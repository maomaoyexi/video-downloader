import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from video_downloader.core.constants import DEFAULT_CONFIG, DEFAULT_SUBTITLE_LANGS
from video_downloader.core.command import build_ytdlp_cmd, parse_custom_ytdlp_args
from video_downloader.core.platform import detect_platform


class YtdlpCommandTests(unittest.TestCase):
    def test_custom_args_parser_preserves_quoted_values(self):
        self.assertEqual(
            parse_custom_ytdlp_args('--add-header "Referer: https://example.com/a b" --sleep-requests 1'),
            ["--add-header", "Referer: https://example.com/a b", "--sleep-requests", "1"],
        )

    def test_custom_args_parser_rejects_unclosed_quote(self):
        with self.assertRaisesRegex(ValueError, "自定义 yt-dlp 参数无法解析"):
            parse_custom_ytdlp_args('--add-header "unterminated')

    @unittest.skipUnless(os.name == "nt", "Windows command-line parsing")
    def test_custom_args_parser_preserves_windows_path_backslashes(self):
        parsed = parse_custom_ytdlp_args(r'--cookies D:\VideoTools\cookies.txt')
        self.assertEqual(parsed, ["--cookies", r"D:\VideoTools\cookies.txt"])

    def test_default_and_one_time_custom_args_are_appended_before_url(self):
        config = dict(DEFAULT_CONFIG, YTDLP_DEFAULT_ARGS="--sleep-requests 2")
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc",
                config,
                Path(directory),
                custom_args="--retries 20",
            )
        self.assertEqual(cmd[-5:], ["--sleep-requests", "2", "--retries", "20", "https://youtube.com/watch?v=abc"])

    def test_youtube_po_provider_base_url_is_passed_to_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc",
                DEFAULT_CONFIG,
                Path(directory),
                po_token_base_url="http://[::1]:4416",
            )
        extractor_args = [
            cmd[index + 1]
            for index, value in enumerate(cmd[:-1])
            if value == "--extractor-args"
        ]
        self.assertIn(
            "youtubepot-bgutilhttp:base_url=http://[::1]:4416",
            extractor_args,
        )

    def test_youtube_subtitle_command_uses_po_provider_base_url(self):
        config = dict(DEFAULT_CONFIG, DOWNLOAD_SUBTITLES=1)
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc",
                config,
                Path(directory),
                subtitle_only=True,
                po_token_base_url="http://[::1]:4416",
            )
        self.assertIn(
            "youtubepot-bgutilhttp:base_url=http://[::1]:4416",
            cmd,
        )

    def test_subtitles_are_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd("https://youtube.com/watch?v=abc", DEFAULT_CONFIG, Path(directory))
        self.assertNotIn("--write-subs", cmd)
        self.assertNotIn("--write-auto-subs", cmd)

    def test_clean_layout_routes_dependencies_downloads_and_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "dependency"
            dependency.mkdir()
            (dependency / "yt-dlp.exe").touch()
            (dependency / "ffmpeg.exe").touch()
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc",
                DEFAULT_CONFIG,
                root,
                ".exe",
            )
        self.assertEqual(cmd[0], str(dependency / "yt-dlp.exe"))
        self.assertEqual(cmd[cmd.index("--ffmpeg-location") + 1], str(dependency))
        self.assertTrue(cmd[cmd.index("-o") + 1].startswith(str(root / "download" / "YouTube")))
        self.assertEqual(
            cmd[cmd.index("--download-archive") + 1],
            str(root / "download" / "archive" / "youtube_archive.txt"),
        )

    def test_every_ytdlp_platform_uses_its_download_and_archive_folders(self):
        platforms = (
            "YouTube",
            "Bilibili",
            "Twitch",
            "Niconico",
            "NicoChannel",
            "Fantia",
            "TwitCasting",
            "Twitter",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for platform in platforms:
                with self.subTest(platform=platform):
                    config = dict(DEFAULT_CONFIG, PLATFORM=platform)
                    cmd = build_ytdlp_cmd(
                        "https://example.com/video", config, root
                    )
                    self.assertTrue(
                        cmd[cmd.index("-o") + 1].startswith(
                            str(root / "download" / platform)
                        )
                    )
                    self.assertEqual(
                        cmd[cmd.index("--download-archive") + 1],
                        str(
                            root
                            / "download"
                            / "archive"
                            / f"{platform.lower()}_archive.txt"
                        ),
                    )

    def test_legacy_root_dependencies_remain_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "yt-dlp.exe").touch()
            (root / "ffmpeg.exe").touch()
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc",
                DEFAULT_CONFIG,
                root,
                ".exe",
            )
        self.assertEqual(cmd[0], str(root / "yt-dlp.exe"))
        self.assertEqual(cmd[cmd.index("--ffmpeg-location") + 1], str(root))

    def test_partially_migrated_plugins_load_from_both_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "dependency"
            dependency.mkdir()
            (dependency / "nicochannel.zip").touch()
            (root / "yt-dlp-plugins").mkdir()

            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc", DEFAULT_CONFIG, root
            )

        plugin_dirs = [
            cmd[index + 1]
            for index, value in enumerate(cmd[:-1])
            if value == "--plugin-dirs"
        ]
        self.assertEqual(plugin_dirs, [str(dependency), str(root)])

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

    def test_disabled_proxy_is_explicit_direct_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc", DEFAULT_CONFIG, Path(directory)
            )
        self.assertEqual(cmd[cmd.index("--proxy") + 1], "")

    def test_enabled_proxy_uses_configured_address(self):
        config = dict(
            DEFAULT_CONFIG,
            PROXY_ENABLED=1,
            PROXY_TYPE="http",
            PROXY_ADDR="127.0.0.1",
            PROXY_PORT="7897",
        )
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc", config, Path(directory)
            )
        self.assertEqual(cmd[cmd.index("--proxy") + 1], "http://127.0.0.1:7897")

    def test_firefox_default_profile_uses_automatic_detection(self):
        config = dict(
            DEFAULT_CONFIG,
            USE_COOKIES=1,
            COOKIE_MODE=2,
            BROWSER_NAME="firefox",
            BROWSER_PROFILE="Default",
        )
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://twitcasting.tv/user/movie/123", config, Path(directory),
                platform_override="TwitCasting",
            )
        self.assertEqual(cmd[cmd.index("--cookies-from-browser") + 1], "firefox")

    def test_named_firefox_profile_is_preserved(self):
        config = dict(
            DEFAULT_CONFIG,
            USE_COOKIES=1,
            COOKIE_MODE=2,
            BROWSER_NAME="firefox",
            BROWSER_PROFILE="abc.default-release",
        )
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://twitcasting.tv/user/movie/123", config, Path(directory),
                platform_override="TwitCasting",
            )
        self.assertEqual(
            cmd[cmd.index("--cookies-from-browser") + 1],
            "firefox:abc.default-release",
        )

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
            plugin = (
                Path(directory)
                / "yt-dlp-plugins/video_downloader/yt_dlp_plugins/postprocessor/"
                / "twitcasting_parallel.py"
            )
            plugin.parent.mkdir(parents=True)
            plugin.touch()
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
        self.assertIn("--enable-file-urls", cmd)
        postprocessors = [
            cmd[index + 1]
            for index, value in enumerate(cmd[:-1])
            if value == "--use-postprocessor"
        ]
        self.assertIn("TwitCastingParallelHls:when=before_dl", postprocessors)
        self.assertIn(
            "TwitCastingParallelHls:when=post_process;cleanup=true",
            postprocessors,
        )
        self.assertEqual(
            cmd[cmd.index("--downloader-args") + 1],
            "ffmpeg_i:-http_persistent 1 -http_multiple 1",
        )

    def test_twitcasting_hls_missing_plugin_safely_keeps_ffmpeg_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://twitcasting.tv/someuser/movie/123",
                DEFAULT_CONFIG,
                Path(directory),
                is_live=False,
                platform_override="TwitCasting",
                use_ffmpeg_for_hls=True,
            )
        self.assertEqual(cmd[cmd.index("--downloader") + 1], "m3u8:ffmpeg")
        self.assertNotIn("--use-postprocessor", cmd)
        self.assertNotIn("--enable-file-urls", cmd)

    def test_twitcasting_hls_finds_plugin_bundled_by_pyinstaller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool_dir = root / "dist"
            bundle_dir = root / "bundle"
            tool_dir.mkdir()
            plugin = (
                bundle_dir
                / "yt-dlp-plugins/video_downloader/yt_dlp_plugins/postprocessor/"
                / "twitcasting_parallel.py"
            )
            plugin.parent.mkdir(parents=True)
            plugin.touch()
            with mock.patch(
                "video_downloader.core.command.sys._MEIPASS",
                str(bundle_dir),
                create=True,
            ):
                cmd = build_ytdlp_cmd(
                    "https://twitcasting.tv/someuser/movie/123",
                    DEFAULT_CONFIG,
                    tool_dir,
                    is_live=False,
                    platform_override="TwitCasting",
                    use_ffmpeg_for_hls=True,
                )
        plugin_dirs = [
            cmd[index + 1]
            for index, value in enumerate(cmd[:-1])
            if value == "--plugin-dirs"
        ]
        self.assertIn(str(bundle_dir), plugin_dirs)
        self.assertIn("--use-postprocessor", cmd)

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
        self.assertNotIn("--use-postprocessor", cmd)

    def test_youtube_uses_web_embedded_fallback_for_ended_live_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtu.be/ffDnUgMOpss",
                DEFAULT_CONFIG,
                Path(directory),
                platform_override="YouTube",
            )
        self.assertIn("--extractor-args", cmd)
        self.assertEqual(
            cmd[cmd.index("--extractor-args") + 1],
            "youtube:player_client=default,web_embedded",
        )

    def test_non_youtube_platform_does_not_inject_youtube_client_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://www.twitch.tv/videos/123",
                DEFAULT_CONFIG,
                Path(directory),
                platform_override="Twitch",
            )
        self.assertNotIn("youtube:player_client", cmd)

    def test_other_platforms_keep_default_hls_downloader(self):
        with tempfile.TemporaryDirectory() as directory:
            cmd = build_ytdlp_cmd(
                "https://youtube.com/watch?v=abc",
                DEFAULT_CONFIG,
                Path(directory),
                platform_override="YouTube",
            )
        self.assertNotIn("--downloader", cmd)
        self.assertNotIn("--use-postprocessor", cmd)

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
