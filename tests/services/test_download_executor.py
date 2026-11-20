import io
import json
import tempfile
import threading
import unittest
from queue import Queue
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from video_downloader.services.download_executor import DownloadExecutor
from video_downloader.services.download_manager import DownloadManager


from tests.helpers.download import (
    FakeAppState, create_executor, ImmediateThread, FailingThread, DirectThread,
    FakeProcess, CompletedProcess, PlaylistProcess,
)


class DownloadExecutorTests(unittest.TestCase):
    def test_cancelled_task_notifies_cleanup_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            callback = Mock()
            executor._on_finished = callback
            handle = executor._download_manager.begin("single")
            executor.stop_download()
            executor._finish(handle, None)
            executor._finish(handle, None)
            callback.assert_called_once_with(handle)

    def test_cancelled_preparation_notifies_parent_without_starting_download(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            executor._on_finished = Mock()
            handle = executor._download_manager.begin("single")
            executor.stop_download()
            run = Mock()
            executor._prepare_download(handle, {}, set(), run, ())
            run.assert_not_called()
            executor._on_finished.assert_called_once_with(handle)

    def test_task_single_password_retry_stays_in_same_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, callbacks = create_executor(Path(directory))
            executor._on_finished = Mock()
            executor._spawn = Mock(side_effect=[CompletedProcess(1), CompletedProcess(0)])
            done = threading.Event()
            done.set()
            first = Queue()
            first.put("ERROR: This video is protected by a password, use the --video-password option")
            executor._start_reader = Mock(side_effect=[(first, done), (Queue(), done)])
            executor._wait_for_password = Mock(return_value="task-password")
            handle = executor._download_manager.begin("single")
            url = "https://twitcasting.tv/user/movie/1"
            executor._run_single(handle, ["yt-dlp", url], url, "TwitCasting", False)
            self.assertEqual(executor._spawn.call_count, 2)
            self.assertIn("task-password", executor._spawn.call_args.args[0])
            self.assertEqual(callbacks["add_history"].call_count, 1)
            self.assertEqual(callbacks["add_history"].call_args.args[3], "success")
            executor._on_finished.assert_called_once_with(handle)

    def test_task_password_rejects_stale_request_instead_of_starting_new_download(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            executor._on_finished = Mock()
            executor._waiting_for_password = True
            executor._password_url = "url"
            executor._password_request_id = "current"
            self.assertIn("error", executor.submit_password("url", "password", request_id="stale"))
            self.assertFalse(executor._password_event.is_set())
            self.assertTrue(executor.submit_password("url", "", request_id="current")["ok"])

    def test_single_niconico_live_timeout_preserves_history_and_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, callbacks = create_executor(Path(directory))
            executor._app_state.config_snapshot = lambda: {"LIVE_DOWNLOAD_TIMEOUT": 1}
            executor._on_finished = Mock()
            handle = executor._download_manager.begin("single")
            with patch("video_downloader.services.download_executor.LiveRunner") as runner:
                runner.return_value.run.return_value = {
                    "status": "timeout", "title": "live", "output": "recording.mp4",
                    "report": "integrity-report.json", "conclusion": "complete", "stop_reason": "timeout"}
                executor._run_single(handle, ["yt-dlp", "url"], "url", "Niconico", True)
                self.assertEqual(runner.return_value.run.call_args.kwargs["config"]["LIVE_DOWNLOAD_TIMEOUT"], 1)
            self.assertEqual(callbacks["add_history"].call_args.args[3], "timeout")
            executor._on_finished.assert_called_once_with(handle)

    def test_start_withny_archive_returns_cancelled_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, callbacks = create_executor(Path(directory))
            result = executor.start_withny_archive()
            self.assertEqual(result, {"ok": True, "cancelled": True})
            callbacks["pick_withny_archive"].assert_called_once_with()

    def test_withny_archive_preserves_a_file_created_while_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ffmpeg.exe").touch()
            har = root / "capture.har"
            har.write_text(json.dumps({"log": {"entries": [
                {"request": {"url": "https://www.withny.fun/user/archives/7ee288a0-ed22-4930-bfd2-3a440517e784"}},
                {"request": {"url": "https://media.example/media.m3u8"},
                 "response": {"status": 200, "content": {"text": "#EXTM3U\n#EXTINF:5,\npart.ts"}}},
            ]}}), encoding="utf-8")
            output = root / "video.mp4"
            executor, callbacks = create_executor(root)
            callbacks["pick_withny_archive"].return_value = {
                "ok": True, "har_path": str(har), "output_path": str(output),
            }

            def finish_download(command, **_):
                Path(command[-1]).write_bytes(b"new download")
                output.write_bytes(b"another task's file")
                return CompletedProcess()

            done = threading.Event()
            done.set()
            with patch.object(executor, "_start_reader", return_value=(Queue(), done)), \
                    patch("video_downloader.services.download_executor.subprocess.Popen", side_effect=finish_download), \
                    patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                self.assertTrue(executor.start_withny_archive()["ok"])

            self.assertEqual(output.read_bytes(), b"another task's file")
            self.assertEqual(list(root.glob("*.mp4")), [output])
            self.assertEqual(executor._app_state.batch_stats["fail"], 1)
            self.assertFalse(executor._download_manager.snapshot()["running"])

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
            config.write_text("channels:\n  test-channel: {}\n", encoding="utf-8")
            executor, callbacks = create_executor(tool_dir)
            callbacks["pick_withny_live_config"].return_value = {"ok": True, "config_path": str(config)}
            finished = threading.Event()
            executor._on_finished = lambda _handle: finished.set()
            launched = []
            process = SimpleNamespace(
                stdout=io.BytesIO(b"ERROR authorization=Bearer capture-test-credential\n"),
                poll=lambda: 0, wait=lambda **_kwargs: 0, returncode=0,
            )

            def launch(command, *, cwd, env):
                launch_config = Path(command[command.index("--config") + 1])
                launched.append((launch_config, launch_config.read_text(encoding="utf-8")))
                return process

            with patch("video_downloader.live.process.spawn", side_effect=launch) as spawn:
                self.assertEqual(executor.start_withny_live(), {"ok": True})
                self.assertTrue(finished.wait(5), "Withny 工作线程未结束")
                spawn.assert_called_once()
            self.assertEqual(spawn.call_args.args[0][:3], [str(executable), "watch", "--config"])
            self.assertEqual(Path(spawn.call_args.kwargs["cwd"]), config_dir.resolve())
            launch_config, config_text = launched[0]
            self.assertNotEqual(launch_config, config)
            self.assertIn("test-channel", config_text)
            self.assertFalse(launch_config.exists())
            self.assertTrue(config.exists())
            events = (launch_config.parent / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"engine_error"', events)
            self.assertNotIn("capture-test-credential", events)
            self.assertNotIn("capture-test-credential", str(callbacks["log"].call_args_list))

    def test_finishing_withny_job_does_not_release_the_next_job_when_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "withny-dl-windows-amd64.exe").touch()
            config = root / "live.yaml"
            config.write_text("channels:\n  test-channel: {}\n", encoding="utf-8")
            manager = DownloadManager()
            executor, callbacks = create_executor(root, manager)
            callbacks["pick_withny_live_config"].return_value = {"ok": True, "config_path": str(config)}
            next_start = []

            def start_when_slot_released():
                if not manager.snapshot()["running"] and not next_start:
                    with patch("video_downloader.services.download_executor.threading.Thread", ImmediateThread):
                        next_start.append(executor.start_withny_live())

            callbacks["broadcast_download_state"].side_effect = start_when_slot_released
            with patch("video_downloader.services.download_executor.LiveRunner") as runner, \
                    patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                runner.return_value.run.return_value = {
                    "status": "fail", "title": "Withny", "output": "", "report": "integrity-report.json",
                }
                self.assertEqual(executor.start_withny_live(), {"ok": True})

            self.assertEqual(next_start, [{"ok": True}])
            self.assertTrue(executor.stop_download()["stopping"])
            self.assertTrue(manager.snapshot()["running"])

    def test_withny_live_releases_slot_after_finalization(self):
        for outcome in ("fail", "stopped"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "withny-dl-windows-amd64.exe").touch()
                config = root / "live.yaml"
                config.write_text("channels: {}\n", encoding="utf-8")
                manager = DownloadManager()
                executor, callbacks = create_executor(root, manager)
                callbacks["pick_withny_live_config"].return_value = {"ok": True, "config_path": str(config)}
                finished = Mock()
                executor._on_finished = finished

                def finalize(*_, **kwargs):
                    if outcome == "stopped":
                        executor.stop_download()
                        self.assertTrue(kwargs["cancel"].is_set())
                    return {"status": outcome, "title": "Withny", "output": "",
                            "report": "integrity-report.json"}

                with patch("video_downloader.services.download_executor.LiveRunner") as runner, \
                        patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                    runner.return_value.run.side_effect = finalize
                    self.assertTrue(executor.start_withny_live()["ok"])
                    self.assertEqual(callbacks["add_history"].call_args.args[3], outcome)
                    self.assertFalse(manager.snapshot()["running"])
                    finished.assert_called_once()
                    self.assertTrue(executor.start_withny_live()["ok"])

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
            executor._run_single = Mock()
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.start_download("https://youtube.com/live/abc")
            self.assertEqual(result, {"ok": True})
            callbacks["build_command"].assert_called_once_with(
                "https://youtube.com/live/abc",
                is_live=True,
                live_mode="catch_up",
                platform_override="YouTube",
                config_override=executor._app_state.config_snapshot(),
                bili_parts=None,
                include_subtitles=False,
            )

    def test_bilibili_live_defaults_to_live_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            executor._run_single = Mock()
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.start_download("https://live.bilibili.com/1")
            self.assertEqual(result, {"ok": True})
            kwargs = callbacks["build_command"].call_args.kwargs
            self.assertTrue(kwargs["is_live"])
            self.assertEqual(kwargs["live_mode"], "live_edge")

    def test_unsupported_catch_up_returns_error_before_start(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            result = executor.start_download(
                "https://live.bilibili.com/1",
                live_mode="catch_up",
            )
            self.assertIn("error", result)
            callbacks["build_command"].assert_not_called()

    def test_non_live_url_text_does_not_enable_live_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            executor._run_single = Mock()
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.start_download("https://youtube.com/watch?v=live-recording")
            self.assertEqual(result, {"ok": True})
            self.assertFalse(callbacks["build_command"].call_args.kwargs["is_live"])

    def test_single_download_forwards_one_time_custom_args(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            executor._run_single = Mock()
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.start_download(
                    "https://youtube.com/watch?v=abc",
                    custom_args="--sleep-requests 1",
                )
            self.assertEqual(result, {"ok": True})
            self.assertEqual(
                callbacks["build_command"].call_args.kwargs["custom_args"],
                "--sleep-requests 1",
            )

    def test_enabled_po_provider_starts_for_youtube_only(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            config = executor._app_state.config_snapshot()
            config["YOUTUBE_PO_TOKEN_ENABLED"] = 1
            config["DOWNLOAD_SUBTITLES"] = 1
            executor._app_state.config_snapshot = Mock(return_value=config)
            executor._run_single = Mock()
            callbacks["ensure_po_token_provider"].return_value = {
                "ok": True, "base_url": "http://[::1]:4416",
            }
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.start_download("https://youtube.com/watch?v=abc")
            self.assertEqual(result, {"ok": True})
            self.assertEqual(callbacks["ensure_po_token_provider"].call_count, 1)
            self.assertIsInstance(
                callbacks["ensure_po_token_provider"].call_args.kwargs["cancel_event"],
                threading.Event,
            )
            self.assertEqual(callbacks["build_command"].call_count, 2)
            self.assertTrue(all(call.kwargs["po_token_base_url"] == "http://[::1]:4416" for call in callbacks["build_command"].call_args_list))
            callbacks["ensure_po_token_provider"].reset_mock()
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                executor.start_download("https://www.twitch.tv/videos/123")
            callbacks["ensure_po_token_provider"].assert_not_called()

    def test_po_provider_start_error_is_logged_and_releases_youtube_task(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            config = executor._app_state.config_snapshot()
            config["YOUTUBE_PO_TOKEN_ENABLED"] = 1
            executor._app_state.config_snapshot = Mock(return_value=config)
            callbacks["ensure_po_token_provider"].return_value = {"error": "provider unavailable"}
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.start_download("https://youtube.com/watch?v=abc")
            self.assertEqual(result, {"ok": True})
            self.assertFalse(executor._download_manager.snapshot()["running"])
            callbacks["build_command"].assert_not_called()
            callbacks["log"].assert_called_with("[准备失败] provider unavailable", "error")
            self.assertEqual(executor._app_state.batch_stats["fail"], 1)

    def test_provider_preparation_returns_promptly_and_can_be_stopped_for_single_and_batch(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as directory:
                tool_dir = Path(directory)
                for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
                    (tool_dir / name).touch()
                executor, callbacks = create_executor(tool_dir)
                config = dict(executor._app_state.config_snapshot(), YOUTUBE_PO_TOKEN_ENABLED=1)
                executor._app_state.config_snapshot = Mock(return_value=config)
                entered = threading.Event()
                release = threading.Event()
                workers = []
                real_thread = threading.Thread

                def capture_worker(*args, **kwargs):
                    worker = real_thread(*args, **kwargs)
                    workers.append(worker)
                    return worker

                def slow_provider(cancel_event):
                    entered.set()
                    release.wait(3)
                    return {"ok": True, "base_url": "http://[::1]:4416"}

                callbacks["ensure_po_token_provider"].side_effect = slow_provider
                executor._run_single = Mock()
                executor._run_batch = Mock()
                start = (lambda: executor.batch_download(["https://youtube.com/watch?v=abc"])) if batch else (
                    lambda: executor.start_download("https://youtube.com/watch?v=abc")
                )
                with patch("video_downloader.services.download_executor.threading.Thread", side_effect=capture_worker):
                    try:
                        self.assertTrue(start()["ok"])
                        self.assertTrue(entered.wait(2))
                        self.assertTrue(executor._download_manager.snapshot()["running"])
                        self.assertFalse(release.is_set())
                        self.assertEqual(start(), {"error": "已有下载任务在运行"})
                        self.assertEqual(callbacks["ensure_po_token_provider"].call_count, 1)
                        self.assertTrue(executor.stop_download()["stopped"])
                        self.assertTrue(callbacks["ensure_po_token_provider"].call_args.kwargs["cancel_event"].is_set())
                        # A new task can finish before the old provider callback returns.
                        self.assertTrue(executor.start_download("https://www.twitch.tv/videos/123")["ok"])
                        workers[-1].join(timeout=2)
                        self.assertFalse(workers[-1].is_alive())
                        stats = dict(executor._app_state.batch_stats)
                    finally:
                        release.set()
                        for worker in workers:
                            worker.join(timeout=3)
                self.assertTrue(all(not worker.is_alive() for worker in workers))
                self.assertEqual(executor._run_single.call_count, 1)
                executor._run_batch.assert_not_called()
                self.assertEqual(executor._app_state.batch_stats, stats)
                self.assertFalse(executor._download_manager.snapshot()["running"])

    def test_provider_exception_is_visible_and_releases_batch_task(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            config = dict(executor._app_state.config_snapshot(), YOUTUBE_PO_TOKEN_ENABLED=1)
            executor._app_state.config_snapshot = Mock(return_value=config)
            callbacks["ensure_po_token_provider"].side_effect = RuntimeError("cold start failed")
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                self.assertTrue(executor.batch_download(["https://youtube.com/watch?v=abc"])["ok"])
            callbacks["log"].assert_called_with("[准备失败] cold start failed", "error")
            callbacks["build_command"].assert_not_called()
            self.assertFalse(executor._download_manager.snapshot()["running"])
            self.assertEqual(executor._app_state.batch_stats["fail"], 1)

    def test_provider_url_is_forwarded_to_video_and_subtitles_in_mixed_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            config = dict(executor._app_state.config_snapshot(), YOUTUBE_PO_TOKEN_ENABLED=1, DOWNLOAD_SUBTITLES=1)
            executor._app_state.config_snapshot = Mock(return_value=config)
            callbacks["ensure_po_token_provider"].return_value = {"ok": True, "base_url": "http://[::1]:4416"}
            executor._spawn = Mock(side_effect=[CompletedProcess(), CompletedProcess()])
            done = threading.Event()
            done.set()
            executor._start_reader = Mock(return_value=(Queue(), done))
            executor._run_subtitle_sidecar = Mock(return_value=True)
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                executor.batch_download(["https://youtube.com/watch?v=abc", "https://www.twitch.tv/videos/123"])
            self.assertEqual(callbacks["ensure_po_token_provider"].call_count, 1)
            youtube_calls = [call for call in callbacks["build_command"].call_args_list if call.kwargs["platform_override"] == "YouTube"]
            twitch_calls = [call for call in callbacks["build_command"].call_args_list if call.kwargs["platform_override"] == "Twitch"]
            self.assertEqual(len(youtube_calls), 2)
            self.assertEqual(len(twitch_calls), 2)
            self.assertTrue(all(call.kwargs["po_token_base_url"] == "http://[::1]:4416" for call in youtube_calls))
            self.assertTrue(all("po_token_base_url" not in call.kwargs for call in twitch_calls))
            self.assertEqual(executor._app_state.batch_stats["ok"], 2)

    def test_twitcasting_retry_keeps_subtitle_command(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            plugin = (
                tool_dir
                / "yt-dlp-plugins/video_downloader/yt_dlp_plugins/postprocessor/"
                / "twitcasting_parallel.py"
            )
            plugin.parent.mkdir(parents=True)
            plugin.touch()
            executor, _ = create_executor(tool_dir)
            handle = executor._download_manager.begin("single")
            executor._app_state.batch_stats.update({"ok": 0, "fail": 0, "total": 1, "current": 1})
            process = Mock(returncode=1)
            process.stdout = None
            process.poll.return_value = 1
            executor._spawn = Mock(return_value=process)
            executor._start_reader = Mock(return_value=(
                Queue(), threading.Event()
            ))
            executor._start_reader.return_value[0].put(
                "ERROR: Initialization fragment found after media fragments"
            )
            executor._start_reader.return_value[1].set()
            executor._close_process = Mock()
            executor._finish = Mock()
            subtitle_cmd = ["yt-dlp", "--skip-download", "url"]
            with patch.object(executor, "_run_single") as retry:
                DownloadExecutor._run_single(
                    executor, handle, ["yt-dlp", "url"], "url", "TwitCasting",
                    False, "0", "mp3", False, subtitle_cmd,
                )
            self.assertIs(retry.call_args.args[8], subtitle_cmd)
            retry_cmd = retry.call_args.args[1]
            self.assertEqual(
                retry_cmd[retry_cmd.index("--downloader") + 1],
                "m3u8:ffmpeg",
            )
            self.assertIn("--enable-file-urls", retry_cmd)
            self.assertIn(
                "TwitCastingParallelHls:when=before_dl",
                retry_cmd,
            )

    def test_twitcasting_m3u8_400_retries_direct_before_firefox(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            handle = executor._download_manager.begin("single")
            executor._app_state.batch_stats.update({"ok": 0, "fail": 0, "total": 1, "current": 1})
            process = Mock(returncode=1)
            process.stdout = None
            process.poll.return_value = 1
            executor._spawn = Mock(return_value=process)
            lines = Queue()
            lines.put(
                "ERROR: [TwitCasting] 1: Failed to download m3u8 information: "
                "HTTP Error 400: Bad Request"
            )
            done = threading.Event()
            done.set()
            executor._start_reader = Mock(return_value=(lines, done))
            executor._close_process = Mock()
            executor._finish = Mock()
            command = [
                "yt-dlp", "--proxy", "http://127.0.0.1:7897",
                "--cookies", "cookies.txt", "url",
            ]
            subtitle_command = [
                "yt-dlp", "--skip-download", "--proxy", "http://127.0.0.1:7897",
                "--cookies", "cookies.txt", "url",
            ]
            with patch.object(executor, "_run_single") as retry:
                DownloadExecutor._run_single(
                    executor, handle, command, "url", "TwitCasting", False,
                    subtitle_cmd=subtitle_command,
                )
            retried = retry.call_args.args[1]
            retried_subtitles = retry.call_args.args[8]
            self.assertEqual(retried[retried.index("--proxy") + 1], "")
            self.assertEqual(
                retried_subtitles[retried_subtitles.index("--proxy") + 1], "",
            )
            self.assertIn("--cookies", retried)
            self.assertIn("--cookies", retried_subtitles)
            self.assertTrue(retry.call_args.args[9])
            self.assertFalse(retry.call_args.args[10])

    def test_twitcasting_m3u8_400_retries_file_cookie_with_firefox(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            handle = executor._download_manager.begin("single")
            executor._app_state.batch_stats.update({"ok": 0, "fail": 0, "total": 1, "current": 1})
            process = Mock(returncode=1)
            process.stdout = None
            process.poll.return_value = 1
            executor._spawn = Mock(return_value=process)
            lines = Queue()
            lines.put(
                "ERROR: [TwitCasting] 1: Failed to download m3u8 information: "
                "HTTP Error 400: Bad Request"
            )
            done = threading.Event()
            done.set()
            executor._start_reader = Mock(return_value=(lines, done))
            executor._close_process = Mock()
            executor._finish = Mock()
            command = ["yt-dlp", "--proxy", "", "--cookies", "cookies.txt", "url"]
            subtitle_command = [
                "yt-dlp", "--skip-download", "--proxy", "",
                "--cookies", "cookies.txt", "url",
            ]
            with patch.object(executor, "_run_single") as retry:
                DownloadExecutor._run_single(
                    executor, handle, command, "url", "TwitCasting", False,
                    subtitle_cmd=subtitle_command,
                )
            retried = retry.call_args.args[1]
            retried_subtitles = retry.call_args.args[8]
            self.assertNotIn("--cookies", retried)
            self.assertNotIn("--cookies", retried_subtitles)
            self.assertEqual(
                retried[retried.index("--cookies-from-browser") + 1],
                "firefox",
            )
            self.assertEqual(
                retried_subtitles[retried_subtitles.index("--cookies-from-browser") + 1],
                "firefox",
            )
            self.assertFalse(retry.call_args.args[9])
            self.assertTrue(retry.call_args.args[10])

    def test_explicit_direct_connection_removes_proxy_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, _ = create_executor(Path(directory))
            process = CompletedProcess()
            with (
                patch.dict(
                    "video_downloader.services.download_executor.os.environ",
                    {
                        "HTTP_PROXY": "http://127.0.0.1:7897",
                        "https_proxy": "http://127.0.0.1:7897",
                        "ALL_PROXY": "socks5://127.0.0.1:7897",
                    },
                    clear=False,
                ),
                patch(
                    "video_downloader.services.download_executor.subprocess.Popen",
                    return_value=process,
                ) as popen,
            ):
                executor._spawn(["yt-dlp", "--proxy", "", "url"])
            child_env = popen.call_args.kwargs["env"]
            self.assertFalse(any(
                key.lower() in {"http_proxy", "https_proxy", "all_proxy"}
                for key in child_env
            ))

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
            self.assertEqual(thread.call_args.kwargs["args"][4][0], ["https://youtube.com/live/abc"])

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
            with patch("video_downloader.services.download_executor.LiveRunner") as runner:
                runner.return_value.run.return_value = {
                    "status": "success", "title": "live", "output": "recording.mp4", "report": "report.json"}
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

    def test_batch_download_forwards_one_time_custom_args(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            executor._spawn = Mock(return_value=CompletedProcess())
            done = threading.Event()
            done.set()
            executor._start_reader = Mock(return_value=(Queue(), done))
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.batch_download(
                    ["https://youtube.com/watch?v=abc"],
                    custom_args="--retries 20",
                )
            self.assertEqual(result, {"ok": True, "total": 1})
            self.assertEqual(
                callbacks["build_command"].call_args.kwargs["custom_args"],
                "--retries 20",
            )

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

    def test_batch_twitcasting_400_recovery_is_bounded_and_keeps_direct_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            for name in ["yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"]:
                (tool_dir / name).touch()
            executor, callbacks = create_executor(tool_dir)
            callbacks["build_command"].return_value = [
                "yt-dlp", "--proxy", "http://127.0.0.1:7897",
                "--cookies", "cookies.txt", "url",
            ]
            executor._spawn = Mock(side_effect=[
                CompletedProcess(1),
                CompletedProcess(1),
                CompletedProcess(0),
            ])
            done = threading.Event()
            done.set()

            def failed_reader():
                lines = Queue()
                lines.put(
                    "ERROR: [TwitCasting] 1: Failed to download m3u8 information: "
                    "HTTP Error 400: Bad Request"
                )
                return lines, done

            executor._start_reader = Mock(side_effect=[
                failed_reader(),
                failed_reader(),
                (Queue(), done),
            ])

            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.batch_download(["https://twitcasting.tv/user/movie/1"])

            self.assertEqual(result, {"ok": True, "total": 1})
            commands = [call.args[0] for call in executor._spawn.call_args_list]
            self.assertEqual(commands[1][commands[1].index("--proxy") + 1], "")
            self.assertEqual(commands[2][commands[2].index("--proxy") + 1], "")
            self.assertNotIn("--cookies", commands[2])
            self.assertEqual(
                commands[2][commands[2].index("--cookies-from-browser") + 1],
                "firefox",
            )
            self.assertEqual(executor._app_state.batch_stats["ok"], 1)
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

            def finish_export(command, **_):
                Path(command[-1]).write_bytes(b"exported audio")
                return process

            with patch("video_downloader.services.download_executor.subprocess.Popen", side_effect=finish_export):
                self.assertTrue(executor._extract_audio_from_video(video_path, "mp3", handle=handle))

            self.assertEqual((tool_dir / "video.mp3").read_bytes(), b"exported audio")
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
