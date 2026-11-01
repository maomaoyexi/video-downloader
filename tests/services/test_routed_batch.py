from types import SimpleNamespace
import threading

from video_downloader.services.routed_executor import RoutedDownloadExecutor
from video_downloader.services.download_manager import DownloadManager
from video_downloader.state.app_state import AppState
from tests.platforms.fanbox.test_executor import callbacks


def test_exclusive_mixed_batch_routes_sequentially_without_deadlock():
    manager=DownloadManager();state=AppState();seen=[]
    def factory(dm,cb,finished,config):
        def start(url,**kwargs):
            handle=dm.begin('test');assert handle
            seen.append(url);dm.finish(handle);finished(handle)
            return {'ok':True}
        return SimpleNamespace(start_download=start,stop_download=lambda:None)
    video=SimpleNamespace(batch_download=lambda *a,**kw:{'old':True},stop_download=lambda:None)
    router=RoutedDownloadExecutor(video,SimpleNamespace(state=state),manager=manager,
                                  callbacks=callbacks(),batch_factory=factory)
    urls=['https://www.youtube.com/watch?v=test','https://sample.fanbox.cc']
    assert router.batch_download(urls)['ok'];router.batch_thread.join(3)
    assert seen==urls and not manager.snapshot()['running']
    assert router.batch_download([urls[0]])=={'old':True}


def test_exclusive_batch_stop_does_not_start_later_item():
    manager=DownloadManager();entered=threading.Event();seen=[]
    def factory(dm,cb,finished,config):
        def start(url,**kw):
            handle=dm.begin('test');seen.append(url);entered.set()
            def worker():
                handle.cancel_event.wait(3);dm.finish(handle);finished(handle)
            threading.Thread(target=worker,daemon=True).start()
            return {'ok':True}
        def stop():dm.request_stop()
        return SimpleNamespace(start_download=start,stop_download=stop)
    router=RoutedDownloadExecutor(SimpleNamespace(),SimpleNamespace(state=AppState()),manager=manager,
        callbacks=callbacks(),batch_factory=factory)
    assert router.batch_download(['https://sample.fanbox.cc','https://other.fanbox.cc'])['ok']
    assert entered.wait(2);router.stop_download();router.batch_thread.join(3)
    assert len(seen)==1 and not manager.snapshot()['running']
