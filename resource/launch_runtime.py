"""启动当前修复源码，或在不打开界面的情况下检查本地运行环境。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import sys
import traceback


def _check_runtime(*, live_only: bool) -> int:
    from video_downloader.core.constants import VERSION

    print("源码版本：" + VERSION, flush=True)
    print("Python 版本：" + sys.version.split()[0], flush=True)
    passed = True
    if not live_only:
        try:
            from video_downloader.platforms.fanbox.runtime import health

            status = health()
            print("FANBOX 运行依赖：" + json.dumps(status, ensure_ascii=False), flush=True)
            passed = bool(status.get("available"))
        except Exception:
            print("[检查失败] FANBOX 运行依赖无法加载。", file=sys.stderr, flush=True)
            traceback.print_exc()
            passed = False
    try:
        from video_downloader.live.danmaku.dependencies import self_check

        checks = self_check()
        print("直播与凭据自检：" + json.dumps(checks, ensure_ascii=False), flush=True)
        passed = passed and bool(checks) and all(checks.values())
    except Exception:
        print("[检查失败] 直播或凭据自检未完成。", file=sys.stderr, flush=True)
        traceback.print_exc()
        passed = False
    if not passed:
        print("请核对当前版本 dependency 中的运行依赖；Windows DPAPI 检查需在正常用户环境执行。",
              file=sys.stderr, flush=True)
    else:
        print("检查通过；未打开界面，也未读取真实登录凭据。", flush=True)
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    root = Path(__file__).resolve().parents[1]
    entry = root / "视频下载工具v2.8.1-GUI.py"
    if not entry.is_file():
        print("[启动失败] 当前修复目录缺少 视频下载工具v2.8.1-GUI.py。", file=sys.stderr, flush=True)
        return 2
    if sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32:
        print("[启动失败] 当前本地运行依赖需要 64 位 Python 3.12。", file=sys.stderr, flush=True)
        return 2
    os.chdir(root)
    paths = [root, root / "dependency" / "fanbox-python", root / "dependency" / "live-python"]
    sys.path[:0] = [str(path) for path in paths if path.is_dir()]
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--check"], ["--live-self-check"]):
        return _check_runtime(live_only=args == ["--live-self-check"])
    print("正在运行 v2.8.1 正式版源码；关闭网页后仍按程序原有规则收尾。", flush=True)
    sys.argv = [str(entry), *args]
    runpy.run_path(str(entry), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
