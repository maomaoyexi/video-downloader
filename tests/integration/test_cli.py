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


if __name__ == "__main__":
    unittest.main()
