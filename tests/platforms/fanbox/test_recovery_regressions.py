import pytest

from video_downloader.platforms.fanbox.archive import ArchiveApplication
from video_downloader.platforms.fanbox.controller import FanboxController
from video_downloader.platforms.fanbox.errors import FanboxError


@pytest.fixture
def queued_controller(tmp_path):
    application = ArchiveApplication(tmp_path / 'files')
    pending = {}

    def start(*args):
        task_id = 'task-' + str(len(pending) + 1)
        pending[task_id] = True
        return {'ok': True, 'task': {'id': task_id}}

    def cancel(job_id, task_id):
        pending[task_id] = False
        return {'ok': True}

    controller = FanboxController(application, tool_dir=tmp_path,
        config_getter=lambda: {}, start=start, cancel=cancel)
    controller.stopping.set()
    controller.thread.join(2)
    controller.is_active = lambda job_id, task_id: pending.get(task_id, False)
    try:
        yield application, controller, pending
    finally:
        controller.stop()


def create(controller):
    return controller.create({'url': 'https://sample.fanbox.cc',
        'request_id': 'recovery-regression'})['job']


def test_pause_before_execution_is_durable_and_can_continue(queued_controller):
    app, controller, pending = queued_controller
    job = create(controller)
    result = controller.action({'id': job['id'], 'action': 'pause'})
    assert result['job']['status'] == 'paused'
    state = app.repository.job(job['id'])
    assert state['status'] == 'paused' and job['id'] not in controller.active
    continued = controller.action({'id': job['id'], 'action': 'continue',
        'version': state['version']})
    assert continued['ok'] and pending[controller.active[job['id']]]


@pytest.mark.parametrize('list_first', [False, True])
def test_cancelled_or_failed_queued_task_is_reconciled(queued_controller, list_first):
    app, controller, pending = queued_controller
    job = create(controller)
    pending[controller.active[job['id']]] = False
    if list_first:
        assert controller.list()[0]['status'] == 'paused'
    state = app.repository.job(job['id'])
    assert controller.action({'id': job['id'], 'action': 'continue',
        'version': state['version']})['ok']


def test_finished_before_archive_run_clears_queued_state(queued_controller):
    app, controller, _ = queued_controller
    job = create(controller)
    controller.finished(job['id'])
    state = app.repository.job(job['id'])
    assert state['status'] == 'paused'
    assert job['id'] not in controller.active
    assert controller.action({'id': job['id'], 'action': 'continue',
        'version': state['version']})['ok']


def test_synchronous_launch_failure_is_durable(queued_controller):
    app, controller, _ = queued_controller

    def fail(*args):
        raise RuntimeError('thread start failed')

    controller.start = fail
    with pytest.raises(FanboxError) as error:
        create(controller)
    assert error.value.code == 'queue_rejected'
    job = app.repository.jobs()[0]
    assert job['status'] == 'paused' and job['id'] not in controller.active


def test_live_queued_or_leased_job_stays_busy(queued_controller):
    app, controller, pending = queued_controller
    job = create(controller)
    assert controller.list()[0]['status'] == 'queued'
    with pytest.raises(FanboxError) as error:
        controller.action({'id': job['id'], 'action': 'continue', 'version': job['version']})
    assert error.value.code == 'job_busy'
    token, _ = app.repository.acquire('job:' + job['id'])
    try:
        controller.action({'id': job['id'], 'action': 'pause'})
        assert not pending[controller.active[job['id']]]
        assert app.repository.job(job['id'])['status'] == 'queued'
    finally:
        app.repository.release(token)
    controller.finished(job['id'])
    assert app.repository.job(job['id'])['status'] == 'paused'
