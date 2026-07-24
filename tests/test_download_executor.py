import tempfile
import threading
import unittest
from queue import Queue
from pathlib import Path
from unittest.mock import Mock, patch

from video_downloader.services.download_executor import DownloadExecutor
from video_downloader.services.download_manager import DownloadManager


class FakeAppState:
    def __init__(self):
        self.download_thread_context = threading.local()
        self.sse_clients = []
        self.batch_stats = {}

    def config_snapshot(self):
        return {
            "PLATFORM": "YouTube",
            "USE_COOKIES": 0,
            "COOKIE_MODE": 1,
            "BROWSER_NAME": "chrome",
            "BROWSER_PROFILE": "Default",
            "PROXY_ENABLED": 0,
            "PROXY_TYPE": "http",
            "PROXY_ADDR": "127.0.0.1",
            "PROXY_PORT": "7890",
        }

    def publish(self, event):
        for client in self.sse_clients:
            client.put_nowait(event)

    def has_sse_clients(self):
        return bool(self.sse_clients)


def create_executor(tool_dir, manager=None):
    callbacks = {
        "build_command": Mock(return_value=["yt-dlp"]),
        "log": Mock(),
        "update_progress": Mock(),
        "broadcast_download_state": Mock(),
        "add_history": Mock(),
        "cancel_idle_timer": Mock(),
        "start_idle_timer": Mock(),
        "emit_event": Mock(),
    }
    executor = DownloadExecutor(
        tool_dir=tool_dir,
        exe_suffix=".exe",
        app_state=FakeAppState(),
        download_manager=manager or DownloadManager(),
        **callbacks,
    )
    return executor, callbacks


class ImmediateThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args

    def start(self):
        pass


class FailingThread(ImmediateThread):
    def start(self):
        raise RuntimeError("thread unavailable")


class DirectThread(ImmediateThread):
    def start(self):
        self.target(*self.args)


class FakeProcess:
    def __init__(self, running=True):
        self.pid = 42
        self.running = running
        self.stdout = Mock()
        self.kill = Mock(side_effect=self._kill)

    def _kill(self):
        self.running = False

    def poll(self):
        return None if self.running else 0

    def wait(self, timeout=None):
        if self.running:
            raise TimeoutError()
        return 0


class CompletedProcess:
    def __init__(self):
        self.returncode = 0
        self.stdout = Mock()

    def poll(self):
        return self.returncode


class PlaylistProcess:
    def __init__(self, stdout="", stderr="", returncode=0, timeout=False):
        self.stdout_output = stdout
        self.stderr_output = stderr
        self.returncode = returncode
        self.timeout = timeout

    def communicate(self, timeout=None):
        if self.timeout:
            raise __import__("subprocess").TimeoutExpired("yt-dlp", timeout)
        return self.stdout_output, self.stderr_output


