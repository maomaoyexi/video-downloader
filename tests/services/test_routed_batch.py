from types import SimpleNamespace
import threading

import pytest

from video_downloader.services.routed_executor import RoutedDownloadExecutor
from video_downloader.services.download_manager import DownloadManager
from video_downloader.state.app_state import AppState
from tests.platforms.fanbox.test_executor import callbacks


def test_exclusive_fanbox_batch_routes_sequentially_without_deadlock():
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
    urls=['https://sample.fanbox.cc','https://other.fanbox.cc']
    assert router.batch_download(urls)['ok'];router.batch_thread.join(3)
    assert seen==urls and not manager.snapshot()['running']
    assert router.batch_download(['https://www.youtube.com/watch?v=test'])=={'old':True}


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


def test_failed_batch_thread_start_restores_idle_timer(monkeypatch):
    manager = DownloadManager()
    idle_resumed = threading.Event()
    router = RoutedDownloadExecutor(
        SimpleNamespace(), SimpleNamespace(state=AppState()), manager=manager,
        callbacks=callbacks(start_idle_timer=idle_resumed.set),
        batch_factory=lambda *args: None,
    )

    def fail_start(self):
        raise RuntimeError('thread unavailable')

    monkeypatch.setattr(threading.Thread, 'start', fail_start)
    assert router.batch_download(['https://sample.fanbox.cc']).get('error')
    assert not manager.snapshot()['running']
    assert idle_resumed.is_set(), 'failed startup must resume automatic idle shutdown'


def test_failed_batch_start_callback_releases_slot_and_restores_idle_timer():
    manager = DownloadManager()
    idle_resumed = threading.Event()

    def fail_cancel_idle():
        raise RuntimeError('timer unavailable')

    router = RoutedDownloadExecutor(
        SimpleNamespace(), SimpleNamespace(state=AppState()), manager=manager,
        callbacks=callbacks(cancel_idle_timer=fail_cancel_idle, start_idle_timer=idle_resumed.set),
        batch_factory=lambda *args: None,
    )
    try:
        router.batch_download(['https://sample.fanbox.cc'])
    except RuntimeError:
        pass
    assert not manager.snapshot()['running'], 'startup callback failure must release the exclusive slot'
    assert idle_resumed.is_set()


@pytest.mark.parametrize('stage', ['config_snapshot', 'cancel_idle_timer'])
@pytest.mark.parametrize('error_type', [RuntimeError, OSError, ValueError])
def test_failed_batch_preparation_releases_slot_and_allows_retry(stage, error_type):
    manager = DownloadManager()
    idle_resumed = threading.Event()
    failing = True
    seen = []

    def prepare(name):
        if failing and stage == name:
            raise error_type('fixture preparation failure')
        return {}

    def factory(child_manager, child_callbacks, finished, config):
        def start(url, **kwargs):
            handle = child_manager.begin('fixture')
            seen.append(url)
            child_manager.finish(handle)
            finished(handle)
            return {'ok': True}
        return SimpleNamespace(start_download=start)

    state = AppState()
    state.config_snapshot = lambda: prepare('config_snapshot')
    router = RoutedDownloadExecutor(
        SimpleNamespace(), SimpleNamespace(state=state), manager=manager,
        callbacks=callbacks(cancel_idle_timer=lambda: prepare('cancel_idle_timer'),
                            start_idle_timer=idle_resumed.set),
        batch_factory=factory,
    )
    url = 'https://sample.fanbox.cc'
    assert router.batch_download([url]).get('error')
    assert not manager.snapshot()['running']
    assert router.batch_handle is None
    assert idle_resumed.is_set()

    failing = False
    idle_resumed.clear()
    assert router.batch_download([url])['ok']
    router.batch_thread.join(3)
    assert seen == [url]
    assert not manager.snapshot()['running']
    assert idle_resumed.is_set()


def test_failed_batch_start_notification_still_restores_idle_timer():
    manager = DownloadManager()
    idle_resumed = threading.Event()

    def fail_preparation():
        raise RuntimeError('fixture preparation failure')

    def fail_notification():
        raise OSError('fixture notification failure')

    router = RoutedDownloadExecutor(
        SimpleNamespace(), SimpleNamespace(state=AppState()), manager=manager,
        callbacks=callbacks(cancel_idle_timer=fail_preparation,
                            broadcast_download_state=fail_notification,
                            start_idle_timer=idle_resumed.set),
        batch_factory=lambda *args: None,
    )
    with pytest.raises(OSError, match='fixture notification failure'):
        router.batch_download(['https://sample.fanbox.cc'])
    assert not manager.snapshot()['running']
    assert router.batch_handle is None
    assert idle_resumed.is_set()
