"""Exercise durable FANBOX recovery through the real application wiring."""
import json
import threading

import pytest

from video_downloader.container import AppContainer
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.tasks import TaskManager
from tests.helpers.tasks import wait_until
from .test_archive_io import Body
from .test_content import post
from .test_scan import FakeTransport


class OfflineTransport(FakeTransport):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture
def wired_recovery(tmp_path, monkeypatch):
    managers = []

    class ControlledTaskManager(TaskManager):
        def __init__(self, **kwargs):
            self.allow_dispatch = threading.Event()
            super().__init__(**kwargs)
            managers.append(self)

        def _dispatch(self):
            if self.allow_dispatch.is_set():
                super()._dispatch()

    monkeypatch.setattr('video_downloader.container.TaskManager', ControlledTaskManager)
    monkeypatch.setattr('video_downloader.container.create_handler', lambda dependencies: dependencies)
    app = AppContainer(tmp_path).wire()
    app.app_state.replace_config({'TASK_MODE': 1, 'TASK_MAX_PARALLEL': 2,
        'FANBOX_ANONYMOUS': 1, 'FANBOX_ENABLED': 1,
        'FANBOX_OPTIONS': json.dumps({'network': {
            'api_interval_seconds': 0, 'file_start_interval_seconds': 0}})})
    dependencies = app.http_service._handler_factory()
    controller = dependencies.fanbox
    controller.stopping.set()
    controller.thread.join(2)
    application = controller.application
    application.transport_factory = lambda *args, **kwargs: OfflineTransport([[post()]])
    application.binary_factory = lambda *args, **kwargs: Body()
    try:
        yield app, dependencies, controller, managers[0]
    finally:
        app.request_exit()


def create(controller):
    return controller.create({'url': 'https://sample.fanbox.cc',
        'request_id': 'task-recovery-integration'})['job']


def continue_job(controller, job_id):
    state = controller.application.repository.job(job_id)
    return controller.action({'id': job_id, 'action': 'continue', 'version': state['version']})


def assert_completed(controller, manager, job_id):
    manager.allow_dispatch.set()
    manager._wake.set()
    assert wait_until(lambda: controller.application.repository.job(job_id)['status'] == 'completed')
    assert wait_until(lambda: not manager.has_active())
    assert wait_until(lambda: job_id not in controller.active)


def test_controller_pause_of_real_queued_task_can_continue(wired_recovery):
    app, dependencies, controller, manager = wired_recovery
    job = create(controller)
    first_task = controller.active[job['id']]
    assert manager.is_task_active(first_task)
    assert controller.is_active(job['id'], first_task)
    paused = controller.action({'id': job['id'], 'action': 'pause'})
    assert paused['job']['status'] == 'paused'
    assert not manager.is_task_active(first_task)
    assert job['id'] not in controller.active
    assert continue_job(controller, job['id'])['ok']
    assert controller.active[job['id']] != first_task
    assert_completed(controller, manager, job['id'])


@pytest.mark.parametrize('list_first', [False, True])
def test_task_list_cancellation_reconciles_before_continue(wired_recovery, list_first):
    app, dependencies, controller, manager = wired_recovery
    job = create(controller)
    first_task = controller.active[job['id']]
    assert dependencies.cancel_task(first_task)['ok']
    assert not controller.is_active(job['id'], first_task)
    if list_first:
        assert controller.list()[0]['status'] == 'paused'
    assert continue_job(controller, job['id'])['ok']
    assert controller.active[job['id']] != first_task
    assert_completed(controller, manager, job['id'])


def test_executor_start_failure_cleans_queue_and_can_retry_after_fixing_config(wired_recovery):
    app, dependencies, controller, manager = wired_recovery
    app.app_state.update_config({'FANBOX_ANONYMOUS': 0, 'USE_COOKIES': 1,
        'FANBOX_COOKIE_FILE': 'missing-test-cookie.txt'})
    job = create(controller)
    first_task = controller.active[job['id']]
    manager.allow_dispatch.set()
    manager._wake.set()
    assert wait_until(lambda: not manager.is_task_active(first_task))
    state = controller.application.repository.job(job['id'])
    assert state['status'] == 'paused'
    assert state['error']['code'] == 'interrupted'
    assert job['id'] not in controller.active
    assert not controller.application.repository.has_lease('job:' + job['id'])
    app.app_state.update_config({'FANBOX_ANONYMOUS': 1, 'FANBOX_COOKIE_FILE': ''})
    assert continue_job(controller, job['id'])['ok']
    assert_completed(controller, manager, job['id'])


def test_legacy_start_failure_can_retry_without_restarting(wired_recovery):
    app, dependencies, controller, manager = wired_recovery
    app.app_state.update_config({'TASK_MODE': 0, 'FANBOX_ANONYMOUS': 0,
        'USE_COOKIES': 1, 'FANBOX_COOKIE_FILE': 'missing-test-cookie.txt'})
    with pytest.raises(FanboxError) as error:
        create(controller)
    assert error.value.code == 'queue_rejected'
    state = controller.application.repository.jobs()[0]
    assert state['status'] == 'paused' and state['id'] not in controller.active
    app.app_state.update_config({'FANBOX_ANONYMOUS': 1, 'FANBOX_COOKIE_FILE': ''})
    assert continue_job(controller, state['id'])['ok']
    assert_completed(controller, manager, state['id'])


def test_existing_job_lease_prevents_relaunch_even_after_queue_cancel(wired_recovery):
    app, dependencies, controller, manager = wired_recovery
    job = create(controller)
    repository = controller.application.repository
    token, _ = repository.acquire('job:' + job['id'])
    try:
        assert dependencies.cancel_task(controller.active[job['id']])['ok']
        with pytest.raises(FanboxError) as error:
            continue_job(controller, job['id'])
        assert error.value.code == 'job_busy'
        assert repository.job(job['id'])['status'] == 'queued'
    finally:
        repository.release(token)
    assert continue_job(controller, job['id'])['ok']
    assert_completed(controller, manager, job['id'])
