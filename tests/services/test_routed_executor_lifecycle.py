"""Keep cancellation attached to the executor that accepted the current job."""
import pytest

from video_downloader.services.download_manager import DownloadManager
from video_downloader.services.routed_executor import RoutedDownloadExecutor


FANBOX_URL = 'https://sample.fanbox.cc'
VIDEO_URL = 'https://www.youtube.com/watch?v=sample'


class Executor:
    def __init__(self, manager, name):
        self.manager = manager
        self.name = name
        self.handle = None
        self.stop_calls = 0
        self.next_result = None
        self.before_start = None

    def _start(self, kind):
        if self.before_start is not None:
            self.before_start()
        if self.next_result is not None:
            if isinstance(self.next_result, Exception):
                raise self.next_result
            return self.next_result
        handle = self.manager.begin(kind)
        if handle is None:
            return {'error': 'already running'}
        self.handle = handle
        return {'ok': True}

    def start_download(self, url, **kwargs):
        return self._start('fanbox' if self.name == 'fanbox' else 'single')

    def batch_download(self, urls, **kwargs):
        return self._start('batch')

    def start_withny_archive(self):
        return self._start('withny-archive')

    def start_withny_live(self):
        return self._start('withny-live')

    def submit_password(self, url, password, request_id=None):
        self.password_arguments = (url, password, request_id)
        return self._start('single')

    def stop_download(self):
        self.stop_calls += 1
        ticket = self.manager.request_stop(kind_prefix='fanbox' if self.name == 'fanbox' else None)
        return {'ok': True, 'stopping': ticket.active}

    def get_current_ytdlp_command(self):
        return {'command': self.name}

    def complete(self):
        assert self.manager.finish(self.handle)


def make_router():
    manager = DownloadManager()
    video = Executor(manager, 'video')
    fanbox = Executor(manager, 'fanbox')
    return RoutedDownloadExecutor(video, fanbox, manager=manager), video, fanbox


def start_video(router, entry):
    if entry == 'single':
        return router.start_download(VIDEO_URL)
    if entry == 'batch':
        return router.batch_download([VIDEO_URL])
    return getattr(router, 'start_withny_' + entry)()


@pytest.mark.parametrize('entry', ['single', 'batch', 'archive', 'live'])
def test_completed_fanbox_then_video_entry_routes_stop_to_current_job(entry):
    router, video, fanbox = make_router()
    assert router.start_download(FANBOX_URL)['ok']
    fanbox.complete()
    assert not fanbox.manager.snapshot()['running']
    assert start_video(router, entry)['ok']
    assert router.active is video
    assert router.get_current_ytdlp_command() == {'command': 'video'}
    assert router.stop_download()['stopping']
    assert video.handle.cancel_event.is_set()
    assert video.stop_calls == 1 and fanbox.stop_calls == 0


@pytest.mark.parametrize('entry', ['single', 'batch', 'archive', 'live'])
def test_rejected_video_start_preserves_running_fanbox(entry):
    router, video, fanbox = make_router()
    assert router.start_download(FANBOX_URL)['ok']
    assert start_video(router, entry).get('error')
    assert router.active is fanbox
    assert router.stop_download()['stopping']
    assert fanbox.handle.cancel_event.is_set()
    assert fanbox.stop_calls == 1 and video.stop_calls == 0


def test_rejected_fanbox_start_preserves_running_video():
    router, video, fanbox = make_router()
    assert router.start_download(VIDEO_URL)['ok']
    assert router.start_download(FANBOX_URL).get('error')
    assert router.active is video
    assert router.stop_download()['stopping']
    assert video.handle.cancel_event.is_set()
    assert video.stop_calls == 1 and fanbox.stop_calls == 0


@pytest.mark.parametrize('entry', ['archive', 'live'])
def test_cancelled_withny_dialog_keeps_previous_executor(entry):
    router, video, fanbox = make_router()
    assert router.start_download(FANBOX_URL)['ok']
    fanbox.complete()
    video.next_result = {'ok': True, 'cancelled': True}
    assert start_video(router, entry)['cancelled']
    assert router.active is fanbox
    assert not video.manager.snapshot()['running']


@pytest.mark.parametrize('result', [{'error': 'startup failed'}, {'ok': False}, RuntimeError('failed')])
def test_failed_fanbox_start_keeps_previous_executor(result):
    router, video, fanbox = make_router()
    fanbox.next_result = result
    if isinstance(result, Exception):
        with pytest.raises(RuntimeError, match='failed'):
            router.start_download(FANBOX_URL)
    else:
        assert router.start_download(FANBOX_URL) == result
    assert router.active is video


def test_executor_is_changed_only_after_start_accepts_job():
    router, video, fanbox = make_router()
    def check_previous():
        assert router.active is video
    fanbox.before_start = check_previous
    assert router.start_download(FANBOX_URL)['ok']
    assert router.active is fanbox


@pytest.mark.parametrize('entry', ['single', 'batch', 'archive', 'live'])
@pytest.mark.parametrize('result', [{'error': 'startup failed'}, {'ok': False}, RuntimeError('failed')])
def test_failed_video_start_keeps_completed_fanbox_executor(entry, result):
    router, video, fanbox = make_router()
    assert router.start_download(FANBOX_URL)['ok']
    fanbox.complete()
    video.next_result = result
    if isinstance(result, Exception):
        with pytest.raises(RuntimeError, match='failed'):
            start_video(router, entry)
    else:
        assert start_video(router, entry) == result
    assert router.active is fanbox


def test_password_retry_start_routes_to_video_and_preserves_request_id():
    router, video, fanbox = make_router()
    assert router.start_download(FANBOX_URL)['ok']
    fanbox.complete()
    assert router.submit_password(VIDEO_URL, 'synthetic-password', request_id='request-1')['ok']
    assert video.password_arguments == (VIDEO_URL, 'synthetic-password', 'request-1')
    assert router.active is video
    assert router.stop_download()['stopping']
    assert video.handle.cancel_event.is_set()


def test_rejected_password_retry_keeps_running_fanbox():
    router, video, fanbox = make_router()
    assert router.start_download(FANBOX_URL)['ok']
    assert router.submit_password(VIDEO_URL, 'synthetic-password').get('error')
    assert router.active is fanbox
    assert router.stop_download()['stopping']
    assert fanbox.handle.cancel_event.is_set()


def test_password_retry_that_only_wakes_a_batch_keeps_current_route():
    router, video, fanbox = make_router()
    assert router.start_download(FANBOX_URL)['ok']
    video.next_result = {'ok': True, 'mode': 'batch_retry'}
    assert router.submit_password(VIDEO_URL, 'synthetic-password')['mode'] == 'batch_retry'
    assert router.active is fanbox


def test_independent_task_routers_keep_parallel_jobs_and_cancellation_separate():
    first, first_video, first_fanbox = make_router()
    second, second_video, second_fanbox = make_router()
    assert first.start_download(FANBOX_URL)['ok']
    assert second.start_download(VIDEO_URL)['ok']
    assert first_fanbox.manager.snapshot()['running']
    assert second_video.manager.snapshot()['running']
    assert first.stop_download()['stopping']
    assert first_fanbox.handle.cancel_event.is_set()
    assert not second_video.handle.cancel_event.is_set()
    assert second.stop_download()['stopping']
    assert second_video.handle.cancel_event.is_set()
