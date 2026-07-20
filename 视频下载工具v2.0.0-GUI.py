# -*- coding: utf-8 -*-
"""
多平台视频下载工具 v2.0.0 WebUI版
支持 YouTube / Bilibili / Twitch / Niconico / Fantia
使用内置HTTP服务器 + 浏览器界面，无需额外GUI库
自动更新通过 GitHub Releases 检查和分发
"""
import os
import sys
from pathlib import Path

from video_downloader.container import AppContainer
from video_downloader.core.constants import VERSION

if getattr(sys, 'frozen', False):
    TOOL_DIR = Path(sys.executable).parent
else:
    TOOL_DIR = Path(__file__).parent

EXE_SUFFIX = ".exe" if os.name == "nt" else ""

container = AppContainer(tool_dir=TOOL_DIR, exe_suffix=EXE_SUFFIX)
app = container.wire()


def main():
    """启动 WebUI 服务器并打开浏览器。"""
    print(f"多平台视频下载工具 {VERSION}", flush=True)
    print("正在启动 WebUI 服务器...", flush=True)
    app.main()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        from video_downloader.cli import run_cli
        sys.exit(run_cli(sys.argv[1:]))
    else:
        main()
