"""Install pinned portable live libraries/protocol assets without changing Python."""
from __future__ import annotations

import hashlib
import io
import json
import os
import argparse
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen


def replace_directory(source, target):
    # Windows antivirus/indexers can briefly deny renaming freshly extracted
    # directories. Keep retries bounded and preserve the previous runtime.
    for attempt in range(6):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.1 * (attempt + 1))


def install(root, *, upgrade=False):
    root = Path(root)
    lock = json.loads((root / "resource/dependencies/live-python.lock.json").read_text(encoding="utf-8"))
    (root / "dependency").mkdir(parents=True, exist_ok=True)
    target = root / "dependency/live-python"
    if target.exists():
        marker = target / "installed.json"
        if not upgrade and marker.is_file() and marker.read_text(encoding="utf-8") == json.dumps(lock, indent=2):
            return target
        if not upgrade:
            raise RuntimeError("dependency/live-python already exists with different contents; use --upgrade")
        try:
            installed = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            installed = None
        if not isinstance(installed, dict) or not installed.get("packages") or target.is_symlink() or target.is_junction():
            raise RuntimeError("Refusing to replace an unmanaged runtime")
    with tempfile.TemporaryDirectory(prefix="live-install-", dir=root / "dependency") as name:
        stage = Path(name) / "runtime"
        stage.mkdir()
        for package in lock["packages"]:
            url = package["url"]
            if urlsplit(url).hostname != "files.pythonhosted.org" or urlsplit(url).scheme != "https":
                raise ValueError("Only pinned official PyPI wheels are accepted")
            with urlopen(url, timeout=30) as response:
                data = response.read(4 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != package["sha256"]:
                raise ValueError("Wheel checksum mismatch: " + package["name"])
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    if not (stage / member.filename).resolve().is_relative_to(stage.resolve()):
                        raise ValueError("Invalid wheel path")
                archive.extractall(stage)
        for asset in lock.get("assets", []):
            destination = (stage / asset["path"]).resolve()
            if not destination.is_relative_to(stage.resolve()):
                raise ValueError("Invalid protocol asset path")
            url = asset["url"]
            if urlsplit(url).scheme != "https" or urlsplit(url).hostname != "raw.githubusercontent.com":
                raise ValueError("Only pinned official source assets are accepted")
            with urlopen(url, timeout=30) as response:
                data = response.read(4 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != asset["sha256"]:
                raise ValueError("Protocol checksum mismatch")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        if lock.get("assets"):
            # Protocol-only subset: deliberately do not import NDGRClient's
            # unrelated SDK dependencies from its original package initializer.
            for directory in [stage / "ndgr_client", *(stage / "ndgr_client").rglob("*")]:
                if directory.is_dir():
                    (directory / "__init__.py").touch(exist_ok=True)
        (stage / "installed.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
        backup = Path(name) / "previous-runtime"
        if target.exists():
            replace_directory(target, backup)
        try:
            replace_directory(stage, target)
        except OSError:
            if backup.exists():
                replace_directory(backup, target)
            raise
        if backup.exists():
            if not backup.resolve().is_relative_to((root / "dependency").resolve()):
                raise ValueError("Unsafe managed runtime cleanup")
            shutil.rmtree(backup)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upgrade", action="store_true", help="Reinstall or upgrade a previously managed runtime")
    print(install(Path(__file__).resolve().parents[1], upgrade=parser.parse_args().upgrade))
