import unittest

from video_downloader.core.utils import detect_platform, is_live_url


class UtilsTests(unittest.TestCase):
    def test_detect_platform_requires_matching_hostname(self):
        self.assertEqual(detect_platform("https://www.youtube.com/watch?v=abc"), "YouTube")
        self.assertIsNone(detect_platform("https://example.com/youtube.com/live/abc"))
        self.assertEqual(detect_platform("https://twitcasting.tv/someuser"), "TwitCasting")

    def test_live_detection_uses_platform_specific_url_shapes(self):
        self.assertTrue(is_live_url("https://www.youtube.com/live/abc", "YouTube"))
        self.assertFalse(is_live_url("https://www.youtube.com/watch?v=live-recording", "YouTube"))
        self.assertTrue(is_live_url("https://www.twitch.tv/channel", "Twitch"))
        self.assertFalse(is_live_url("https://www.twitch.tv/videos/123", "Twitch"))
        self.assertFalse(is_live_url("https://clips.twitch.tv/Slug", "Twitch"))
        self.assertTrue(is_live_url("https://live.nicovideo.jp/watch/lv123", "Niconico"))
        self.assertFalse(is_live_url("https://www.nicovideo.jp/watch/sm123", "Niconico"))
        self.assertFalse(is_live_url("https://fantia.jp/posts/live", "Fantia"))
        self.assertTrue(is_live_url("https://twitcasting.tv/someuser", "TwitCasting"))
        self.assertFalse(is_live_url("https://twitcasting.tv/someuser/movie/123", "TwitCasting"))
        self.assertFalse(is_live_url("https://twitcasting.tv/someuser/show", "TwitCasting"))
        self.assertFalse(is_live_url("https://twitcasting.tv/someuser/archive", "TwitCasting"))


if __name__ == "__main__":
    unittest.main()
