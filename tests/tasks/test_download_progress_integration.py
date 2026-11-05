"""真实任务调度与下载执行器之间的进度回放，不访问网络或用户配置。"""
import tempfile
import threading
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import Mock

from tests.helpers.download import CompletedProcess
from tests.helpers.tasks import wait_until
from video_downloader.services.download_executor import DownloadExecutor
from video_downloader.state.app_state import AppState
from video_downloader.tasks import TaskManager


class TaskDownloadProgressIntegrationTests(unittest.TestCase):
    def test_estimate_stage_and_independent_tasks_keep_their_own_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependencies = root / "dependency"
            dependencies.mkdir()
            for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
                (dependencies / name).touch()
            state = AppState(config={
                "PLATFORM": "YouTube", "TASK_MAX_PARALLEL": 2,
                "TASK_ORDER": "none", "AUDIO_MODE": "0",
            })
            channels = {}

            def factory(task, task_state, dm, callbacks, on_finished):
                lines, done = Queue(), threading.Event()
                executor = DownloadExecutor(
                    tool_dir=root, exe_suffix=".exe", app_state=task_state,
                    download_manager=dm, build_command=Mock(return_value=["yt-dlp"]),
                    log=callbacks.log, update_progress=callbacks.update_progress,
                    broadcast_download_state=callbacks.broadcast_download_state,
                    add_history=callbacks.add_history,
                    cancel_idle_timer=callbacks.cancel_idle_timer,
                    start_idle_timer=callbacks.start_idle_timer,
                    emit_event=callbacks.emit_event, on_finished=on_finished,
                )
                executor._spawn = Mock(return_value=CompletedProcess())
                executor._start_reader = Mock(return_value=(lines, done))
                channels[task.id] = (lines, done)
                return executor

            manager = TaskManager(
                base_app_state=state, executor_factory=factory,
                max_parallel_getter=lambda: 2, order_getter=lambda: "none",
            )

            def task_snapshot(task_id):
                return next((task for task in manager.list_tasks() if task["id"] == task_id), {})

            sequence = 0

            def progress(task_id, percent, expected, stage="video"):
                nonlocal sequence
                sequence += 1
                speed = f"{sequence}.0MiB/s"
                codecs = "none|mp4a" if stage == "audio" else "avc1|none"
                channels[task_id][0].put(
                    f"[download] {percent:.1f}% of Unknown at {speed} ETA 00:30 "
                    f"__VD_STAGE__{codecs}"
                )
                # 等待本条回放真正被执行器消费和任务快照公开；速度区分相同百分比。
                self.assertTrue(wait_until(lambda: task_snapshot(task_id).get("speed") == speed))
                snapshot = task_snapshot(task_id)
                self.assertEqual(snapshot["stage"], stage)
                self.assertEqual(snapshot["progress"], expected)
                self.assertEqual(snapshot["items"][0]["progress"], expected)
                return snapshot["progress"]

            try:
                first = manager.submit(["https://example.invalid/video/first"])["task"]["id"]
                self.assertTrue(wait_until(lambda: first in channels))
                self.assertEqual([
                    progress(first, 45, 45), progress(first, 43, 45), progress(first, 47, 47),
                ], [45, 45, 47])
                self.assertEqual([
                    progress(first, 5, 5, "audio"), progress(first, 3, 5, "audio"),
                    progress(first, 8, 8, "audio"),
                ], [5, 5, 8])

                # 第一条尚未结束时启动第二条，验证不同任务没有共享高水位。
                second = manager.submit(["https://example.invalid/video/second"])["task"]["id"]
                self.assertTrue(wait_until(lambda: second in channels))
                self.assertEqual([
                    progress(second, 2, 2), progress(second, 1, 2), progress(second, 4, 4),
                ], [2, 2, 4])
                self.assertEqual(task_snapshot(first)["progress"], 8)
                for _, done in channels.values():
                    done.set()
                self.assertTrue(wait_until(lambda: all(
                    task["status"] == "completed" for task in manager.list_tasks()
                )))
                self.assertFalse(manager.has_active())
            finally:
                for _, done in channels.values():
                    done.set()
                manager.stop()


if __name__ == "__main__":
    unittest.main()
