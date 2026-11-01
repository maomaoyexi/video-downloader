from types import SimpleNamespace
import threading

import pytest

from video_downloader.platforms.fanbox.executor import FanboxExecutor
from video_downloader.services.download_manager import DownloadManager
from video_downloader.services.routed_executor import RoutedDownloadExecutor,is_fanbox
from video_downloader.state.app_state import AppState
from video_downloader.tasks.manager import TaskCallbacks


def callbacks(**overrides):
    values={key:(lambda *a,**kw:None) for key in TaskCallbacks.__dataclass_fields__}
    values.update(overrides)
    return TaskCallbacks(**values)


class Application:
    def __init__(self,status='completed'):
        self.root=None;self.sources=[];self.status=status
    def create(self,url,options):
        self.sources.append(url)
        return {'id':str(len(self.sources))}
    def run(self,job_id,**kwargs):
        kwargs['on_update']({'phase':'downloading','counts':{'posts':1},'status':'running'})
        return {'id':job_id,'status':self.status,'counts':{},'output':'','error':None}


def test_executor_new_request_gets_new_job_and_finalizes_exactly_once(tmp_path):
    app=Application();manager=DownloadManager();finished=[]
    executor=FanboxExecutor(app,tool_dir=tmp_path,app_state=AppState(),download_manager=manager,
                            callbacks=callbacks(),on_finished=lambda handle:finished.append(handle))
    for name in ['alice','bob']:
        assert executor.start_download('https://'+name+'.fanbox.cc')['ok']
        executor.thread.join(3)
        assert not manager.snapshot()['running']
    assert len(finished)==2 and len(app.sources)==2
    assert executor.last_result['status']=='completed'


def test_finish_callback_runs_even_if_state_notification_raises(tmp_path):
    def fail(*_):raise RuntimeError('notification error')
    finished=threading.Event();manager=DownloadManager()
    executor=FanboxExecutor(Application(),tool_dir=tmp_path,app_state=AppState(),download_manager=manager,
        callbacks=callbacks(broadcast_download_state=fail),on_finished=lambda _:finished.set())
    assert executor.start_download('https://alice.fanbox.cc')['ok']
    assert finished.wait(3) and not manager.snapshot()['running']
    executor.thread.join(3)


def test_start_failure_and_duplicate_start_do_not_leak_slots(tmp_path,monkeypatch):
    manager=DownloadManager();finished=[]
    executor=FanboxExecutor(Application(),tool_dir=tmp_path,app_state=AppState(),download_manager=manager,
        callbacks=callbacks(),on_finished=lambda h:finished.append(h))
    monkeypatch.setattr(threading.Thread,'start',lambda self:(_ for _ in ()).throw(RuntimeError('failed')))
    assert executor.start_download('https://alice.fanbox.cc').get('error')
    assert len(finished)==1 and not manager.snapshot()['running']
    manager.begin('other')
    assert executor.start_download('https://alice.fanbox.cc').get('error')
    assert len(finished)==1


def test_router_keeps_fanbox_out_of_video_fallback():
    video=SimpleNamespace(start_download=lambda *a,**kw:{'video':True},stop_download=lambda:1)
    fanbox=SimpleNamespace(start_download=lambda *a,**kw:{'fanbox':True},stop_download=lambda:2,last_result={'status':'partial'})
    router=RoutedDownloadExecutor(video,fanbox)
    assert router.start_download('https://www.fanbox.cc')['fanbox']
    assert router.stop_download()==2 and router.last_result['status']=='partial'
    assert router.start_download('https://www.youtube.com/watch?v=1')['video']
    assert not is_fanbox('https://fanbox.cc.evil.test/@sample')
