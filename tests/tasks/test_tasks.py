import threading
import time
import unittest

from video_downloader.state.app_state import AppState
from video_downloader.tasks import TaskManager, TaskStatus


from tests.helpers.tasks import FakeExecutor, make_manager, wait_until


class TaskManagerTests(unittest.TestCase):
    def test_task_completes_and_publishes_snapshot(self):
        manager, state, events, _ = make_manager()
        try:
            result = manager.submit(["https://example.com/video"])
            self.assertTrue(result["ok"])
            task_id = result["task"]["id"]
            self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "completed"))
            self.assertFalse(manager.has_active())
            self.assertTrue(any(event["type"] == "task_snapshot" for event in events))
            task = manager.list_tasks()[0]
            self.assertEqual(task["urls"], ["https://example.com/video"])
            self.assertEqual(task["progress"], 100)
            self.assertEqual(task["history"][0]["status"], "success")
        finally:
            manager.stop()

    def test_failed_task(self):
        manager, state, events, _ = make_manager(mode="fail")
        try:
            result = manager.submit(["https://example.com/video"])
            self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "failed"))
            self.assertIn("失败", manager.list_tasks()[0]["message"])
            self.assertFalse(manager.has_active())
        finally:
            manager.stop()

    def test_queue_waits_when_parallel_is_one(self):
        manager, state, events, tasks = make_manager(max_parallel=1)
        gate = threading.Event()

        class BlockingExecutor(FakeExecutor):
            def start_download(self, url, **kwargs):
                gate.wait(2)
                return super().start_download(url, **kwargs)

        def factory(task, task_state, dm, callbacks, on_finished):
            executor = BlockingExecutor(task, callbacks, on_finished)
            tasks[task.id] = executor
            return executor

        manager._executor_factory = factory
        try:
            first = manager.submit(["https://example.com/1"])["task"]["id"]
            second = manager.submit(["https://example.com/2"])["task"]["id"]
            self.assertTrue(wait_until(lambda: len([t for t in manager.list_tasks() if t["status"] == "running"]) == 1))
            queued = [t for t in manager.list_tasks() if t["status"] == "queued"]
            self.assertEqual(len(queued), 1)
            gate.set()
            self.assertTrue(wait_until(lambda: all(t["status"] == "completed" for t in manager.list_tasks())))
        finally:
            gate.set()
            manager.stop()

    def test_cancel_queued_task(self):
        manager, state, events, tasks = make_manager(max_parallel=1)
        gate = threading.Event()

        class BlockingExecutor(FakeExecutor):
            def start_download(self, url, **kwargs):
                gate.wait(2)
                return super().start_download(url, **kwargs)

        manager._executor_factory = lambda task, ts, dm, cb, done: BlockingExecutor(task, cb, done)
        try:
            first = manager.submit(["https://example.com/1"])["task"]["id"]
            second = manager.submit(["https://example.com/2"])["task"]["id"]
            self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "running"))
            result = manager.cancel(second)
            self.assertEqual(result["task"]["status"], "cancelled")
            gate.set()
            self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "completed"))
        finally:
            gate.set()
            manager.stop()

    def test_max_parallel_and_priority(self):
        manager, state, events, tasks = make_manager(max_parallel=2, order="live_first")
        gate = threading.Event()
        started = []

        class BlockingExecutor(FakeExecutor):
            def start_download(self, url, **kwargs):
                started.append((self.task.kind, url))
                gate.wait(2)
                return super().start_download(url, **kwargs)

        manager._executor_factory = lambda task, ts, dm, cb, done: BlockingExecutor(task, cb, done)
        try:
            manager.submit(["https://example.com/d1"], kind="download")
            manager.submit(["https://example.com/l1"], kind="live")
            self.assertTrue(wait_until(lambda: len(started) == 2))
            # 两个都启动；live_first 只影响排队顺序，不阻止并行。
            self.assertEqual(len(started), 2)
            gate.set()
            self.assertTrue(wait_until(lambda: all(t["status"] == "completed" for t in manager.list_tasks())))
        finally:
            gate.set()
            manager.stop()

    def test_task_app_state_is_isolated(self):
        # TaskAppState 的 stats/progress 不污染基础 AppState。
        manager, state, events, _ = make_manager()
        try:
            manager.submit(["https://example.com/1"])
            self.assertTrue(wait_until(lambda: not manager.has_active()))
            self.assertEqual(state.batch_stats["ok"], 0)
        finally:
            manager.stop()


