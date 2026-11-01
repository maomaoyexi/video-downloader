"""Explicit source/frozen dependency boundary; install only hash-locked wheels."""
from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys

from .errors import FanboxError


def library(name):
    if not getattr(sys, "frozen", False):
        directory = Path(__file__).resolve().parents[3] / "dependency" / "fanbox-python"
        try:
            if directory.is_dir() and str(directory) not in sys.path:
                sys.path.insert(0, str(directory))
        except OSError:
            pass
    try:
        return importlib.import_module(name)
    except ImportError:
        raise FanboxError("dependency_missing",
            "缺少 FANBOX 依赖，请运行 python -m video_downloader.platforms.fanbox.runtime --install") from None


def health():
    try:
        lib = library("curl_cffi")
        requests = library("curl_cffi.requests")
        with requests.Session(impersonate="chrome", trust_env=False, verify=True):
            pass
        return {"available": True, "version": lib.__version__}
    except (FanboxError, OSError):
        return {"available": False}


def install():
    if getattr(sys, "frozen", False):
        raise FanboxError("dependency_missing", "请使用包含 FANBOX 运行依赖的发行版")
    root = Path(__file__).resolve().parents[3]
    target = root / "dependency" / "fanbox-python"
    lock = root / "resource" / "dependencies" / "fanbox-runtime.txt"
    # pip performs version/platform selection and verifies every downloaded wheel.
    subprocess.run([sys.executable, "-m", "pip", "install", "--require-hashes", "--only-binary=:all:",
                    "--no-compile", "--no-deps", "--upgrade", "--target", str(target),
                    "--index-url", "https://pypi.org/simple", "-r", str(lock)], check=True)


if __name__ == "__main__":
    import json
    if sys.argv[1:] == ["--install"]:
        install()
    print(json.dumps(health()))
