import tempfile
import unittest
from pathlib import Path

from video_downloader.core.constants import DEFAULT_CONFIG
from video_downloader.core.command import build_ytdlp_cmd


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


if __name__ == "__main__":
    unittest.main()
