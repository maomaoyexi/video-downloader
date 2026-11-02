# -*- coding: utf-8 -*-
"""
多平台视频下载工具 v2.7.1 WebUI版
支持 YouTube / Bilibili / Twitch / Niconico / NicoChannel / Fantia / TwitCasting / Twitter / Rplay / FANBOX
提供已接入平台的直播录制、任务队列、FANBOX 内容归档与 Withny 已授权历史存档 HAR 保存功能
各平台的列表、认证、续传与可访问内容范围不同，下载以账号已有权限为准
使用内置HTTP服务器 + 浏览器界面，无需额外GUI库
自动更新通过 GitHub Releases 检查和分发
"""
import os
import sys
from pathlib import Path

if __name__ == "__main__" and sys.argv[1:] == ["--live-self-test"]:
    import json
    from video_downloader.live.danmaku.dependencies import self_check
    checks = self_check()
    print(json.dumps(checks), flush=True)
    sys.exit(0 if all(checks.values()) else 1)

if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--live-comment-worker":
    from video_downloader.live.danmaku.worker import main as comment_worker
    sys.exit(comment_worker(sys.argv[2]))

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
