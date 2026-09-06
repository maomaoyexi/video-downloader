import tempfile
import unittest
from pathlib import Path

from video_downloader.core.constants import DEFAULT_CONFIG, DEFAULT_SUBTITLE_LANGS
from video_downloader.core.command import build_ytdlp_cmd
from video_downloader.core.platform import detect_platform


class YtdlpCommandTests(unittest.TestCase):
    def test_subtitles_are_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd("https://youtube.com/watch?v=abc", DEFAULT_CONFIG, Path(directory))
        self.assertNotIn("--write-subs", cmd)
        self.assertNotIn("--write-auto-subs", cmd)

    def test_enabled_subtitles_use_chinese_languages_and_separate_directory(self):
        config = dict(DEFAULT_CONFIG, DOWNLOAD_SUBTITLES=1)
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd("https://youtube.com/watch?v=abc", config, Path(directory))
        self.assertIn("--write-subs", cmd)
        self.assertIn("--write-auto-subs", cmd)
        self.assertEqual(cmd[cmd.index("--sub-langs") + 1], DEFAULT_SUBTITLE_LANGS)
        subtitle_output = cmd[cmd.index("-o", cmd.index("-o") + 1) + 1]
        self.assertIn("subtitles", subtitle_output)

    def test_subtitle_only_command_skips_video_and_archive(self):
        config = dict(DEFAULT_CONFIG, DOWNLOAD_SUBTITLES=1)
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc", config, Path(directory), subtitle_only=True
            )
        self.assertIn("--skip-download", cmd)
        self.assertNotIn("--download-archive", cmd)
        self.assertNotIn("-f", cmd)

    def test_video_command_can_omit_subtitles_for_sidecar(self):
        config = dict(DEFAULT_CONFIG, DOWNLOAD_SUBTITLES=1)
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc", config, Path(directory), include_subtitles=False
            )
        self.assertNotIn("--write-subs", cmd)
        self.assertNotIn("--write-auto-subs", cmd)
    def test_progress_template_includes_media_stage_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc",
                DEFAULT_CONFIG,
                Path(directory),
            )
        self.assertIn("--progress-template", cmd)
        template = cmd[cmd.index("--progress-template") + 1]
        self.assertIn("__VD_STAGE__%(info.vcodec)s|%(info.acodec)s", template)

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

    def test_twitcasting_hls_uses_ffmpeg_downloader_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://twitcasting.tv/someuser/movie/123",
                DEFAULT_CONFIG,
                Path(directory),
                is_live=False,
                platform_override="TwitCasting",
                use_ffmpeg_for_hls=True,
            )
        self.assertIn("--downloader", cmd)
        self.assertEqual(cmd[cmd.index("--downloader") + 1], "m3u8:ffmpeg")

    def test_twitcasting_default_uses_native_hls_downloader(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://twitcasting.tv/someuser/movie/123",
                DEFAULT_CONFIG,
                Path(directory),
                is_live=False,
                platform_override="TwitCasting",
            )
        self.assertNotIn("--downloader", cmd)

    def test_other_platforms_keep_default_hls_downloader(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc",
                DEFAULT_CONFIG,
                Path(directory),
                platform_override="YouTube",
            )
        self.assertNotIn("--downloader", cmd)

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
