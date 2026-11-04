"""下载入口在精简旧直播分支后仍保留点播进度与直播收尾。"""
import tempfile
import threading
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import Mock, patch

from tests.helpers.download import CompletedProcess, DirectThread, create_executor


class DownloadExecutionPathTests(unittest.TestCase):
    def make_executor(self, root):
        for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
            (root / name).touch()
        return create_executor(root)

    @staticmethod
    def output(*lines):
        queue = Queue()
        for line in lines:
            queue.put(line)
        done = threading.Event()
        done.set()
        return queue, done

    def test_single_vod_keeps_ffmpeg_progress_without_a_percentage(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, callbacks = self.make_executor(Path(directory))
            executor._spawn = Mock(return_value=CompletedProcess())
            executor._start_reader = Mock(return_value=self.output(
                "size= 4096kB time=00:00:10.00 bitrate=3355.4kbits/s speed=1.25x",
                "frame= 300 fps=30 size=N/A time=00:00:10.00 bitrate=N/A",
            ))
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.start_download("https://www.youtube.com/watch?v=fixture")

            self.assertEqual(result, {"ok": True})
            progress = [call for call in callbacks["update_progress"].call_args_list if call.args[0] == -1]
            self.assertEqual(len(progress), 2)
            self.assertIn("FFmpeg 下载中", progress[0].args[1])
            self.assertIn("4096kB", progress[0].args[1])
            self.assertEqual(progress[0].kwargs["speed"], "1.25x")
            self.assertEqual(progress[1].kwargs["speed"], "30 fps")
            self.assertEqual(callbacks["add_history"].call_args.args[3], "success")
            self.assertFalse(executor._download_manager.snapshot()["running"])

    def test_batch_vod_keeps_ffmpeg_progress_after_hls_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, callbacks = self.make_executor(Path(directory))
            executor._spawn = Mock(side_effect=[CompletedProcess(1), CompletedProcess()])
            executor._start_reader = Mock(side_effect=[
                self.output("ERROR: Initialization fragment found after media fragments"),
                self.output("size= 4096kB time=00:00:10.00 bitrate=3355.4kbits/s speed=1.25x"),
            ])
            with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                result = executor.batch_download(["https://twitcasting.tv/fixture/movie/1"])

            self.assertEqual(result, {"ok": True, "total": 1})
            self.assertEqual(executor._spawn.call_count, 2)
            self.assertTrue(callbacks["build_command"].call_args.kwargs["use_ffmpeg_for_hls"])
            progress = [call for call in callbacks["update_progress"].call_args_list if call.args[0] == -1]
            self.assertEqual(len(progress), 1)
            self.assertIn("FFmpeg 下载中", progress[0].args[1])
            self.assertEqual(progress[0].kwargs["speed"], "1.25x")
            self.assertEqual(executor._app_state.batch_stats["ok"], 1)
            self.assertEqual(executor._app_state.batch_stats["fail"], 0)
            self.assertFalse(executor._download_manager.snapshot()["running"])

    def test_live_timeout_uses_the_runner_and_releases_single_and_batch_tasks(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as directory:
                executor, callbacks = self.make_executor(Path(directory))
                config = dict(executor._app_state.config_snapshot(), LIVE_DOWNLOAD_TIMEOUT=1)
                executor._app_state.config_snapshot = lambda: dict(config)
                executor._spawn = Mock()
                with patch("video_downloader.services.download_executor.LiveRunner") as runner, \
                        patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                    runner.return_value.run.return_value = {
                        "status": "timeout", "title": "fixture", "output": "recording.mp4",
                        "report": "integrity-report.json", "conclusion": "complete",
                    }
                    url = "https://live.nicovideo.jp/watch/lv123456"
                    result = executor.batch_download([url]) if batch else executor.start_download(url)

                self.assertTrue(result["ok"])
                runner.return_value.run.assert_called_once()
                self.assertEqual(runner.return_value.run.call_args.kwargs["config"]["LIVE_DOWNLOAD_TIMEOUT"], 1)
                executor._spawn.assert_not_called()
                self.assertEqual(callbacks["add_history"].call_args.args[3], "timeout")
                self.assertFalse(executor._download_manager.snapshot()["running"])

    def test_cancelled_live_runner_does_not_spawn_following_batch_vod(self):
        with tempfile.TemporaryDirectory() as directory:
            executor, callbacks = self.make_executor(Path(directory))
            executor._spawn = Mock()

            def stopped(*args, cancel, **kwargs):
                cancel.set()
                return {"status": "stopped", "title": "fixture", "output": "recording.mp4",
                        "report": "integrity-report.json", "conclusion": "complete"}

            with patch("video_downloader.services.download_executor.LiveRunner") as runner, \
                    patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                runner.return_value.run.side_effect = stopped
                result = executor.batch_download([
                    "https://www.youtube.com/live/fixture",
                    "https://www.youtube.com/watch?v=following",
                ])

            self.assertTrue(result["ok"])
            executor._spawn.assert_not_called()
            self.assertEqual(callbacks["add_history"].call_count, 1)
            self.assertEqual(callbacks["add_history"].call_args.args[3], "stopped")
            self.assertFalse(executor._download_manager.snapshot()["running"])
