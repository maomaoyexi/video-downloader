"""FANBOX task boundaries and ownership of legacy archive prompts."""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.helpers.download import create_executor
from tests.helpers.tasks import make_manager
from tests.platforms.fanbox.test_executor import callbacks
from video_downloader.services.download_manager import DownloadManager
from video_downloader.services.routed_executor import RoutedDownloadExecutor
from video_downloader.state.app_state import AppState


FANBOX = 'https://sample.fanbox.cc'
VIDEO = 'https://www.youtube.com/watch?v=sample'


@pytest.mark.parametrize('urls', [[FANBOX, VIDEO], [VIDEO, FANBOX]])
def test_legacy_mixed_batch_is_rejected_before_starting_any_item(urls):
    manager = DownloadManager()
    started = []

    def factory(dm, cb, finished, config):
        def start(url, **kwargs):
            started.append(url)
            finished(None)
            return {'ok': True}
        return SimpleNamespace(start_download=start)

    router = RoutedDownloadExecutor(SimpleNamespace(), SimpleNamespace(state=AppState()),
        manager=manager, callbacks=callbacks(), batch_factory=factory)
    result = router.batch_download(urls)
    if router.batch_thread:
        router.batch_thread.join(1)
    assert 'error' in result and 'FANBOX' in result['error']
    assert not started and not manager.snapshot()['running']


def test_task_mode_also_rejects_a_parent_containing_fanbox_and_video():
    manager, state, events, tasks = make_manager()
    try:
        result = manager.submit([FANBOX, VIDEO])
        assert 'error' in result and 'FANBOX' in result['error']
        assert manager.list_tasks() == []
    finally:
        manager.stop()


def test_separate_fanbox_and_video_tasks_are_both_accepted():
    manager, state, events, tasks = make_manager(max_parallel=2)
    try:
        fanbox = manager.submit([FANBOX])
        video = manager.submit([VIDEO])
        assert fanbox['ok'] and video['ok']
        assert fanbox['task']['id'] != video['task']['id']
    finally:
        manager.stop()


def test_task_liveness_reads_queued_and_cancelled_state_under_the_lock():
    manager, state, events, tasks = make_manager()
    try:
        assert not manager.is_task_active('missing')
        with manager._lock:
            task_id = manager.submit([FANBOX])['task']['id']
            assert manager.is_task_active(task_id)
            manager.cancel(task_id)
            assert not manager.is_task_active(task_id)
    finally:
        manager.stop()


@pytest.mark.parametrize('task_mode', [0, 1])
def test_container_multiline_and_text_file_entries_reject_mixed_fanbox(tmp_path, monkeypatch, task_mode):
    from video_downloader.container import AppContainer

    monkeypatch.setattr('video_downloader.container.create_handler', lambda dependencies: dependencies)
    app = AppContainer(tmp_path).wire()
    try:
        app.app_state.update_config({'TASK_MODE': task_mode})
        dependencies = app.http_service._handler_factory()
        (tmp_path / 'urls.txt').write_text(FANBOX + '\n' + VIDEO, encoding='utf-8')
        assert 'FANBOX' in dependencies.start_urls_download([FANBOX, VIDEO])['error']
        assert 'FANBOX' in dependencies.batch_txt_download()['error']
        assert dependencies.list_tasks() == []
    finally:
        app.request_exit()


def test_legacy_archive_choice_reaches_the_child_that_emitted_it(tmp_path):
    outer, outer_callbacks = create_executor(tmp_path)
    child, child_callbacks = create_executor(tmp_path)
    child._app_state.sse_clients.append(Queue())
    router = RoutedDownloadExecutor(outer, SimpleNamespace())
    router.batch_child = (child, child._download_manager)
    handle = child._download_manager.begin('single')
    child.ARCHIVE_CHOICE_TIMEOUT = .05
    responses = []

    def answer(event, data):
        if event == 'archive_choice_required':
            responses.append(router.submit_archive_choice(data['request_id'], True))

    child_callbacks['emit_event'].side_effect = answer
    try:
        assert child._wait_for_archive_choice(handle, VIDEO, 'YouTube', {'sample'})
        assert responses == [{'ok': True}]
    finally:
        child._download_manager.finish(handle)


def test_fanbox_active_does_not_forward_a_stale_choice_to_video(tmp_path):
    video, _ = create_executor(tmp_path)
    video.submit_archive_choice = Mock(return_value={'ok': True})
    router = RoutedDownloadExecutor(video, SimpleNamespace())
    router.active = router.fanbox
    assert 'error' in router.submit_archive_choice('stale-request', True)
    video.submit_archive_choice.assert_not_called()


def test_batch_between_children_does_not_fall_back_to_outer_video(tmp_path):
    video, _ = create_executor(tmp_path)
    video.submit_archive_choice = Mock(return_value={'ok': True})
    router = RoutedDownloadExecutor(video, SimpleNamespace())
    router.batch_handle = object()
    assert 'error' in router.submit_archive_choice('previous-child', True)
    video.submit_archive_choice.assert_not_called()


def test_nested_task_router_keeps_archive_choices_on_its_active_video(tmp_path):
    video, cb = create_executor(tmp_path)
    video._app_state.sse_clients.append(Queue())
    router = RoutedDownloadExecutor(video, SimpleNamespace())
    handle = video._download_manager.begin('single')
    responses = []
    cb['emit_event'].side_effect = lambda event, data: responses.append(
        router.submit_archive_choice(data['request_id'], True)
    ) if event == 'archive_choice_required' else None
    try:
        assert video._wait_for_archive_choice(handle, VIDEO, 'YouTube', {'sample'})
        assert responses == [{'ok': True}]
    finally:
        video._download_manager.finish(handle)
