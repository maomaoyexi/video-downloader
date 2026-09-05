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
        "pick_withny_archive": Mock(return_value={"ok": True, "cancelled": True}),
        "pick_withny_live_config": Mock(return_value={"ok": True, "cancelled": True}),
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
    def __init__(self, returncode=0):
        self.returncode = returncode
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
    def test_start_withny_archive_returns_cancelled_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, callbacks = create_executor(Path(directory))
            result = executor.start_withny_archive()
            self.assertEqual(result, {"ok": True, "cancelled": True})
            callbacks["pick_withny_archive"].assert_called_once_with()

    def test_start_withny_live_returns_cancelled_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, callbacks = create_executor(Path(directory))
            result = executor.start_withny_live()
            self.assertEqual(result, {"ok": True, "cancelled": True})
            callbacks["pick_withny_live_config"].assert_called_once_with()

    def test_start_withny_live_requires_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            config = tool_dir / "config.yaml"
            config.touch()
            executor, callbacks = create_executor(tool_dir)
            callbacks["pick_withny_live_config"].return_value = {"ok": True, "config_path": str(config)}
            result = executor.start_withny_live()
            self.assertEqual(result, {"error": "缺少依赖: withny-dl-windows-amd64.exe"})

    def test_start_withny_live_builds_argument_list_and_config_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            executable = tool_dir / "withny-dl-windows-amd64.exe"
            executable.touch()
            config_dir = tool_dir / "config"
            config_dir.mkdir()
            config = config_dir / "live.yaml"
            config.touch()
            executor, callbacks = create_executor(tool_dir)
            callbacks["pick_withny_live_config"].return_value = {"ok": True, "config_path": str(config)}
            captured = {}

            def capture_thread(target, args=(), daemon=None):
                captured["args"] = args
                return ImmediateThread(target, args, daemon)

            with patch("video_downloader.services.download_executor.threading.Thread", side_effect=capture_thread):
                result = executor.start_withny_live()
            self.assertEqual(result, {"ok": True})
            args = captured["args"]
            self.assertEqual(args[1][:3], [str(executable), "watch", "--config"])
            self.assertEqual(args[1][3], str(config.resolve()))
            self.assertEqual(args[2], config_dir.resolve())

    def test_withny_live_log_sanitizer_hides_credentials(self):
        line = 'authorization=Bearer abc token=secret "password":"hidden" normal=value'
        cleaned = DownloadExecutor._sanitize_withny_live_line(line)
        self.assertNotIn("abc", cleaned)
        self.assertNotIn("secret", cleaned)
        self.assertNotIn("hidden", cleaned)
        self.assertIn("normal=value", cleaned)

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

    def test_batch_reuses_last_twitcasting_password_and_reprompts_when_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            executor._spawn = Mock(side_effect=[
                CompletedProcess(1),  # 第一个链接：尚未提供密码
                CompletedProcess(0),  # 第一个链接：新密码正确
                CompletedProcess(1),  # 第二个链接：自动复用后密码不正确
                CompletedProcess(0),  # 第二个链接：再次输入的新密码正确
            ])
            done = threading.Event()
            done.set()

            def reader_with(line=""):
                lines = Queue()
                if line:
                    lines.put(line)
                return lines, done

            executor._start_reader = Mock(side_effect=[
                reader_with("ERROR: This video is protected by a password, use the --video-password option"),
                reader_with(),
                reader_with("ERROR: Requested format is not available"),
                reader_with(),
            ])
            executor._wait_for_password = Mock(side_effect=["first-password", "second-password"])

            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.batch_download([
                    "https://twitcasting.tv/user/movie/1",
                    "https://twitcasting.tv/user/movie/2",
                ])

            self.assertEqual(result, {"ok": True, "total": 2})
            command_configs = [call.kwargs["config_override"] for call in callbacks["build_command"].call_args_list]
            self.assertNotIn("TC_PASSWORD", command_configs[0])
            self.assertEqual(command_configs[1]["TC_PASSWORD"], "first-password")
            self.assertEqual(command_configs[2]["TC_PASSWORD"], "first-password")
            self.assertEqual(command_configs[3]["TC_PASSWORD"], "second-password")
            self.assertEqual(executor._wait_for_password.call_count, 2)
            self.assertEqual(
                [call.kwargs["reason"] for call in executor._wait_for_password.call_args_list],
                ["missing", "retry"],
            )
            self.assertEqual(executor._app_state.batch_stats["ok"], 2)
            self.assertEqual(executor._app_state.batch_stats["fail"], 0)

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
            self.assertEqual(result, {"ok": True, "stopping": False, "stopped": True})
            self.assertTrue(handle.cancel_event.is_set())
            executor.kill_process_tree.assert_called_once_with(process)
            self.assertFalse(manager.snapshot()["running"])
            callbacks["broadcast_download_state"].assert_called_once_with()

    def test_media_stage_marker_distinguishes_audio_and_video(self):
        self.assertEqual(
            DownloadExecutor._media_stage_from_line(
                "[download] 25.0% __VD_STAGE__avc1.640028|none"
            ),
            "video",
        )
        self.assertEqual(
            DownloadExecutor._media_stage_from_line(
                "[download] 25.0% __VD_STAGE__none|mp4a.40.2"
            ),
            "audio",
        )

    def test_progress_metrics_support_template_speed_and_long_eta(self):
        speed, eta = DownloadExecutor._progress_metrics_from_line(
            "[download] 12.0% of 1.0GiB at 12.5MiB/s ETA 01:02:03 "
            "__VD_STAGE__avc1|none"
        )
        self.assertEqual(speed, "12.5MiB/s")
        self.assertEqual(eta, "01:02:03")

    def test_progress_metrics_clears_unknown_speed_with_unit(self):
        speed, eta = DownloadExecutor._progress_metrics_from_line(
            "[download]   0.0% of    6.00MiB at  Unknown B/s ETA Unknown "
            "__VD_STAGE__NA|NA"
        )
        self.assertEqual(speed, "")
        self.assertEqual(eta, "")

    def test_current_ytdlp_command_is_remembered_and_masks_password(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            self.assertIn("没有可复制", executor.get_current_ytdlp_command()["error"])
            executor._remember_ytdlp_command([
                "yt-dlp.exe", "--video-password", "secret", "https://example.com/video",
            ])
            result = executor.get_current_ytdlp_command()
            self.assertTrue(result["ok"])
            self.assertTrue(result["redacted"])
            self.assertIn("***", result["command"])
            self.assertNotIn("secret", result["command"])
            self.assertIn("https://example.com/video", result["command"])

    def test_batch_progress_reports_current_item_instead_of_whole_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            executor._spawn = Mock(side_effect=[CompletedProcess(), CompletedProcess()])
            done = threading.Event()
            done.set()

            def progress_reader(stage):
                lines = Queue()
                lines.put(f"[download] 50.0% __VD_STAGE__{stage}")
                return lines, done

            executor._start_reader = Mock(side_effect=[
                progress_reader("avc1|none"),
                progress_reader("none|mp4a"),
            ])
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                executor.batch_download(["one", "two"])

            progress_calls = [
                call for call in callbacks["update_progress"].call_args_list
                if call.args and call.args[0] == 0.5
            ]
            self.assertEqual(len(progress_calls), 2)
            self.assertEqual(progress_calls[0].kwargs["stage"], "video")
            self.assertEqual(progress_calls[1].kwargs["stage"], "audio")

    def test_audio_extraction_is_managed_and_reports_audio_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            video_path = str(tool_dir / "video.mp4")
            manager = DownloadManager()
            handle = manager.begin("single")
            executor, callbacks = create_executor(tool_dir, manager)
            process = CompletedProcess()
            lines = Queue()
            lines.put("Duration: 00:00:10.00")
            lines.put("out_time_us=5000000")
            done = threading.Event()
            done.set()
            executor._start_reader = Mock(return_value=(lines, done))

            with patch("video_downloader.services.download_executor.subprocess.Popen", return_value=process), \
                    patch("video_downloader.services.download_executor.os.path.isfile", side_effect=[False, True]):
                self.assertTrue(executor._extract_audio_from_video(video_path, "mp3", handle=handle))

            self.assertIsNone(manager.snapshot()["process"])
            audio_updates = [
                call for call in callbacks["update_progress"].call_args_list
                if call.kwargs.get("stage") == "audio"
            ]
            self.assertTrue(audio_updates)
            self.assertTrue(any(call.args[0] == 0.5 for call in audio_updates))

    def test_stop_wakes_password_wait_and_releases_task(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DownloadManager()
            executor, _ = create_executor(Path(directory), manager)
            manager.begin("batch")
            executor._waiting_for_password = True
            executor._password_event.clear()

            result = executor.stop_download()

            self.assertTrue(result["stopped"])
            self.assertTrue(executor._password_event.is_set())
            self.assertFalse(manager.snapshot()["running"])

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