class TaskRegressionTests(unittest.TestCase):
    def make(self, factory=None, parallel=1, order="none", config=None, history=None):
        state = AppState(config={"TASK_MAX_PARALLEL": parallel, "TASK_ORDER": order, **(config or {})})
        started, executors = [], {}

        class HeldExecutor(FakeExecutor):
            def start_download(self, url, **kwargs):
                self.url = url
                executors[url] = self
                started.append(url)
                self.callbacks.update_progress(0.5, "下载中")
                return {"ok": True}

            def finish(self, status="success"):
                self.callbacks.add_history(self.url, "title", "YouTube", status, "out.mp4")
                self.on_finished(object())

            def stop_download(self):
                self.stopped.set()
                self.on_finished(object())
                return {"ok": True}

        manager = TaskManager(
            base_app_state=state,
            executor_factory=factory or (lambda task, ts, dm, cb, done: HeldExecutor(task, cb, done)),
            max_parallel_getter=lambda: state.config_snapshot()["TASK_MAX_PARALLEL"],
            order_getter=lambda: state.config_snapshot()["TASK_ORDER"],
            add_history=history,
        )
        self.addCleanup(manager.stop)
        return manager, state, started, executors

    def test_fractional_progress_is_scaled_and_aggregated_per_url(self):
        manager, _, started, executors = self.make()
        manager.submit(["https://example.com/1", "https://example.com/2"])
        self.assertTrue(wait_until(lambda: len(started) == 1))
        self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["progress"] == 25))
        executors[started[0]].finish()
        self.assertTrue(wait_until(lambda: len(started) == 2))
        self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["progress"] == 75))
        executors[started[1]].finish()
        self.assertTrue(wait_until(lambda: not manager.has_active()))
        self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["stats"]["ok"] == 2))

    def test_all_archive_skips_complete_without_false_success(self):
        manager, _, started, executors = self.make()
        manager.submit(["https://example.com/skip"])
        self.assertTrue(wait_until(lambda: started))
        executors[started[0]].finish("skipped")
        self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "completed"))
        self.assertEqual(manager.list_tasks()[0]["stats"], {"ok": 0, "fail": 0, "skipped": 1, "total": 1})

    def test_partial_failure_is_not_a_successful_task(self):
        manager, _, started, executors = self.make()
        manager.submit(["https://example.com/1", "https://example.com/2"])
        self.assertTrue(wait_until(lambda: len(started) == 1))
        executors[started[0]].finish("fail")
        self.assertTrue(wait_until(lambda: len(started) == 2))
        executors[started[1]].finish()
        self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "failed"))
        self.assertEqual(manager.list_tasks()[0]["stats"]["fail"], 1)

    def test_priority_only_reorders_queued_tasks_and_preserves_fifo_ties(self):
        manager, _, started, executors = self.make(order="live_first")
        first = "https://example.com/blocker"
        manager.submit([first])
        self.assertTrue(wait_until(lambda: started))
        manager.submit(["https://example.com/download"])
        manager.submit(["https://twitch.tv/live1"])
        manager.submit(["https://twitch.tv/live2"])
        executors[first].finish()
        self.assertTrue(wait_until(lambda: len(started) == 2))
        self.assertEqual(started[1], "https://twitch.tv/live1")
        executors[started[1]].finish()
        self.assertTrue(wait_until(lambda: len(started) == 3))
        self.assertEqual(started[2], "https://twitch.tv/live2")

    def test_internal_live_limit_and_default_serial_order(self):
        manager, state, started, executors = self.make(config={"TASK_LIVE_PARALLEL": 2})
        urls = [f"https://twitch.tv/channel{i}" for i in range(3)]
        manager.submit(urls)
        self.assertTrue(wait_until(lambda: len(started) == 2))
        self.assertEqual(len(manager._runtimes), 1)
        self.assertEqual(len(manager._runtimes[next(iter(manager._runtimes))]["children"]), 2)
        executors[started[0]].finish()
        self.assertTrue(wait_until(lambda: len(started) == 3))
        manager.cancel_all()
        self.assertTrue(wait_until(lambda: not manager.has_active()))
        state.update_config({"TASK_MIXED_PARALLEL": 0})
        started.clear()
        manager.submit(urls)
        self.assertTrue(wait_until(lambda: len(started) == 1))
        self.assertEqual(started[0], urls[0])
        executors[urls[0]].finish()
        self.assertTrue(wait_until(lambda: len(started) == 2))
        self.assertEqual(started[1], urls[1])

    def test_cancel_during_factory_creation_never_starts_cancelled_url(self):
        entered, gate = threading.Event(), threading.Event()
        calls = []

        def factory(task, ts, dm, cb, done):
            entered.set()
            gate.wait(3)
            executor = FakeExecutor(task, cb, done)
            original = executor.start_download
            executor.start_download = lambda url, **kwargs: (calls.append(url), original(url, **kwargs))[1]
            return executor

        manager, _, _, _ = self.make(factory=factory)
        task_id = manager.submit(["https://example.com/cancel"])['task']['id']
        self.assertTrue(entered.wait(2))
        manager.cancel(task_id)
        self.assertTrue(manager.has_active())
        gate.set()
        self.assertTrue(wait_until(lambda: not manager.has_active()))
        self.assertEqual(calls, [])
        self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "cancelled"))

    def test_cancel_all_does_not_dispatch_queued_tasks(self):
        manager, _, started, _ = self.make()
        manager.submit(["https://example.com/1"])
        self.assertTrue(wait_until(lambda: started))
        for number in range(2, 8):
            manager.submit([f"https://example.com/{number}"])
        manager.cancel_all()
        self.assertTrue(wait_until(lambda: not manager.has_active()))
        self.assertEqual(len(started), 1)

    def test_task_config_is_frozen_and_history_is_forwarded(self):
        from unittest.mock import Mock
        from video_downloader.tasks.context import TaskAppState
        from video_downloader.tasks.models import Task

        history = Mock()
        manager, state, started, executors = self.make(history=history)
        state.update_config({"RESOLUTION": "720"})
        task_id = manager.submit(["https://example.com/1"])['task']['id']
        state.update_config({"RESOLUTION": "1080"})
        self.assertEqual(manager._tasks[task_id].config["RESOLUTION"], "720")
        self.assertTrue(wait_until(lambda: started))
        executors[started[0]].finish()
        self.assertTrue(wait_until(lambda: history.called))
        self.assertEqual(history.call_args.args[-1], "out.mp4")
        proxy = TaskAppState(state, Task(urls=["url"]).id)
        proxy.archive_prompt = {"request_id": "isolated"}
        self.assertIsNone(state.archive_prompt)

    def test_duplicate_active_url_rejected_and_submit_after_stop_rejected(self):
        manager, _, started, _ = self.make()
        manager.submit(["https://example.com/1", "https://example.com/1"])
        self.assertEqual(manager.list_tasks()[0]["url_count"], 1)
        self.assertIn("error", manager.submit(["https://example.com/1"]))
        manager.stop()
        self.assertIn("error", manager.submit(["https://example.com/2"]))

    def test_snapshot_read_does_not_deadlock_with_sse_publication(self):
        manager, state, _, _ = self.make()
        entered, read = threading.Event(), threading.Event()

        def publisher():
            with manager._lock:
                entered.set()
                state.publish({"type": "test"})

        with state.sse_lock:
            thread = threading.Thread(target=publisher, daemon=True)
            thread.start()
            self.assertTrue(entered.wait(2))
            reader = threading.Thread(target=lambda: (manager.list_tasks(), read.set()), daemon=True)
            reader.start()
            self.assertTrue(read.wait(1), "SSE reconnect must not wait for the task lock")
        thread.join(2)
        reader.join(2)

    def test_cancel_before_download_handle_creation_prevents_late_begin(self):
        entered, gate = threading.Event(), threading.Event()
        handles = []

        class SlowStart(FakeExecutor):
            def start_download(self, url, **kwargs):
                entered.set()
                gate.wait(3)
                handles.append(self.dm.begin("single"))
                return {"error": "cancelled before begin"}

        def factory(task, ts, dm, cb, done):
            executor = SlowStart(task, cb, done)
            executor.dm = dm
            return executor

        manager, _, _, _ = self.make(factory=factory)
        task_id = manager.submit(["https://example.com/1"])["task"]["id"]
        self.assertTrue(entered.wait(2))
        manager.cancel(task_id)
        gate.set()
        self.assertTrue(wait_until(lambda: not manager.has_active()))
        self.assertEqual(handles, [None])

    def test_early_failure_survives_task_history_truncation(self):
        class ManyExecutor(FakeExecutor):
            def start_download(self, url, **kwargs):
                self.callbacks.add_history(url, "title", "YouTube", "fail" if url.endswith("/0") else "success")
                self.on_finished(None)
                return {"ok": True}

        manager, _, _, _ = self.make(factory=lambda t,s,d,c,f: ManyExecutor(t,c,f))
        manager.submit([f"https://example.com/{i}" for i in range(55)])
        self.assertTrue(wait_until(lambda: not manager.has_active(), timeout=8))
        self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "failed"))
        self.assertEqual(manager.list_tasks()[0]["stats"]["fail"], 1)
        self.assertEqual(manager.list_tasks()[0]["stats"]["ok"], 54)
        self.assertLess(len(manager.list_tasks()[0]["history"]), 55)

    def test_parallel_prompt_responses_are_routed_to_their_own_url(self):
        from unittest.mock import Mock
        manager, _, started, executors = self.make(config={"TASK_LIVE_PARALLEL": 2})
        task_id = manager.submit(["https://twitch.tv/a", "https://twitch.tv/b"])["task"]["id"]
        self.assertTrue(wait_until(lambda: len(started) == 2))
        for number, url in enumerate(started):
            executor = executors[url]
            executor.submit_password = Mock(return_value={"ok": True})
            executor.callbacks.emit_event("password_required", {"url": url, "request_id": f"request-{number}"})
        self.assertTrue(wait_until(lambda: len(manager.list_tasks()[0]["prompts"]) == 2))
        prompts = manager.list_tasks()[0]["prompts"]
        for prompt in prompts:
            result = manager.submit_password(task_id, prompt["url"], "password", prompt["item_id"], prompt["request_id"])
            self.assertTrue(result["ok"])
            executors[prompt["url"]].submit_password.assert_called_once()
        self.assertIn("error", manager.submit_password(task_id, started[0], "password", request_id="stale"))

    def test_legacy_start_is_blocked_until_queue_has_finished(self):
        from unittest.mock import Mock
        manager, _, _, _ = self.make()
        manager.submit(["https://example.com/1"])
        start = Mock(return_value={"ok": True})
        self.assertIn("error", manager.start_exclusive(start))
        start.assert_not_called()

    def test_mixed_batch_allows_live_overlap_but_keeps_downloads_serial(self):
        manager, _, started, executors = self.make(config={"TASK_LIVE_PARALLEL": 3})
        urls = ["https://example.com/1", "https://example.com/2", "https://twitch.tv/live1", "https://twitch.tv/live2"]
        manager.submit(urls)
        self.assertTrue(wait_until(lambda: len(started) == 3))
        self.assertNotIn(urls[1], started)
        self.assertIn(urls[2], started)
        self.assertIn(urls[3], started)
        executors[urls[0]].finish()
        self.assertTrue(wait_until(lambda: urls[1] in started))

    def test_explicit_live_handoff_marks_ambiguous_watch_url_as_live(self):
        manager, _, started, executors = self.make()
        result = manager.submit(["https://youtube.com/watch?v=live"], kind="live")
        self.assertEqual(result["task"]["items"][0]["kind"], "live")

    def test_default_lanes_allow_two_recordings_and_one_video_regardless_of_order(self):
        for live_first in (True, False):
            manager, _, started, executors = self.make()
            videos = [f"https://example.com/video{i}" for i in range(3)]
            lives = [f"https://twitch.tv/channel{i}" for i in range(3)]
            urls = lives + videos if live_first else videos + lives
            manager.submit(urls)
            self.assertTrue(wait_until(lambda: len(started) == 3))
            self.assertEqual(set(started), {videos[0], lives[0], lives[1]})
            executors[videos[0]].finish()
            self.assertTrue(wait_until(lambda: videos[1] in started))
            self.assertNotIn(lives[2], started)
            executors[lives[0]].finish()
            self.assertTrue(wait_until(lambda: lives[2] in started))
            manager.stop()

    def test_independent_limits_allow_five_live_and_five_videos(self):
        manager, _, started, _ = self.make(config={"TASK_LIVE_PARALLEL": 5, "TASK_DOWNLOAD_PARALLEL": 5})
        manager.submit([f"https://twitch.tv/channel{i}" for i in range(6)] +
                       [f"https://example.com/video{i}" for i in range(6)])
        self.assertTrue(wait_until(lambda: len(started) == 10))
        task = manager.list_tasks()[0]
        self.assertEqual(sum("twitch" in url for url in started), 5)
        self.assertEqual(task["download_parallel"], 5)

    def test_master_switch_makes_even_mixed_urls_strictly_serial(self):
        manager, _, started, executors = self.make(config={
            "TASK_MIXED_PARALLEL": 0, "TASK_LIVE_PARALLEL": 5, "TASK_DOWNLOAD_PARALLEL": 5})
        urls = ["https://twitch.tv/a", "https://example.com/v", "https://twitch.tv/b"]
        manager.submit(urls)
        self.assertTrue(wait_until(lambda: len(started) == 1))
        self.assertEqual(started, urls[:1])
        executors[urls[0]].finish()
        self.assertTrue(wait_until(lambda: len(started) == 2))
        self.assertEqual(started, urls[:2])

    def test_parent_concurrency_is_capped_at_five_even_for_old_config(self):
        manager, _, started, _ = self.make(parallel=8)
        for i in range(6):
            manager.submit([f"https://example.com/{i}"])
        self.assertTrue(wait_until(lambda: len(started) == 5))
        self.assertEqual(len(manager._runtimes), 5)

    def test_video_only_speed_budget_never_limits_recording(self):
        states = []
        def factory(task, state, dm, cb, done):
            states.append(state.config_snapshot())
            return FakeExecutor(task, cb, done)
        manager, _, _, _ = self.make(factory=factory, config={
            "TASK_DOWNLOAD_SPEED_LIMIT": .3, "SPEED_LIMIT": 0})
        manager.submit(["https://twitch.tv/a", "https://example.com/v"])
        self.assertTrue(wait_until(lambda: not manager.has_active()))
        self.assertEqual(sorted(s["SPEED_LIMIT"] for s in states), [0, .3])

    def test_invalid_speed_config_finishes_item_with_diagnostic_error(self):
        manager, _, _, _ = self.make(config={"TASK_DOWNLOAD_SPEED_LIMIT": "invalid-speed"})
        manager.submit(["https://example.com/video"])
        self.assertTrue(wait_until(lambda: not manager.has_active()))
        self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "failed"))
        item = manager.list_tasks()[0]["items"][0]
        self.assertIn("invalid-speed", item["error"])
        self.assertIsNotNone(item["finished_at"])




if __name__ == "__main__":
    unittest.main()
