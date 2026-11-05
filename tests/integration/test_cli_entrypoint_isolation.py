"""命令行入口应在临时目录中运行，不初始化 WebUI 或触碰运行数据。"""
import subprocess
import sys

import pytest

from tests.helpers import PROJECT_ROOT
from video_downloader.core.constants import VERSION


ENTRY = PROJECT_ROOT / f"视频下载工具{VERSION.split()[0]}-GUI.py"
CLI_RUNNER = """
import importlib.abc
import runpy
import sys
from pathlib import Path

class RejectWebUI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'video_downloader.container':
            raise AssertionError('CLI must not initialize the WebUI container')

entry = Path(sys.argv[1])
sys.path.insert(0, str(entry.parent))
sys.meta_path.insert(0, RejectWebUI())
sys.argv = [str(entry), *sys.argv[2:]]
runpy.run_path(str(entry), run_name='__main__')
"""


@pytest.mark.parametrize(("arguments", "exit_code", "message"), [
    (["--help"], 0, "命令行模式"),
    (["-h"], 0, "命令行模式"),
    (["--fanbox-scan", "--help"], 0, "--anonymous"),
    (["--fanbox-download", "--help"], 0, "--anonymous"),
    (["--unknown-option"], 1, "未知参数"),
])
def test_cli_does_not_initialize_webui_or_create_runtime_files(tmp_path, arguments, exit_code, message):
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8", "-c", CLI_RUNNER, str(ENTRY), *arguments],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == exit_code, result.stderr
    assert message in result.stdout
    assert not list(tmp_path.iterdir())
