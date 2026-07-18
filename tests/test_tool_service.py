import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_downloader.services.tools import ToolService


class FakeAppState:
    def __init__(self):
        self.updates = []

    def update_config(self, values):
        self.updates.append(values)


def create_service(tool_dir):
    return ToolService(
        tool_dir=tool_dir,
        exe_suffix=".exe",
        app_state=FakeAppState(),
        save_config=lambda: None,
        log=lambda message, level="info": None,
    )


class ToolServiceTests(unittest.TestCase):
    def test_check_deps_reports_all_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            (tool_dir / "ffmpeg.exe").touch()
            service = create_service(tool_dir)
            self.assertEqual(service.check_deps(), {
                "yt-dlp": True,
                "ffmpeg": True,
                "ffprobe": False,
                "fantiadl": False,
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
            nested = tool_dir / "nested"
            nested.mkdir()
            (nested / "video.part").touch()
            (nested / "state.ytdl").touch()
            kept = tool_dir / "video.mp4"
            kept.touch()
            result = create_service(tool_dir).clean_temp()
            self.assertEqual(result, {"ok": True, "count": 2})
            self.assertTrue(kept.exists())
            self.assertFalse((nested / "video.part").exists())

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
            tool_dir = Path(directory)
            service = create_service(tool_dir)
            with patch.object(service, "open_folder", side_effect=lambda path: {"path": path}):
                self.assertEqual(service.handle_tool_action("open-downloads"), {"path": tool_dir})
                self.assertEqual(service.handle_tool_action("open-logs"), {"path": tool_dir / "logs"})

    def test_handle_tool_action_rejects_unknown_action(self):
        with tempfile.TemporaryDirectory() as directory:
            service = create_service(Path(directory))
            self.assertEqual(
                service.handle_tool_action("missing"),
                {"error": "未知工具操作: missing"},
            )


if __name__ == "__main__":
    unittest.main()
