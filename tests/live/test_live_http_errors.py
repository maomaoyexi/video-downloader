"""直播预检应区分状态、格式和网络错误。"""
import json
import subprocess
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from video_downloader.core.platform import is_live_url
from video_downloader.live.inspect import LiveInspector
from video_downloader.live.probe import ProbeService
from video_downloader.live.urls import classify_target


class LiveHttpErrorTests(unittest.TestCase):
    youtube_url = "https://www.youtube.com/live/UpYrR2rLdRg"
    format_error = "ERROR: [youtube] UpYrR2rLdRg: Requested format is not available. Use --list-formats for a list of available formats"

    def youtube_inspection(self, first_error, recovered=None):
        def run(command, timeout):
            if "--ignore-no-formats-error" in command and recovered is not None:
                return subprocess.CompletedProcess(command, 0, json.dumps(recovered), "")
            return subprocess.CompletedProcess(command, 1, "", first_error)

        runner = Mock(side_effect=run)
        inspector = LiveInspector(ProbeService(ytdlp_path="yt-dlp", runner=runner))
        return inspector.inspect(self.youtube_url), runner

    def test_youtube_upcoming_status_is_recovered_without_playable_formats(self):
        result, runner = self.youtube_inspection(self.format_error, {
            "live_status": "is_upcoming", "release_timestamp": 1800000000,
            "formats": [{"format_id": "sb0", "vcodec": "none", "acodec": "none"}],
        })
        self.assertEqual(result["status"], "upcoming")
        self.assertEqual(result["scheduled_start"], 1800000000)
        self.assertEqual(result["effective_mode"], "wait")
        self.assertNotIn("error", result)
        initial, recovery = runner.call_args_list
        self.assertNotIn("--ignore-no-formats-error", initial.args[0])
        self.assertIn("--ignore-no-formats-error", recovery.args[0])
        self.assertEqual(recovery.args[0][-1], self.youtube_url)
        self.assertLessEqual(recovery.args[1], initial.args[1])

    def test_youtube_format_error_blocks_start_when_recording_or_replay_is_unavailable(self):
        for status, expected, message in (("is_live", "error", "可录制"),
                                          ("post_live", "ended", "回放格式"),
                                          ("was_live", "ended", "回放格式")):
            with self.subTest(status=status):
                result, runner = self.youtube_inspection(self.format_error, {"live_status": status, "formats": []})
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["effective_mode"], "")
                self.assertIn(message, result["error"])
                self.assertEqual(result["probe_error"], result["error"])
                self.assertNotIn("replay_url", result)
                self.assertEqual(runner.call_count, 2)

    def test_confirmed_youtube_replay_has_a_vod_url_with_the_same_case_sensitive_id(self):
        for video_id in ("UpYrR2rLdRg", "OtherVideo1"):
            with self.subTest(video_id=video_id):
                info = {"id": video_id, "live_status": "was_live"}
                runner = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(info), ""))
                inspector = LiveInspector(ProbeService(ytdlp_path="yt-dlp", runner=runner))
                result = inspector.inspect(self.youtube_url)
                self.assertEqual(result["status"], "ended")
                if video_id == "UpYrR2rLdRg":
                    self.assertEqual(result["replay_url"], "https://www.youtube.com/watch?v=UpYrR2rLdRg")
                    self.assertFalse(is_live_url(result["replay_url"]))
                else:
                    self.assertNotIn("replay_url", result)

    def test_youtube_metadata_retry_respects_inspection_deadline(self):
        with patch("video_downloader.live.probe.time.monotonic", side_effect=[0, 21]):
            result, runner = self.youtube_inspection(self.format_error)
        self.assertIn("暂时无法确认直播状态", result["error"])
        self.assertEqual(runner.call_count, 1)

    def test_youtube_permission_and_network_errors_are_not_retried_without_formats(self):
        for message, status in (("Login required", "private"), ("Connection reset", "error")):
            with self.subTest(message=message):
                result, runner = self.youtube_inspection(f"ERROR: [youtube] {message}")
                self.assertEqual(result["status"], status)
                self.assertIn(message, result["error"])
                self.assertEqual(runner.call_count, 1)

    def test_local_file_error_is_not_reported_as_a_retryable_network_error(self):
        for url in ("https://live.bilibili.com/123", "https://twitcasting.tv/fixture"):
            with self.subTest(url=url), patch("video_downloader.live.probe.urlopen",
                                              side_effect=FileNotFoundError(2, "No such file or directory")):
                service = ProbeService(ytdlp_path="unused")
                result = LiveInspector(service).inspect(url)
                self.assertIn("本地运行文件缺失", result["error"])
                self.assertNotIn("网络错误", result["error"])
                self.assertEqual(result["error"], result["probe_error"])
                self.assertFalse(service.probe(classify_target(url)).retryable)

    def test_actual_network_error_still_allows_retry(self):
        with patch("video_downloader.live.probe.urlopen",
                   side_effect=URLError("fixture network unavailable")):
            probe = ProbeService(ytdlp_path="unused").probe(classify_target("https://live.bilibili.com/123"))
        self.assertIn("网络错误", probe.error)
        self.assertTrue(probe.retryable)


if __name__ == "__main__":
    unittest.main()