class DownloadExecutorTests(unittest.TestCase):
    def test_fetch_bili_playlist_uses_bounded_communicate(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            process = PlaylistProcess(
                stdout='{"playlist_index": 1, "title": "第一集", "id": "BV1", "duration": 12}\n'
            )
            with patch("video_downloader.services.download_executor.subprocess.Popen", return_value=process):
                result = executor.fetch_bili_playlist("https://www.bilibili.com/video/BV1")
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["parts"][0]["title"], "第一集")

    def test_fetch_bili_playlist_timeout_kills_process(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            process = PlaylistProcess(timeout=True)
            executor.kill_process_tree = Mock(side_effect=lambda proc: setattr(proc, "timeout", False))
            with patch("video_downloader.services.download_executor.subprocess.Popen", return_value=process):
                result = executor.fetch_bili_playlist("https://www.bilibili.com/video/BV1")
            self.assertIn("超时", result["error"])
            executor.kill_process_tree.assert_called_once_with(process)

    def test_fetch_bili_playlist_empty_title_uses_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            process = PlaylistProcess(stdout='{"playlist_index": 1, "title": null, "id": "BV1"}\n')
            with patch("video_downloader.services.download_executor.subprocess.Popen", return_value=process):
                result = executor.fetch_bili_playlist("https://www.bilibili.com/video/BV1")
            self.assertEqual(result["parts"][0]["title"], "P1")

    def test_start_download_rejects_missing_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, callbacks = create_executor(Path(directory))
            result = executor.start_download("https://youtube.com/watch?v=abc")
            self.assertEqual(result, {"error": "缺少依赖: yt-dlp.exe"})
            callbacks["build_command"].assert_not_called()

    def test_start_download_starts_managed_single_task(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            manager = DownloadManager()
            executor, callbacks = create_executor(tool_dir, manager)
            with patch("video_downloader.services.download_executor.threading.Thread", ImmediateThread):
                result = executor.start_download("https://youtube.com/watch?v=abc")
            self.assertEqual(result, {"ok": True})
            self.assertEqual(manager.snapshot()["kind"], "single")
            callbacks["cancel_idle_timer"].assert_called_once_with()
            callbacks["broadcast_download_state"].assert_called_once_with()

    def test_youtube_live_flag_is_passed_to_command_builder(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            with patch("video_downloader.services.download_executor.threading.Thread", ImmediateThread):
                result = executor.start_download("https://youtube.com/live/abc")
            self.assertEqual(result, {"ok": True})
            callbacks["build_command"].assert_called_once_with(
                "https://youtube.com/live/abc",
                is_live=True,
                platform_override="YouTube",
                config_override=executor._app_state.config_snapshot(),
                bili_parts=None,
            )

    def test_non_live_url_text_does_not_enable_live_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            with patch("video_downloader.services.download_executor.threading.Thread", ImmediateThread):
                result = executor.start_download("https://youtube.com/watch?v=live-recording")
            self.assertEqual(result, {"ok": True})
            self.assertFalse(callbacks["build_command"].call_args.kwargs["is_live"])

    def test_single_thread_start_failure_rolls_back_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            manager = DownloadManager()
            executor, callbacks = create_executor(tool_dir, manager)
            with patch("video_downloader.services.download_executor.threading.Thread", FailingThread):
                result = executor.start_download("https://youtube.com/watch?v=abc")
            self.assertEqual(result, {"error": "下载线程启动失败: thread unavailable"})
            self.assertFalse(manager.snapshot()["running"])
            callbacks["broadcast_download_state"].assert_called_with()
            callbacks["start_idle_timer"].assert_called_once_with()

    def test_batch_download_initializes_shared_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            with patch("video_downloader.services.download_executor.threading.Thread", ImmediateThread):
                result = executor.batch_download(["one", "two"])
            self.assertEqual(result, {"ok": True, "total": 2})
            self.assertEqual(executor._app_state.batch_stats, {"ok": 0, "fail": 0, "total": 2, "current": 0})
            callbacks["cancel_idle_timer"].assert_called_once_with()

    def test_batch_download_cleans_urls_before_initializing_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, _ = create_executor(tool_dir)
            with patch("video_downloader.services.download_executor.threading.Thread") as thread:
                result = executor.batch_download(["  `https://youtube.com/live/abc`  ", "", "  "])
            self.assertEqual(result, {"ok": True, "total": 1})
            self.assertEqual(executor._app_state.batch_stats, {"ok": 0, "fail": 0, "total": 1, "current": 0})
            self.assertEqual(thread.call_args.kwargs["args"][1], ["https://youtube.com/live/abc"])

    def test_batch_download_passes_live_flag_and_uses_filtered_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            executor._spawn = Mock(side_effect=[CompletedProcess(), CompletedProcess()])
            done = threading.Event()
            done.set()
            executor._start_reader = Mock(side_effect=[(Queue(), done), (Queue(), done)])
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.batch_download([
                    " https://youtube.com/live/abc ",
                    " ",
                    "https://www.twitch.tv/videos/123",
                ])
            self.assertEqual(result, {"ok": True, "total": 2})
            self.assertEqual(callbacks["build_command"].call_args_list[0].kwargs["is_live"], True)
            self.assertEqual(callbacks["build_command"].call_args_list[1].kwargs["is_live"], False)
            self.assertEqual(executor._app_state.batch_stats, {"ok": 2, "fail": 0, "total": 2, "current": 2})
            statuses = [call.args[1] for call in callbacks["update_progress"].call_args_list]
            self.assertIn("批量下载 2/2", statuses)

    def test_batch_download_rejects_empty_cleaned_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            result = executor.batch_download(["", "  ", "``"])
            self.assertEqual(result, {"error": "没有有效的视频链接"})
            callbacks["cancel_idle_timer"].assert_not_called()

    def test_batch_thread_start_failure_rolls_back_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            manager = DownloadManager()
            executor, callbacks = create_executor(tool_dir, manager)
            with patch("video_downloader.services.download_executor.threading.Thread", FailingThread):
                result = executor.batch_download(["one"])
            self.assertEqual(result, {"error": "下载线程启动失败: thread unavailable"})
            self.assertFalse(manager.snapshot()["running"])
            callbacks["start_idle_timer"].assert_called_once_with()

    def test_stop_download_terminates_published_process(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DownloadManager()
            executor, callbacks = create_executor(Path(directory), manager)
            handle = manager.begin("single")
            process = FakeProcess()
            manager.publish_process(handle, process)
            executor.kill_process_tree = Mock()
            result = executor.stop_download()
            self.assertEqual(result, {"ok": True, "stopping": True})
            self.assertTrue(handle.cancel_event.is_set())
            executor.kill_process_tree.assert_called_once_with(process)
            callbacks["broadcast_download_state"].assert_called_once_with()

    def test_stop_download_is_idempotent_when_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, callbacks = create_executor(Path(directory))
            self.assertEqual(executor.stop_download(), {"ok": True, "stopping": False})
            callbacks["broadcast_download_state"].assert_not_called()

    def test_kill_process_tree_falls_back_to_process_kill(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            process = FakeProcess()
            with patch("video_downloader.services.download_executor.os.name", "posix"):
                executor.kill_process_tree(process)
            process.kill.assert_called_once_with()
            process.stdout.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
