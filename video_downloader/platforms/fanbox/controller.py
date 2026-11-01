"""Authenticated HTTP facade: snapshots, optimistic commands and durable intents."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import webbrowser

from .archive import summary
from .auth import load_credentials
from .errors import FanboxError
from .naming import confined
from .models import Post
from .options import normalize_options,import_plugin_settings
from .runtime import health
from .presentation import asset_rows,manifest,naming_preview
from .records import preview_records,resource_record_key
from .maintenance import clear_resume_cache
from .verification import VerificationService,report_header


class FanboxController:
    def __init__(self,application,*,tool_dir,config_getter,start,cancel,publish=None):
        self.application,self.root=application,Path(tool_dir)
        self.config=config_getter;self.start=start;self.cancel=cancel
        self.publish=publish or (lambda event:None)
        self.lock=threading.RLock();self.active={}
        self.verifier=VerificationService(application,self._verification_event)
        self._snapshot=[];self.access_error=None
        self.stopping=threading.Event()
        self.thread=threading.Thread(target=self._loop,name='fanbox-recovery',daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=2)
        self.verifier.stop()

    def _verification_event(self,job_id,report):
        values=self.application.repository.summaries(job_id=job_id,limit=1)
        if values:self.publish({'type':'fanbox_job','data':values[0]})

    def _summary(self,state):
        value=summary(state)
        value['verification']=report_header(self.application.repository.verification(state['id']),state['version'])
        return value

    def _loop(self):
        while not self.stopping.wait(1):
            try:
                # Runtime state is never auto-resumed after a crash. Only the
                # user's explicit next-day policy schedules future work.
                if not int(self.config().get('FANBOX_ENABLED',1)):continue
                for state in self.list():
                    if (state.get('resume_after') and state['resume_after']<=time.time()
                            and state['status']=='paused' and int(self.config().get('FANBOX_ENABLED',1))):
                        self.action({'id':state['id'],'version':state['version'],'action':'continue'})
            except Exception:
                pass

    def snapshot(self):
        return copy.deepcopy(self._snapshot)

    def list(self):
        try:
            values=self._list()
            self._snapshot=values;self.access_error=None
            return values
        except Exception:
            self.access_error='归档数据库不可用'
            return self.snapshot()

    def _list(self):
        if not int(self.config().get('FANBOX_ENABLED',1)):
            return []
        with self.lock:
            result=[]
            for state in self.application.repository.summaries():
                verification=state.get('verification')
                if verification and verification['status']=='running' and not self.application.repository.has_lease('job:'+state['id']):
                    report=self.application.repository.verification(state['id']);report['status']='interrupted'
                    self.application.repository.save_verification(state['id'],report);state['verification']=report_header(report)
                if state['status'] not in {'running','queued'} and not self.application.repository.has_lease('job:'+state['id']):
                    self.active.pop(state['id'],None)
                if state['status'] in {'running','queued'} and state['id'] not in self.active and not self.application.repository.has_lease('job:'+state['id']):
                    state=self.application.repository.job(state['id'])
                    state['status']='paused';state['phase']='paused'
                    state['error']={'code':'interrupted','message':'任务已中断，可继续','retry_after':None}
                    self.application.repository.save_job(state)
                    result.append(self._summary(state))
                else:result.append(state)
            return result

    def options(self):
        config=self.config()
        return {'options':normalize_options(config.get('FANBOX_OPTIONS','{}')),'defaults':normalize_options(),
                'enabled':bool(int(config.get('FANBOX_ENABLED',1))),
                'anonymous':bool(int(config.get('FANBOX_ANONYMOUS',0))),
                'cookie_file':config.get('FANBOX_COOKIE_FILE','')}

    def auth_status(self):
        config=self.config();name=config.get('FANBOX_COOKIE_FILE') or 'cookies.txt'
        path=Path(name)
        if not path.is_absolute():path=self.root/path
        loaded=False
        if int(config.get('USE_COOKIES',1)) and not int(config.get('FANBOX_ANONYMOUS',0)) and path.is_file():
            loaded=load_credentials(path).has_session
        return {'status':'loaded' if loaded else 'anonymous','runtime':health(),'checked_at':time.time()}

    def _launch(self,state,preview):
        result=self.start(state['id'],state['source'],preview,state.get('selection',{}))
        if result.get('error'):
            state['status']='paused';state['phase']='paused'
            state['error']={'code':'queue_rejected','message':result['error'],'retry_after':None}
            self.application.repository.save_job(state)
            raise FanboxError('queue_rejected',result['error'])
        self.active[state['id']]=result.get('task',{}).get('id') or 'exclusive'
        return result

    def finished(self,job_id):
        with self.lock:
            self.active.pop(job_id,None)

    def create(self,data):
        if not isinstance(data.get('url'),str) or type(data.get('preview',False)) is not bool:
            raise FanboxError('invalid_request','来源或预览参数无效')
        key=data.get('request_id')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',key):
            raise FanboxError('invalid_request','缺少有效请求标识')
        config=self.config()
        if not int(config.get('FANBOX_ENABLED',1)):
            raise FanboxError('platform_disabled','FANBOX 已关闭')
        options=normalize_options(data.get('options',config.get('FANBOX_OPTIONS','{}')))
        fingerprint=hashlib.sha256(json.dumps({'url':data['url'],'preview':data.get('preview',False),
            'options':data.get('options')},sort_keys=True).encode()).hexdigest()
        with self.lock:
            state,new=self.application.create(data['url'],options,request_key=key,fingerprint=fingerprint)
            if new:self._launch(state,data.get('preview',not options['workflow']['auto_download']))
            latest=self.application.repository.job(state['id'])
            return {'ok':True,'job':summary(latest),'replayed':not new}

    def history(self,source):
        from .urls import parse_source
        source=parse_source(source).url
        return {'source':source,'runs':self.application.repository.summaries(source,10000)}

    def records(self,export=False):
        repository=self.application.repository
        result=repository.record_stats()
        if export:result['records']=[{'url':row['path'].lstrip('/')} for row in repository.url_records()]
        return result

    def usage(self):
        zone=self.options()['options']['quota']['timezone']
        return {'timezone':zone,'days':self.application.repository.usage_history(zone)}

    def record_command(self,data):
        action=data.get('action');repository=self.application.repository
        if action=='clear':return {'removed':repository.clear_url_records(),**repository.record_stats()}
        if action not in {'preview','import'}:raise FanboxError('invalid_request','记录操作无效')
        paths,report=preview_records(data.get('records'))
        if action=='import':report['inserted']=repository.import_url_records(paths)
        return report

    def logs(self,job_id):
        state=self.application.repository.job(job_id)
        if state is None:raise FanboxError('job_not_found','归档任务不存在')
        return {'logs':copy.deepcopy(state.get('logs',[]))}

    def manifest(self,job_id):
        state=self.application.repository.job(job_id)
        if state is None:raise FanboxError('job_not_found','归档任务不存在')
        value=manifest(state);value['verification']=self.application.repository.verification(job_id)
        if value['verification'] and value['verification']['job_version']!=state['version']:value['verification']['status']='stale'
        if value['verification'] and value['verification']['job_version']!=state['version']:value['verification']['status']='stale'
        return value

    def naming_preview(self,data):
        return naming_preview(data.get('options',self.config().get('FANBOX_OPTIONS','{}')),
                              data.get('url') or 'https://www.fanbox.cc/@creator')

    def detail(self,job_id,*,offset=0,limit=25,post_id=None,query=''):
        state=self.application.repository.job(job_id)
        if not state:raise FanboxError('job_not_found','归档任务不存在')
        posts=(state.get('scan') or {}).get('posts',[])
        if not isinstance(query,str) or len(query)>500:raise FanboxError('invalid_request','筛选条件无效')
        if query:posts=[p for p in posts if query.casefold() in p['title'].casefold()]
        if post_id is not None:
            value=next((p for p in posts if p['id']==post_id),None)
            if value is None:raise FanboxError('post_not_found','投稿不存在')
            model=Post.from_dict(value)
            effective_options=normalize_options(state['options'])
            assets=asset_rows(state,model,effective_options)
            paths=[resource_record_key(asset.url) for asset in model.assets]
            hints=self.application.repository.imported_hints(paths)
            for asset,path in zip(assets,paths):asset['history_hint']=path in hints
            return {'job':self._summary(state),'post':{k:copy.deepcopy(value[k]) for k in
                     ('id','title','type','published_at','fee','access','blocks','links','comments','comments_complete','warnings')},'assets':assets}
        if type(offset) is not int or type(limit) is not int or offset<0 or not 1<=limit<=100:
            raise FanboxError('invalid_request','分页参数无效')
        items=[]
        for p in posts[offset:offset+limit]:
            selected=[a for a in p['assets'] if a['selected']]
            items.append({k:p[k] for k in ('id','title','type','published_at','fee','access')})
            items[-1].update(resources=len(selected),links=len(p['links']),known_bytes=sum(a['size'] or 0 for a in selected),
                             unknown_sizes=sum(a['size'] is None for a in selected))
        verification=self.application.repository.verification(job_id)
        if verification and verification['job_version']!=state['version']:verification['status']='stale'
        return {'job':self._summary(state),'posts':items,'total':len(posts),'offset':offset,'limit':limit,
                'options':state['options'],'fan_cards':copy.deepcopy(state.get('fan_cards',[])),'verification':verification}

    def action(self,data):
        job_id=data.get('id');action=data.get('action')
        if not isinstance(job_id,str) or not re.fullmatch('[a-f0-9]{32}',job_id):
            raise FanboxError('invalid_request','任务标识无效')
        with self.lock:
            state=self.application.repository.job(job_id)
            if not state:raise FanboxError('job_not_found','归档任务不存在')
            if action in {'verify','cancel_verification'}:
                if action=='verify':
                    if type(data.get('version')) is not int:raise FanboxError('invalid_request','缺少任务版本')
                    self.verifier.start(job_id,data['version'])
                else:self.verifier.cancel(job_id)
                return {'ok':True,'job':self._summary(self.application.repository.job(job_id))}
            if action=='pause':
                target=self.active.get(job_id)
                if target:self.cancel(job_id,target)
                return {'ok':True,'job':summary(state)}
            if action=='open':
                if not state.get('output'):raise FanboxError('output_missing','归档尚未生成')
                path=confined(self.application.root,state['output'])
                if not path.is_file():raise FanboxError('output_missing','归档文件已移走')
                webbrowser.open(path.resolve().as_uri())
                return {'ok':True}
            if action=='clear_cache':
                if type(data.get('version')) is not int:raise FanboxError('invalid_request','缺少任务版本')
                updated,report=clear_resume_cache(self.application,job_id,data['version'])
                return {'ok':True,'job':summary(updated),'cache':report}
            if action not in {'download','continue','retry_failed'} or type(data.get('version')) is not int:
                raise FanboxError('invalid_request','任务操作或版本无效')
            if state['status'] not in {'running','queued'} and not self.application.repository.has_lease('job:'+job_id):
                self.active.pop(job_id,None)
            if state['status'] in {'running','queued'} or job_id in self.active:
                raise FanboxError('job_busy','任务已在运行或排队')
            selection=data.get('selection',state.get('selection',{}))
            if action=='retry_failed':
                failed=[post_id+':'+key for post_id,files in state['files'].items()
                        for key,record in files.items() if record.get('status') in {'failed','degraded'}]
                if not failed:raise FanboxError('nothing_to_retry','没有可单独重试的失败文件')
                selection={'asset_ids':failed,'post_ids':list(dict.fromkeys(key.split(':')[0] for key in failed))}
            self._selection(selection,state)
            if action=='download':selection=dict(selection,accessible_only=True) if isinstance(selection,dict) else selection
            state['selection']=selection
            state['retry_only']=action=='retry_failed'
            # Runtime policies may be revised while content and names remain
            # frozen; this makes quota/fallback/conflict decisions actionable.
            current=normalize_options(data.get('options',state['options']))
            state.setdefault('scan_options',copy.deepcopy(state['options']))
            state['options']['quota']=current['quota']
            state['options']['content']['image_fallback']=current['content']['image_fallback']
            state['options']['naming']['conflict']=current['naming']['conflict']
            state['resume_after']=None;state['error']=None
            state['status']='queued';state['phase']='queued'
            self.application.repository.transition(state,data['version'])
            self._launch(state,False)
            return {'ok':True,'job':summary(self.application.repository.job(job_id))}

    @staticmethod
    def _selection(selection,state):
        if not isinstance(selection,dict) or set(selection)-{'post_ids','asset_ids','exclude_post_ids','exclude_asset_ids','accessible_only','title_query'}:
            raise FanboxError('invalid_request','选择参数无效')
        posts=(state.get('scan') or {}).get('posts',[])
        allowed={p['id'] for p in posts if p['access']!='restricted'}
        all_assets={p['id']+':'+a['id']+':'+a['variant'] for p in posts for a in p['assets'] if a['selected']}
        for name,valid in [('post_ids',allowed),('asset_ids',all_assets),('exclude_post_ids',allowed),('exclude_asset_ids',all_assets)]:
            if name in selection and (not isinstance(selection[name],list) or len(selection[name])>100000
                    or any(not isinstance(v,str) or v not in valid for v in selection[name])):
                raise FanboxError('invalid_request','选择包含不可用内容')
        if ('accessible_only' in selection and type(selection['accessible_only']) is not bool
                or 'title_query' in selection and (not isinstance(selection['title_query'],str) or len(selection['title_query'])>500)):
            raise FanboxError('invalid_request','选择表达式无效')
