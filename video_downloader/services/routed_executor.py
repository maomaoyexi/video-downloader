"""Route native content downloads without adding platform logic to yt-dlp."""
from __future__ import annotations

from dataclasses import replace
import threading

from video_downloader.platforms.fanbox.urls import split_http_url
from video_downloader.platforms.fanbox.errors import FanboxError


def is_fanbox(url):
    try:
        host=split_http_url(url.strip()).hostname.lower()
        return host=='fanbox.cc' or host.endswith('.fanbox.cc')
    except (FanboxError,AttributeError):
        return False


class RoutedDownloadExecutor:
    def __init__(self,video,fanbox,*,batch_factory=None,manager=None,callbacks=None):
        self.video,self.fanbox=video,fanbox
        self.active=video
        self.batch_factory,self.manager,self.callbacks=batch_factory,manager,callbacks
        self.batch_handle=None;self.batch_child=None;self.batch_thread=None

    def __getattr__(self,name):
        return getattr(self.video,name)

    def __setattr__(self,name,value):
        video=self.__dict__.get('video')
        if name not in {'video','fanbox','active','batch_factory','manager','callbacks','batch_handle','batch_child','batch_thread'} and video is not None and hasattr(video,name):
            setattr(video,name,value)
        else:
            object.__setattr__(self,name,value)

    @property
    def last_result(self):
        return getattr(self.active,'last_result',None)

    def start_download(self,url,**kwargs):
        self.active=self.fanbox if is_fanbox(url) else self.video
        return self.active.start_download(url,**kwargs)

    def stop_download(self):
        if self.batch_handle is not None:
            self.manager.request_stop(kind_prefix='fanbox_batch')
            child=self.batch_child
            if child is not None:
                child[1].suspend();child[0].stop_download()
            return {'ok':True,'stopping':True}
        return self.active.stop_download()

    def get_current_ytdlp_command(self):
        if self.batch_child:return self.batch_child[0].get_current_ytdlp_command()
        return self.active.get_current_ytdlp_command()

    def batch_download(self,urls,bili_parts_map=None,custom_args=None):
        if not any(is_fanbox(url) for url in urls):
            return self.video.batch_download(urls,bili_parts_map=bili_parts_map,custom_args=custom_args)
        if self.batch_factory is None:return {'error':'当前执行器不支持混合批量入口'}
        handle=self.manager.begin('fanbox_batch')
        if handle is None:return {'error':'当前已有任务'}
        self.batch_handle=handle
        config=self.fanbox.state.config_snapshot()
        self.callbacks.cancel_idle_timer()
        def worker():
            try:
                from video_downloader.services.download_manager import DownloadManager
                for index,url in enumerate(urls):
                    if handle.cancel_event.is_set():break
                    done=threading.Event();manager=DownloadManager()
                    context=self.fanbox.state.download_thread_context
                    def progress(*args,**kwargs):
                        previous=getattr(context,'task_id',None)
                        context.task_id=handle.generation
                        try:self.callbacks.update_progress(*args,**kwargs)
                        finally:context.task_id=previous
                    callbacks=replace(self.callbacks,update_progress=progress,
                                      broadcast_download_state=lambda:None,start_idle_timer=lambda:None)
                    child=self.batch_factory(manager,callbacks,lambda h:done.set(),config)
                    self.batch_child=(child,manager)
                    if handle.cancel_event.is_set():
                        manager.suspend();break
                    result=child.start_download(url,bili_parts=(bili_parts_map or {}).get(url),custom_args=custom_args)
                    if result.get('error'):
                        self.callbacks.log(result['error'],'error');continue
                    while not done.wait(.1):
                        if handle.cancel_event.is_set():
                            manager.suspend();child.stop_download()
                    self.batch_child=None
            finally:
                self.batch_child=None;self.batch_handle=None
                self.manager.finish(handle)
                self.callbacks.broadcast_download_state()
                self.callbacks.start_idle_timer()
        try:
            self.batch_thread=threading.Thread(target=worker,name='routed-batch',daemon=True)
            self.batch_thread.start()
        except RuntimeError:
            self.batch_handle=None;self.manager.finish(handle)
            return {'error':'批量任务启动失败'}
        self.callbacks.broadcast_download_state()
        return {'ok':True}
