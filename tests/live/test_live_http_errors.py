"""本地运行文件故障与真实网络故障应准确区分。"""
import unittest
from unittest.mock import patch
from urllib.error import URLError

from video_downloader.live.inspect import LiveInspector
from video_downloader.live.probe import ProbeService
from video_downloader.live.urls import classify_target


class LiveHttpErrorTests(unittest.TestCase):
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
