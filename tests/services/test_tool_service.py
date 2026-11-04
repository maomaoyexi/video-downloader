import tempfile
import unittest
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from unittest.mock import patch

from video_downloader.services.download_manager import DownloadManager
from video_downloader.services.tools import ToolService


from tests.helpers.tools import FakeAppState, create_service, ImmediateThread, FakePopen


class ToolServiceTests(unittest.TestCase):
    def test_cleanup_refuses_queued_tasks_without_deleting_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partial = root / "download" / "video.part"
            partial.parent.mkdir()
            partial.touch()
            manager = DownloadManager()
            service = create_service(root, download_manager=manager)
            service._has_active_downloads = lambda: True
            self.assertIn("error", service.clean_temp())
            self.assertTrue(partial.exists())
            self.assertTrue(manager.snapshot()["accepting"])
    def test_check_deps_reports_all_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            (tool_dir / "ffmpeg.exe").touch()
            service = create_service(tool_dir)
            status = service.check_deps()
            for key in ('live_comment_export', 'live_comment_transport', 'live_comment_niconico'):
                self.assertIsInstance(status.pop(key), bool)
            self.assertEqual(status, {
                "yt-dlp": True,
                "ffmpeg": True,
                "ffprobe": False,
                "fantiadl": False,
                "withny_dl": False,
            "withny_live_chat": False,
                "nicochannel_plugin": False,
                "youtube_po_token": False,
            })

    def test_read_urls_file_filters_blank_and_comment_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "urls.txt").write_text(
                "# ignored\n\nhttps://example.com/one\n https://example.com/two \n",
                encoding="utf-8",
            )
            service = create_service(tool_dir)
            self.assertEqual(service.read_urls_file(), ([
                "https://example.com/one",
                "https://example.com/two",
            ], None))

    def test_clean_temp_only_removes_known_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            nested = tool_dir / "download" / "nested"
            nested.mkdir(parents=True)
            (nested / "video.part").touch()
            (nested / "state.ytdl").touch()
            kept = tool_dir / "video.mp4"
            kept.touch()
            result = create_service(tool_dir).clean_temp()
            self.assertEqual(result, {"ok": True, "count": 2})
            self.assertTrue(kept.exists())
            self.assertFalse((nested / "video.part").exists())

    def test_cookie_template_is_loadable_netscape_file_without_login_cookies(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            result = create_service(tool_dir).gen_cookie_template()
            self.assertEqual(result, {"ok": True})
            cookie_file = tool_dir / "cookies.txt"
            raw = cookie_file.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            lines = raw.decode("utf-8").splitlines()
            self.assertEqual(lines[0], "# Netscape HTTP Cookie File")
            self.assertIn("# 使用说明：", lines)
            self.assertIn("# 这是空白格式模板，不含真实登录 Cookie。", lines)
            self.assertTrue(all(not line.strip() or line.startswith("#") for line in lines))
            jar = MozillaCookieJar(str(cookie_file))
            # Read UTF-8 explicitly rather than the Windows locale's default GBK.
            with cookie_file.open(encoding="utf-8") as file:
                jar._really_load(file, str(cookie_file), True, True)
            self.assertEqual(len(jar), 0)

    def test_templates_do_not_overwrite_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            urls_file = tool_dir / "urls.txt"
            cookie_file = tool_dir / "cookies.txt"
            urls_file.write_text("existing urls", encoding="utf-8")
            cookie_file.write_text("existing cookies", encoding="utf-8")
            service = create_service(tool_dir)
            self.assertTrue(service.gen_url_template()["existed"])
            self.assertTrue(service.gen_cookie_template()["existed"])
            self.assertEqual(urls_file.read_text(encoding="utf-8"), "existing urls")
            self.assertEqual(cookie_file.read_text(encoding="utf-8"), "existing cookies")

    def test_handle_tool_action_routes_every_explicit_action(self):
        with tempfile.TemporaryDirectory() as directory:
            service = create_service(Path(directory))
            method_names = [
                "gen_url_template",
                "gen_cookie_template",
                "update_ytdlp",
                "clean_temp",
            ]
            actions = [
                "gen-template",
                "gen-cookie-template",
                "update-ytdlp",
                "clean-temp",
            ]
            for method_name, action in zip(method_names, actions):
                with self.subTest(action=action), patch.object(service, method_name, return_value={"action": action}):
                    self.assertEqual(service.handle_tool_action(action), {"action": action})

    def test_handle_tool_action_routes_folder_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory).resolve()
            service = create_service(tool_dir)
            with patch.object(service, "open_folder", side_effect=lambda path: {"path": path}):
                self.assertEqual(service.handle_tool_action("open-downloads"), {"path": tool_dir / "download"})
                self.assertEqual(service.handle_tool_action("open-logs"), {"path": tool_dir / "download" / "logs"})

    def test_handle_tool_action_rejects_unknown_action(self):
        with tempfile.TemporaryDirectory() as directory:
            service = create_service(Path(directory))
            self.assertEqual(
                service.handle_tool_action("missing"),
                {"error": "未知工具操作: missing"},
            )

    def test_download_subtitles_rejects_concurrent_task(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            manager = DownloadManager()
            handle = manager.begin("video")
            service = create_service(
                tool_dir,
                build_subtitle_command=lambda *args, **kwargs: [],
                download_manager=manager,
            )
            result = service.download_subtitles(
                ["https://youtube.com/watch?v=abc"], "manual", "zh.*"
            )
            self.assertEqual(result, {"error": "已有下载任务正在运行"})
            manager.finish(handle)

    def test_download_subtitles_runs_and_releases_task(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            manager = DownloadManager()
            calls = []
            service = create_service(
                tool_dir,
                build_subtitle_command=lambda *args, **kwargs: calls.append((args, kwargs)) or ["yt-dlp.exe"],
                download_manager=manager,
            )
            with patch("video_downloader.services.tools.threading.Thread", ImmediateThread), \
                 patch("video_downloader.services.tools.subprocess.Popen", return_value=FakePopen(
                     stdout="[info] Writing video subtitles to: subtitles/video.zh.vtt"
                 )):
                result = service.download_subtitles(
                    ["https://youtube.com/watch?v=abc"], "all", "zh.*"
                )
            self.assertEqual(result, {"ok": True, "total": 1})
            self.assertFalse(manager.snapshot()["running"])
            self.assertEqual(calls[0][1]["subtitle_type"], "all")
            self.assertEqual(calls[0][1]["subtitle_langs"], "zh.*")

    def test_download_covers_skips_fantia_without_calling_ytdlp(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            manager = DownloadManager()
            calls = []
            logs = []
            service = create_service(
                tool_dir,
                build_cover_command=lambda *args, **kwargs: calls.append(args) or ["yt-dlp.exe"],
                download_manager=manager,
                log=lambda message, level="info": logs.append(message),
            )
            with patch("video_downloader.services.tools.threading.Thread", ImmediateThread), \
                 patch("video_downloader.services.tools.subprocess.Popen") as popen:
                result = service.download_covers(["https://fantia.jp/posts/123"])
            self.assertEqual(result, {"ok": True, "total": 1})
            popen.assert_not_called()
            self.assertEqual(calls, [])
            self.assertTrue(any("Fantia" in message for message in logs))
            self.assertFalse(manager.snapshot()["running"])

    def test_download_covers_skips_unrecognised_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            manager = DownloadManager()
            logs = []
            service = create_service(
                tool_dir,
                build_cover_command=lambda *args, **kwargs: ["yt-dlp.exe"],
                download_manager=manager,
                log=lambda message, level="info": logs.append(message),
            )
            with patch("video_downloader.services.tools.threading.Thread", ImmediateThread), \
                 patch("video_downloader.services.tools.subprocess.Popen") as popen:
                result = service.download_covers(["https://example.com/video"])
            self.assertEqual(result, {"ok": True, "total": 1})
            popen.assert_not_called()
            self.assertTrue(any("未识别的平台" in message for message in logs))

    def test_download_covers_reports_written_thumbnail_name(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            manager = DownloadManager()
            calls = []
            logs = []
            service = create_service(
                tool_dir,
                build_cover_command=lambda *args, **kwargs: calls.append(kwargs) or ["yt-dlp.exe"],
                download_manager=manager,
                log=lambda message, level="info": logs.append(message),
            )
            with patch("video_downloader.services.tools.threading.Thread", ImmediateThread), \
                 patch("video_downloader.services.tools.subprocess.Popen", return_value=FakePopen(
                     stdout=(
                         "[info] Writing video thumbnail 45 to: cover\\video.webp\n"
                         '[ThumbnailsConvertor] Converting thumbnail "cover\\video.webp" to jpg\n'
                     )
                 )):
                result = service.download_covers(["https://youtube.com/watch?v=abc"])
            self.assertEqual(result, {"ok": True, "total": 1})
            self.assertEqual(calls[0]["platform_override"], "YouTube")
            # 转换后原文件会被删除，因此要报告 jpg 而不是 webp。
            self.assertTrue(any("video.jpg" in message for message in logs))
            self.assertFalse(manager.snapshot()["running"])

    def test_download_covers_rejects_concurrent_task(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            manager = DownloadManager()
            handle = manager.begin("video")
            service = create_service(
                tool_dir,
                build_cover_command=lambda *args, **kwargs: [],
                download_manager=manager,
            )
            result = service.download_covers(["https://youtube.com/watch?v=abc"])
            self.assertEqual(result, {"error": "已有下载任务正在运行"})
            manager.finish(handle)


if __name__ == "__main__":
    unittest.main()
