"""Callback-compatible asynchronous archive executor; finalization owns the slot."""
from __future__ import annotations

from pathlib import Path
import threading

from .auth import load_credentials
from .errors import FanboxError
from .naming import confined
from .options import normalize_options


class FanboxExecutor:
    def __init__(self,application,*,tool_dir,app_state,download_manager,callbacks,on_finished=None,
                 job_id=None,preview=False,selection=None):
        self.application,self.tool_dir=application,Path(tool_dir)
        self.state,self.manager,self.callbacks=app_state,download_manager,callbacks
        self.on_finished=on_finished or (lambda handle:None)
        self.job_id,self.preview,self.selection=job_id,preview,selection
        self.requested_job_id=job_id
        self.last_result=None
        self.thread=None

    def start_download(self,url,**kwargs):
        handle=self.manager.begin('fanbox')
        if handle is None:
            return {'error':'当前已有任务或程序正在关闭'}
        try:
            config=self.state.config_snapshot()
            if not int(config.get('FANBOX_ENABLED',1)):
                raise FanboxError('platform_disabled','FANBOX 已关闭')
            options=normalize_options(config.get('FANBOX_OPTIONS','{}'))
            configured=config.get('FANBOX_COOKIE_FILE','')
            cookie=Path(configured) if configured else self.tool_dir/'cookies.txt'
            if configured and not cookie.is_absolute():cookie=self.tool_dir/cookie
            use_cookies=int(config.get('USE_COOKIES',1)) and not int(config.get('FANBOX_ANONYMOUS',0))
            if configured and use_cookies and not cookie.is_file():
                raise FanboxError('cookie_file_missing','FANBOX 凭据文件不存在')
            credentials=load_credentials(cookie if use_cookies and cookie.exists() else None)
            job_id=self.requested_job_id or self.application.create(url,options)['id']
            self.job_id=job_id
            self.callbacks.cancel_idle_timer()
            def worker():
                try:
                    def update(value):
                        label={'scanning':'抓取中','downloading':'下载中','preview':'待选择','paused':'已暂停','finished':'归档完成'}.get(value['phase'],'排队中')
                        self.callbacks.update_progress(-1,label,stage='content')
                        self.callbacks.emit_event('content_progress',{'content_kind':'fanbox','job_id':job_id,
                            'content_stats':value['counts'] or {},'archive_status':value['status']})
                    result=self.application.run(job_id,credentials=credentials,config=config,cancel=handle.cancel_event,
                        preview=self.preview or (not self.requested_job_id and not options['workflow']['auto_download']),
                        selection=self.selection,on_update=update)
                    status=result['status']
                    self.last_result={'status':status,'content_kind':'fanbox','content_stats':result['counts'],
                                      'job_id':job_id,'error':result['error']}
                    self.callbacks.emit_event('content_result',self.last_result)
                    output=str(confined(self.application.root,result['output'])) if result.get('output') else ''
                    if status in {'completed','partial','failed'}:
                        from .urls import parse_source
                        source=parse_source(result.get('source',url))
                        title=source.creator_id or {'supporting':'所有赞助','following':'所有关注'}.get(source.scope,'FANBOX')
                        self.callbacks.add_history(source.url,title,'Fanbox',{'completed':'success','partial':'partial','failed':'fail'}[status],output)
                    self.callbacks.update_progress(1 if status=='completed' else -1,status,stage='content')
                except BaseException:
                    self.last_result={'status':'failed','content_kind':'fanbox','content_stats':{},
                                      'error':{'code':'executor_error','message':'归档执行失败'}}
                    self.callbacks.emit_event('content_result',self.last_result)
                finally:
                    try:
                        self.manager.finish(handle)
                        self.callbacks.broadcast_download_state()
                        self.callbacks.start_idle_timer()
                    except Exception:
                        pass  # A UI observer must not strand a completed task.
                    finally:
                        self.on_finished(handle)
            self.thread=threading.Thread(target=worker,name='fanbox-archive',daemon=True)
            self.thread.start()
            return {'ok':True,'job_id':job_id}
        except (FanboxError,OSError,RuntimeError) as error:
            self.manager.finish(handle)
            self.on_finished(handle)
            return {'error':str(error) if isinstance(error,FanboxError) else '归档任务启动失败'}

    def stop_download(self):
        ticket=self.manager.request_stop(kind_prefix='fanbox')
        return {'ok':True,'stopping':ticket.active}

    def get_current_ytdlp_command(self):
        return {'error':'FANBOX 使用内容归档执行器'}
