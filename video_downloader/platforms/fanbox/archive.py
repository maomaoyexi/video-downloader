"""Durable author archives composed from the pure P1 scan and IO adapters."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid

from .auth import load_credentials
from .binary import BinaryTransport
from .cli import credential_scope, proxy_from_config
from .client import FanboxClient
from .downloader import Downloader
from .errors import FanboxError
from .exporters import export_post,export_index
from .fan_cards import save_card
from .models import Post
from .naming import confined
from .options import normalize_options,options_json
from .parsers import parse_post
from .repository import Repository
from .scheduling import AccountGate
from .service import ScanService, write_json
from .transport import CurlTransport, HttpTransport
from .urls import parse_source,source_for_options

_PAUSES={'cancelled','lease_expired','quota_exceeded','quota_busy','rate_limited','challenge_required','access_denied','fallback_required','conflict_required'}


def summary(state):
    result={key:copy.deepcopy(state.get(key)) for key in
            ('id','source','status','version','created_at','updated_at','counts','error','scope','output','phase','outcome','resume_after')}
    result['notify']=state['options'].get('notifications',{}).get('on_complete',False)
    return result


class ArchiveApplication:
    def __init__(self, root, *, repository=None, transport_factory=None,binary_factory=None,publish=None):
        self.root=Path(root)
        self._repository=repository
        self._repository_lock=threading.Lock()
        self.transport_factory=transport_factory
        self.binary_factory=binary_factory or BinaryTransport
        self.publish=publish or (lambda event:None)

    @property
    def repository(self):
        # An unavailable optional archive must not prevent other platforms or
        # the application's configuration UI from starting.
        with self._repository_lock:
            if self._repository is None:
                self._repository=Repository(confined(self.root,'.fanbox/library.sqlite',create=True))
            return self._repository

    def create(self,url,options=None,*,request_key=None,fingerprint=None):
        options=normalize_options(options)
        source=source_for_options(url,options)
        state={'id':uuid.uuid4().hex,'source':source.url,'options':options,
               'created_at':time.time(),'task_date':datetime.now(timezone.utc).isoformat(),
               'status':'queued','phase':'queued','counts':{},'files':{},'archives':[],
               'checkpoint':None,'scan':None,'auth_scope':None,'selection':{},'error':None,
               'scope':{},'output':'','outcome':'','resume_after':None}
        if request_key is not None:
            return self.repository.create_requested(state,request_key,fingerprint)
        self.repository.save_job(state)
        return state

    def run(self,job_id,*,credentials=None,config=None,cancel=None,preview=False,selection=None,on_update=None):
        state=self.repository.job(job_id)
        if state is None:
            raise FanboxError('job_not_found','归档任务不存在')
        cancel=cancel or threading.Event()
        config=config or {}
        credentials=credentials or load_credentials()
        options=normalize_options(state['options'])
        old_scan_options=state.get('scan_options',state['options'])
        scan_options=normalize_options(old_scan_options)
        checkpoint=state.get('checkpoint')
        if checkpoint and scan_options!=old_scan_options:
            old_digest=hashlib.sha256(json.dumps(old_scan_options,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if checkpoint.get('options_digest')==old_digest:
                checkpoint['options_digest']=hashlib.sha256(options_json(scan_options).encode()).hexdigest()
        state['options']=options
        state['scan_options']=scan_options
        job_token,_=self.repository.acquire('job:'+job_id)
        if job_token is None:
            raise FanboxError('job_busy','归档任务仍在运行或等待崩溃租约释放')
        gate=AccountGate(self.repository,cancel,options['network']['api_interval_seconds'],heartbeat_tokens=[job_token])
        lock=threading.RLock()
        received={}
        last_progress=[0.]

        def log(message,level='info'):
            with lock:
                entries=state.setdefault('logs',[])
                entry={'time':datetime.now().strftime('%H:%M:%S'),'msg':'[FANBOX] '+message,
                       'level':level,'job_id':job_id,'seq':entries[-1]['seq']+1 if entries else 1}
                entries.append(entry);state['logs']=entries[-500:]
            try:self.publish({'type':'fanbox_log','data':entry})
            except Exception:pass

        def scan_event(kind,data):
            if kind=='listing':log(f"列表页 {data['pages']} 抓取完成 · 当前 {data['posts']} 篇投稿")
            else:log(f"投稿 {data['id']} · "+('正文受限' if data['restricted'] else f"可保存 {data['files']} 个文件"),
                     'warn' if data['restricted'] else 'info')

        def save(*,terminal=False):
            if terminal:
                if not self.repository.save_terminal_job(state,job_token):return
            else:
                self.repository.save_job(state,lease_token=job_token)
            event={'type':'fanbox_job','data':summary(state)}
            try:
                self.publish(event)
                if on_update:on_update(event['data'])
            except Exception:
                pass

        def stats():
            posts=state['scan']['posts'] if state['scan'] else []
            results=[record for files in state['files'].values() for record in files.values()]
            state['counts']={'posts':len(posts),'restricted':sum(p['access']=='restricted' for p in posts),
                'completed':sum(r['status']=='completed' for r in results),
                'reused':sum(r['status']=='reused' for r in results),
                'failed':sum(r['status']=='failed' for r in results),
                'degraded':sum(r['status']=='degraded' for r in results),
                'skipped':sum(r['status']=='skipped' for r in results),
                'bytes_received':sum(received.values()),'links':sum(len(p['links']) for p in posts)}
            cards=state.get('fan_cards',[])
            state['counts']['fan_cards']=sum(card['status']=='completed' for card in cards)
            state['counts']['fan_cards_failed']=sum(card['status']=='failed' for card in cards)

        def progress(**data):
            with lock:
                received[data['key']]=received.get(data['key'],0)+data['delta']
                if time.monotonic()-last_progress[0]>.5:
                    stats();save();last_progress[0]=time.monotonic()

        try:
            scope=credential_scope(credentials)
            if state['auth_scope'] not in (None,scope):
                raise FanboxError('credentials_changed','登录快照已改变，请创建新抓取任务')
            state['auth_scope']=scope
            state['error']=None
            state['resume_after']=None
            state['status']='running'
            state['phase']='scanning'
            log('开始抓取 · '+state['source'])
            save()
            proxy=proxy_from_config(config,options)
            factory=self.transport_factory or (CurlTransport if options['network']['engine']=='curl' else HttpTransport)
            with factory(credentials,proxy=proxy,gate=gate) as transport:
                client=FanboxClient(transport)
                if options['fan_cards']['only'] and state['scan'] is None:
                    state['scan']={'posts':[],'status':'completed','errors':[]}
                    state['scope']={'scope':'fan_cards','list_complete':False}
                if state['scan'] is None or (state['scan']['status']!='completed' and not preview):
                    def checkpoint(value):
                        state['checkpoint']=value
                        save()
                    result=ScanService(client).scan(state['source'],scan_options,
                        checkpoint=state['checkpoint'],save_checkpoint=checkpoint,auth_scope=scope,notify=scan_event)
                    state['scan']={key:value for key,value in result.items() if key!='checkpoint'}
                    state['checkpoint']=result['checkpoint']
                    state['scope']=result['coverage']
                    stats()
                    log(f"抓取完毕 · 投稿 {state['counts']['posts']} · 受限 {state['counts']['restricted']} · 链接 {state['counts']['links']}",'success')
                    if result['errors']:
                        error=result['errors'][0]
                        if error['code'] in _PAUSES:
                            raise FanboxError(error['code'],error['message'],retry_after=error.get('retry_after'))
                if preview:
                    state['status']='preview_ready'
                    state['phase']='preview'
                    log('预览已就绪，等待选择下载内容','success')
                    stats();save()
                    return summary(state)
                if selection is not None:
                    state['selection']=copy.deepcopy(selection)
                state['phase']='downloading'
                log('开始下载')
                save()
                selected=state['selection'].get('post_ids')
                chosen_assets=state['selection'].get('asset_ids')
                binary=self.binary_factory(credentials,proxy=proxy,
                    speed=int(float(config.get('SPEED_LIMIT',0))*1024*1024/options['network']['file_concurrency']))
                downloader=Downloader(self.root,self.repository,gate,binary,progress=progress)
                state['archives']=state['archives'] if state.get('retry_only') else []
                if options['fan_cards']['enabled']:
                    log('开始保存粉丝卡')
                    state['fan_cards']=[]
                    try:
                        current_source=parse_source(state['source'])
                        if options['fan_cards']['scope']=='current' and not current_source.creator_id:
                            raise FanboxError('card_scope_required','集合任务请明确选择所有赞助作者的粉丝卡')
                        creators=(client.supporting_creators() if options['fan_cards']['scope']=='all_supporting'
                                  else [current_source.creator_id])
                        if not creators:raise FanboxError('no_supporting_creators','当前账号没有可用的赞助粉丝卡')
                    except FanboxError as error:
                        if error.code in _PAUSES:raise
                        creators=[]
                        state['fan_cards'].append({'creator_id':'','status':'failed','error':error.to_dict()})
                        log('粉丝卡保存失败 · '+str(error),'warn')
                        stats();save()
                    for creator in creators:
                        gate.check()
                        try:
                            card=save_card(self.root,client,downloader,creator,options,state['task_date'])
                            log('粉丝卡保存完成 · '+creator,'success')
                        except FanboxError as error:
                            if error.code in _PAUSES:raise
                            card={'creator_id':creator,'status':'failed','error':error.to_dict()}
                            log('粉丝卡保存失败 · '+creator+' · '+str(error),'warn')
                        state['fan_cards'].append(card);stats();save()
                for value in state['scan']['posts']:
                    gate.check()
                    post=Post.from_dict(value)
                    if selected is not None and post.id not in selected:
                        continue
                    if (post.id in state['selection'].get('exclude_post_ids',[])
                            or state['selection'].get('accessible_only') and post.access=='restricted'
                            or state['selection'].get('title_query','').casefold() not in post.title.casefold()):
                        continue
                    results=state['files'].setdefault(post.id,{})

                    def one(asset):
                        gate.check()
                        def refresh():
                            updated=parse_post(client.post(post.id,post.creator_id),options)
                            return next((a for a in updated.assets if a.id==asset.id and a.variant==asset.variant and a.kind==asset.kind),None)
                        try:
                            result=downloader.download(post,asset,options,state['task_date'],refresh=refresh)
                        except FanboxError as error:
                            if error.code in _PAUSES:
                                cancel.set()
                                raise
                            result={'status':'failed','error':error.to_dict()}
                        with lock:
                            results[asset.id+':'+asset.variant]=result
                            label={'completed':'下载完成','reused':'跳过已保存文件','skipped':'按规则跳过','degraded':'已降级为缩略图','failed':'下载失败'}[result['status']]
                            log(f"{label} · 投稿 {post.id} · {asset.name[:160]}",'warn' if result['status'] in {'failed','degraded'} else 'info')
                            stats();save()

                    assets=[a for a in post.assets if a.selected and (post.access!='restricted' or a.kind=='cover') and
                            (chosen_assets is None or post.id+':'+a.id+':'+a.variant in chosen_assets)
                            and post.id+':'+a.id+':'+a.variant not in state['selection'].get('exclude_asset_ids',[])]
                    if assets:
                        with ThreadPoolExecutor(max_workers=options['network']['file_concurrency']) as workers:
                            futures=[workers.submit(one,asset) for asset in assets]
                            errors=[]
                            for future in as_completed(futures):
                                try:future.result()
                                except FanboxError as error:errors.append(error)
                            if errors:
                                raise next((e for e in errors if e.code!='cancelled'),errors[0])
                    entry=export_post(self.root,self.repository,post,options,state['task_date'],results)
                    state['archives']=[old for old in state['archives'] if old['post_id']!=post.id]+[entry]
                    stats();save()
                stats()
                counts=state['counts']
                partial=(counts['failed'] or counts['degraded'] or counts['restricted'] or counts['fan_cards_failed']
                         or state['scan']['status']!='completed')
                state['status']='partial' if partial else 'completed'
                if counts['failed'] and not (counts['completed'] or counts['reused'] or
                        options['content']['body'] and any(p['blocks'] for p in state['scan']['posts'])):
                    state['status']='failed'
                if options['fan_cards']['only'] and not counts['fan_cards']:state['status']='failed'
                state['outcome']='empty' if not state['archives'] and not counts['fan_cards'] else 'restricted' if counts['posts'] and counts['restricted']==counts['posts'] else state['status']
                state['phase']='finished'
                log(f"下载结束 · 完成 {counts['completed']} · 复用 {counts['reused']} · 失败 {counts['failed']} · 降级 {counts['degraded']} · 粉丝卡 {counts['fan_cards']} · 粉丝卡失败 {counts['fan_cards_failed']}",
                    'success' if state['status']=='completed' else 'warn')
                state['output']=export_index(self.root,state) if state['archives'] or counts['fan_cards'] else ''
                manifest={'schema_version':1,'source':state['source'],'status':state['status'],
                          'coverage':state['scope'],'counts':counts,'posts':state['archives'],'files':state['files'],
                          'fan_cards':state.get('fan_cards',[])}
                write_json(confined(self.root,f'.fanbox/manifests/{state["id"]}.json',create=True),manifest)
                save()
        except FanboxError as error:
            state['status']='paused' if error.code in _PAUSES else 'failed'
            state['phase']='paused' if state['status']=='paused' else 'finished'
            state['error']=error.to_dict()
            log(str(error),'warn' if state['status']=='paused' else 'error')
            if error.code=='quota_exceeded' and options['quota']['on_limit']=='next_day':
                state['resume_after']=self.repository._day(self.repository.clock(),options['quota']['timezone'])[1]*60
            stats();save(terminal=True)
        except KeyboardInterrupt:
            state['status']='paused';state['phase']='paused'
            state['error']={'code':'cancelled','message':'任务已暂停','retry_after':None}
            stats();save(terminal=True)
            raise
        except (OSError,ValueError,TypeError) as error:
            state['status']='failed';state['phase']='finished'
            state['error']={'code':'archive_error','message':'归档写入或响应处理失败','retry_after':None}
            stats();save(terminal=True)
        finally:
            self.repository.release(job_token)
        return summary(state)
