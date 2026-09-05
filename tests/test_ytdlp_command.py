import tempfile
import unittest
from pathlib import Path

from video_downloader.core.constants import DEFAULT_CONFIG
from video_downloader.core.command import build_ytdlp_cmd
from video_downloader.core.platform import detect_platform


class YtdlpCommandTests(unittest.TestCase):
    def test_youtube_live_command_uses_live_options_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/live/abc",
                DEFAULT_CONFIG,
                Path(directory),
                is_live=True,
                platform_override="YouTube",
            )
        self.assertIn("--live-from-start", cmd)
        output = cmd[cmd.index("-o") + 1]
        self.assertIn("直播", output)

    def test_twitch_live_still_uses_live_template(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://www.twitch.tv/xqc",
                DEFAULT_CONFIG,
                Path(directory),
                is_live=True,
                platform_override="Twitch",
            )
        self.assertIn("--live-from-start", cmd)
        output = cmd[cmd.index("-o") + 1]
        self.assertIn("直播", output)

    def test_twitch_vod_uses_vod_template(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://www.twitch.tv/videos/123",
                DEFAULT_CONFIG,
                Path(directory),
                is_live=False,
                platform_override="Twitch",
            )
        self.assertNotIn("--live-from-start", cmd)
        output = cmd[cmd.index("-o") + 1]
        self.assertNotIn("直播", output)

    def test_twitcasting_live_uses_live_template(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://twitcasting.tv/someuser",
                DEFAULT_CONFIG,
                Path(directory),
                is_live=True,
                platform_override="TwitCasting",
            )
        self.assertIn("--live-from-start", cmd)
        output = cmd[cmd.index("-o") + 1]
        self.assertIn("直播", output)
        self.assertIn("TwitCasting", output)

    def test_twitcasting_password_injected_when_set(self):
        config = dict(DEFAULT_CONFIG, TC_PASSWORD="secret")
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://twitcasting.tv/someuser/movie/123",
                config,
                Path(directory),
                is_live=False,
                platform_override="TwitCasting",
            )
        self.assertIn("--video-password", cmd)
        self.assertEqual(cmd[cmd.index("--video-password") + 1], "secret")

    def test_twitcasting_password_absent_when_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://twitcasting.tv/someuser/movie/123",
                DEFAULT_CONFIG,
                Path(directory),
                is_live=False,
                platform_override="TwitCasting",
            )
        self.assertNotIn("--video-password", cmd)

    # ── nicochannel ──────────────────────────────────────────────

    def test_nicochannel_with_auth_token_passes_jwt_via_username_password(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://nicochannel.jp/channel/video/12345",
                DEFAULT_CONFIG,
                Path(directory),
                platform_override="NicoChannel",
                nicochannel_auth_token="test-jwt-token",
            )
        self.assertIn("--username", cmd)
        self.assertIn("--password", cmd)
        user_idx = cmd.index("--username")
        pass_idx = cmd.index("--password")
        self.assertEqual(cmd[user_idx + 1], "jwt_token")
        self.assertEqual(cmd[pass_idx + 1], "test-jwt-token")

    def test_nicochannel_without_auth_token_skips_jwt_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://nicochannel.jp/channel/video/12345",
                DEFAULT_CONFIG,
                Path(directory),
                platform_override="NicoChannel",
                nicochannel_auth_token=None,
            )
        self.assertNotIn("jwt_token", cmd)

    def test_nicochannel_platform_detection(self):
        self.assertEqual(
            detect_platform("https://nicochannel.jp/channel/video/12345"),
            "NicoChannel",
        )
        self.assertEqual(
            detect_platform("https://www.nicochannel.jp/channel/video/abc"),
            "NicoChannel",
        )


if __name__ == "__main__":
    unittest.main()
