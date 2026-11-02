import threading

from video_downloader.platforms.fanbox.archive import ArchiveApplication
from video_downloader.platforms.fanbox.repository import Repository

from .test_content import post
from .test_scan import FakeTransport
from .test_archive_io import Body, DATA


class VirtualCancel:
    def __init__(self, now, cancel_after=None):
        self.now, self.cancel_after = now, cancel_after
        self.cancelled = False

    def is_set(self):
        return self.cancelled

    def set(self):
        self.cancelled = True

    def wait(self, seconds):
        self.now[0] += seconds
        if self.cancel_after is not None and self.now[0] >= self.cancel_after:
            self.set()
        return self.cancelled


def setup_archive(tmp_path, *, file=False, expire=False, cancel_after=None):
    now = [1000.]
    repository = Repository(tmp_path / '.fanbox/library.sqlite', clock=lambda: now[0])
    value = post('file', {'text': 'public text', 'files': [
        {'id': 'asset', 'name': 'sample', 'extension': 'bin',
         'url': 'https://downloads.fanbox.cc/sample.bin', 'size': len(DATA)}]}) if file else post('text', {'text': 'body'})

    class ScheduledTransport(FakeTransport):
        def __init__(self, gate):
            super().__init__([[value]])
            self.gate = gate
            self.expired = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get_json(self, url):
            with self.gate:
                result = super().get_json(url)
                if expire and not self.expired:
                    self.expired = True
                    now[0] += 121
                return result

    app = ArchiveApplication(tmp_path, repository=repository,
        transport_factory=lambda *a, **kw: ScheduledTransport(kw['gate']),
        binary_factory=lambda *a, **kw: Body())
    job = app.create('https://sample.fanbox.cc', {'network': {
        'api_interval_seconds': 0 if file or expire else 180,
        'file_start_interval_seconds': 180 if file else 0}})
    if file:
        token, _ = repository.acquire('file', interval=180)
        repository.release(token)
    return app, job, now, VirtualCancel(now, cancel_after)


def test_long_api_interval_keeps_job_lease_alive(tmp_path):
    app, job, now, cancel = setup_archive(tmp_path)
    result = app.run(job['id'], cancel=cancel)
    assert now[0] >= 1360
    assert result['status'] == 'completed'
    assert app.repository.job(job['id'])['status'] == 'completed'
    assert not app.repository.has_lease('job:' + job['id'])


def test_long_file_start_interval_keeps_job_and_asset_leases_alive(tmp_path):
    app, job, now, cancel = setup_archive(tmp_path, file=True)
    result = app.run(job['id'], cancel=cancel)
    assert now[0] >= 1180
    assert result['status'] == 'completed'
    assert result['counts']['completed'] == 1


def test_long_wait_can_still_be_cancelled_and_resumed(tmp_path):
    app, job, now, cancel = setup_archive(tmp_path, cancel_after=1005)
    result = app.run(job['id'], cancel=cancel)
    assert result['status'] == 'paused' and result['error']['code'] == 'cancelled'
    assert app.repository.job(job['id'])['status'] == 'paused'
    cancel.cancelled = False
    cancel.cancel_after = None
    assert app.run(job['id'], cancel=cancel)['status'] == 'completed'


def test_unexpected_expiry_persists_recoverable_terminal_state(tmp_path):
    app, job, _, cancel = setup_archive(tmp_path, expire=True)
    result = app.run(job['id'], cancel=cancel)
    saved = app.repository.job(job['id'])
    assert result['status'] == saved['status'] == 'paused'
    assert saved['error']['code'] == 'lease_expired'
    assert not app.repository.has_lease('job:' + job['id'])
