"""Validated conditional Range transfers, durable partials and atomic promotion."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from .errors import FanboxError
from .naming import asset_path, confined
from .service import write_json
from .transport import retry_after
from .records import resource_record_key


def resource_key(post, asset):
    # URL query credentials and CDN host changes do not change resource identity.
    identity=(post.creator_id,post.id,post.updated_at,asset.kind,asset.id,asset.variant,
              urlsplit(asset.url).path,asset.size)
    return hashlib.sha256(repr(identity).encode()).hexdigest()


def digest_file(path):
    digest=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def valid_payload(asset, prefix):
    lower=prefix.lstrip().lower()
    if asset.extension not in {'html','htm','txt','json'} and lower.startswith((b'<!doctype',b'<html',b'{"error',b'{"body')):
        raise FanboxError('invalid_payload','资源返回了网页或错误文档')
    signatures={'jpg':lambda b:b.startswith(b'\xff\xd8\xff'),'jpeg':lambda b:b.startswith(b'\xff\xd8\xff'),
                'png':lambda b:b.startswith(b'\x89PNG\r\n\x1a\n'),'gif':lambda b:b.startswith((b'GIF87a',b'GIF89a')),
                'webp':lambda b:b.startswith(b'RIFF') and b[8:12]==b'WEBP'}
    if asset.kind in {'image','cover'} and asset.extension in signatures and not signatures[asset.extension](prefix):
        raise FanboxError('invalid_payload','图片文件头与预期类型不一致')


class Downloader:
    def __init__(self, root, repository, gate, transport, *, progress=None):
        self.root,self.repository,self.gate,self.transport=Path(root),repository,gate,transport
        self.progress=progress or (lambda **kw:None)

    def download(self,post,asset,options,task_date,*,refresh=None):
        last=None
        for attempt in range(3):
            self.gate.check()
            try:
                return self._one(post,asset,options,task_date)
            except FanboxError as error:
                last=error
                if error.code=='file_skipped':
                    return {'status':'skipped','variant':asset.variant,'reason':'existing_file'}
                if error.code in {'access_denied','not_found'} and refresh and attempt==0:
                    updated=refresh()
                    if updated is not None:
                        asset=updated
                        continue
                if error.code not in {'network_error','server_error','incomplete_file','range_restart','quota_busy'}:
                    break
                self.gate.wait(.2*(attempt+1))
        if asset.kind=='image' and asset.variant=='original' and asset.thumbnail_url and last.code in {'access_denied','not_found','invalid_payload'}:
            fallback=options['content']['image_fallback']
            if fallback=='ask':
                raise FanboxError('fallback_required','原图不可用，等待图片质量选择')
            if fallback=='allow':
                extension=Path(urlsplit(asset.thumbnail_url).path).suffix.lstrip('.') or asset.extension
                result=self._one(post,replace(asset,url=asset.thumbnail_url,variant='thumbnail',extension=extension),options,task_date)
                return dict(result,status='degraded',reason=last.code)
        raise last

    def _one(self,post,asset,options,task_date):
        key=resource_key(post,asset)
        token=self.gate.acquire('asset:'+key)
        try:
            candidate=asset_path(post,asset,options,task_date)
            relative=self.repository.allocate(key,candidate,conflict=options['naming']['conflict'],
                                             exists=lambda name:confined(self.root,name).exists())
            target=confined(self.root,relative,create=True)
            old=self.repository.asset(key)
            if options['archive']['incremental'] and old.get('status')=='completed' and target.is_file():
                if target.stat().st_size==old['size'] and digest_file(target)==old['sha256']:
                    return dict(old,status='reused',key=key,variant=asset.variant)
            part=confined(self.root,f'.fanbox/parts/{key}.part',create=True)
            meta=confined(self.root,f'.fanbox/parts/{key}.json',create=True)
            import json
            try:
                previous=json.loads(meta.read_text(encoding='utf-8'))
            except (OSError,ValueError):
                previous={}
            offset=part.stat().st_size if part.is_file() else 0
            etag=previous.get('etag','')
            if offset and (not isinstance(etag,str) or not etag.startswith('"') or previous.get('key')!=key):
                part.unlink(missing_ok=True)
                offset=0
            headers={'Range':f'bytes={offset}-','If-Range':etag} if offset else {}
            state={'total':asset.size,'received':0,'expected_body':None,'file':None,'complete':False,'prefix':b''}
            touched=[time.monotonic()]
            with self.gate.file(options) as file_token:
                def reserve(expected):
                    while True:
                        self.gate.check()
                        try:
                            return self.repository.reserve(file_token,options['quota'],expected)
                        except FanboxError as error:
                            if error.code!='quota_busy':raise
                            self.repository.heartbeat(file_token)
                            self.repository.heartbeat(token)
                            self.gate.wait(.1)
                budget=reserve(max(0,asset.size-offset) if asset.size is not None else None)

                def response(status, data):
                    self.gate.check()
                    if status==429:
                        delay=retry_after(data.get('retry-after'))
                        delay=360 if delay is None else delay
                        self.gate.defer(delay)
                        raise FanboxError('rate_limited','FANBOX 请求频率受限',retry_after=delay)
                    if status in {401,403}:
                        code='challenge_required' if 'html' in data.get('content-type','').lower() else 'access_denied'
                        raise FanboxError(code,'附件需要重新验证访问权限')
                    if status==404:
                        raise FanboxError('not_found','附件不存在或当前不可访问')
                    if status>=500:
                        raise FanboxError('server_error','附件服务暂时不可用')
                    if status==416:
                        match=re.fullmatch(r'bytes \*/([0-9]+)',data.get('content-range',''))
                        if match and offset==int(match[1]) and data.get('etag')==etag and offset:
                            state['total']=offset
                            state['complete']=True
                            return
                        part.unlink(missing_ok=True)
                        meta.unlink(missing_ok=True)
                        raise FanboxError('range_restart','服务器拒绝续传，重新下载')
                    if status not in {200,206}:
                        raise FanboxError('unexpected_redirect' if 300<=status<400 else 'http_error','附件返回未预期状态')
                    if data.get('content-encoding','identity').lower() not in {'identity',''}:
                        raise FanboxError('invalid_range','附件返回压缩传输，无法可靠计量续传')
                    length=data.get('content-length')
                    if length is not None and not str(length).isdigit():
                        raise FanboxError('invalid_range','附件长度无效')
                    state['expected_body']=int(length) if length is not None else None
                    start=0
                    if status==206:
                        match=re.fullmatch(r'bytes ([0-9]+)-([0-9]+)/([0-9]+)',data.get('content-range',''))
                        if offset and data.get('etag')!=etag:
                            part.unlink(missing_ok=True)
                            meta.unlink(missing_ok=True)
                            raise FanboxError('range_restart','续传文件版本已改变，重新下载')
                        if (not match or int(match[1])!=offset or not int(match[1])<=int(match[2])<int(match[3])
                                or (length is not None and int(length)!=int(match[2])-int(match[1])+1)
                                or (offset and data.get('etag')!=etag)):
                            raise FanboxError('invalid_range','续传范围或版本校验失败')
                        start=int(match[1]);state['total']=int(match[3])
                    elif length is not None:
                        state['total']=int(length)
                    if asset.size is not None and state['total']!=asset.size:
                        raise FanboxError('resource_changed','附件大小已改变，请重新抓取投稿')
                    required=state['expected_body']
                    if required is not None:
                        reserve(required)
                    mode='ab' if start else 'wb'
                    write_json(meta,{'key':key,'etag':data.get('etag',''),'total':state['total']})
                    state['file']=part.open(mode)
                    if start:
                        with part.open('rb') as existing:state['prefix']=existing.read(32)

                def chunk(data):
                    self.gate.check()
                    if time.monotonic()-touched[0]>1:
                        self.repository.heartbeat(token)
                        touched[0]=time.monotonic()
                    if state['complete']:
                        if data:raise FanboxError('invalid_range','416 响应包含非预期正文')
                        return
                    if state['file'] is None:
                        raise FanboxError('invalid_response','附件响应缺少有效头部')
                    state['prefix']=(state['prefix']+data)[:32]
                    if len(state['prefix'])>=12:
                        valid_payload(asset,state['prefix'])
                    state['file'].write(data)
                    state['received']+=len(data)

                def meter(count):
                    self.repository.charge(file_token,count)
                    self.progress(key=key,delta=count,bytes=state['received'],total=state['expected_body'])

                try:
                    self.transport.transfer(asset.url,headers,response,chunk,
                        maximum=(budget+offset if budget is not None else None),
                        meter=meter)
                finally:
                    if state['file'] is not None:
                        state['file'].flush()
                        os.fsync(state['file'].fileno())
                        state['file'].close()
                if not part.exists():
                    raise FanboxError('incomplete_file','附件尚未写入')
                if state['total'] is not None and part.stat().st_size!=state['total']:
                    raise FanboxError('incomplete_file','附件长度不完整，保留续传数据')
                if state['expected_body'] is not None and state['received']!=state['expected_body'] and not state['complete']:
                    raise FanboxError('incomplete_file','附件响应长度不完整')
                with part.open('rb') as file:valid_payload(asset,file.read(32))
                result={'status':'completed','size':part.stat().st_size,'sha256':digest_file(part),
                        'variant':asset.variant,'key':key,'path':relative,
                        'resource_path':resource_record_key(asset.url)}
                # Recheck parent/link boundaries immediately before promotion.
                target=confined(self.root,relative,create=True)
                os.replace(part,target)
                self.repository.save_asset(key,result)
                meta.unlink(missing_ok=True)
                return result
        finally:
            self.repository.release(token)
