from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from video_downloader import cli


class CliLiveTests(unittest.TestCase):
    def test_redirected_cli_output_accepts_unicode_titles(self):
        import io
        binary=io.BytesIO()
        output=io.TextIOWrapper(binary,encoding='gbk')
        with patch.object(cli.sys,'stdout',output),patch.object(cli.sys,'stderr',output):
            self.assertEqual(cli.run_cli(['--help']),0)
            print('测试标题 💜')
            output.flush()
        self.assertIn('💜'.encode(),binary.getvalue())
    def test_single_live_url_passes_live_mode_to_command_builder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "dependency"
            dependency.mkdir()
            (dependency / "yt-dlp.exe").touch()
            (dependency / "ffmpeg.exe").touch()
            process = Mock(returncode=0)
            with patch.object(cli, "_find_tool_dir", return_value=root), \
                 patch.object(cli, "_get_exe_suffix", return_value=".exe"), \
                 patch.object(cli, "build_ytdlp_cmd", return_value=["yt-dlp.exe"]) as build, \
                 patch.object(cli.subprocess, "Popen", return_value=process), \
                 patch("builtins.print"):
                self.assertEqual(cli._cmd_download("https://youtube.com/live/abc"), 0)

            self.assertTrue(build.call_args.kwargs["is_live"])
            self.assertEqual(build.call_args.kwargs["platform_override"], "YouTube")

    def test_single_vod_url_keeps_vod_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "dependency"
            dependency.mkdir()
            (dependency / "yt-dlp.exe").touch()
            (dependency / "ffmpeg.exe").touch()
            process = Mock(returncode=0)
            with patch.object(cli, "_find_tool_dir", return_value=root), \
                 patch.object(cli, "_get_exe_suffix", return_value=".exe"), \
                 patch.object(cli, "build_ytdlp_cmd", return_value=["yt-dlp.exe"]) as build, \
                 patch.object(cli.subprocess, "Popen", return_value=process), \
                 patch("builtins.print"):
                self.assertEqual(cli._cmd_download("https://youtube.com/watch?v=abc"), 0)

            self.assertFalse(build.call_args.kwargs["is_live"])


class CliBatchTests(unittest.TestCase):
    def test_ctrl_c_stops_the_batch_before_launching_another_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "dependency"
            dependency.mkdir()
            for name in ("yt-dlp.exe", "ffmpeg.exe"):
                (dependency / name).touch()
            urls = root / "urls.txt"
            urls.write_text("https://www.bilibili.com/video/BV1first\nhttps://www.bilibili.com/video/BV1second\n",
                            encoding="utf-8")
            interrupted = Mock(returncode=0)
            interrupted.wait.side_effect = [KeyboardInterrupt, 0]
            later = Mock(returncode=0)
            output = StringIO()
            with patch.object(cli, "_find_tool_dir", return_value=root), \
                 patch.object(cli, "_get_exe_suffix", return_value=".exe"), \
                 patch.object(cli.subprocess, "Popen", side_effect=[interrupted, later]) as spawn, \
                 redirect_stdout(output):
                self.assertEqual(cli.run_cli(["--batch", str(urls)]), 130)
            interrupted.terminate.assert_called_once_with()
            self.assertEqual(spawn.call_count, 1)
            self.assertIn("已取消", output.getvalue())

    def test_bom_prefixed_batch_keeps_the_first_links_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "dependency"
            dependency.mkdir()
            for name in ("yt-dlp.exe", "ffmpeg.exe"):
                (dependency / name).touch()
            urls = root / "urls.txt"
            urls.write_text("https://www.bilibili.com/video/BV1sample\n", encoding="utf-8-sig")
            output = StringIO()
            with patch.object(cli, "_find_tool_dir", return_value=root), \
                 patch.object(cli, "_get_exe_suffix", return_value=".exe"), \
                 patch.object(cli.subprocess, "Popen", return_value=Mock(returncode=0)), \
                 redirect_stdout(output):
                self.assertEqual(cli.run_cli(["--batch", str(urls)]), 0)
            self.assertIn("平台: Bilibili (自动识别)", output.getvalue())

    def test_badly_encoded_batch_returns_a_read_error_without_starting_download(self):
        with tempfile.TemporaryDirectory() as directory:
            urls = Path(directory) / "urls.txt"
            urls.write_bytes(b"\xff\n")
            output = StringIO()
            with patch.object(cli, "_find_tool_dir", return_value=urls.parent), \
                 patch.object(cli.subprocess, "Popen") as spawn, redirect_stdout(output):
                self.assertEqual(cli.run_cli(["--batch", str(urls)]), 1)
            spawn.assert_not_called()
            self.assertIn("读取", output.getvalue())
            self.assertIn("UTF-8", output.getvalue())


if __name__ == "__main__":
    unittest.main()
