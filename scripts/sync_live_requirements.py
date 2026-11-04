"""从直播 JSON 锁生成手动 pip 清单；--check 仅检查是否同步。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]


def sync(root=ROOT, *, check=False):
    """保留包顺序与固定哈希，不将协议源码素材当成 pip 依赖。"""
    root = Path(root)
    lock = json.loads((root / "resource/dependencies/live-python.lock.json").read_text(encoding="utf-8"))
    lines = []
    for package in lock["packages"]:
        name, version, digest = (package[key] for key in ("name", "version", "sha256"))
        if not (isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
                and isinstance(version, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version)
                and isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise ValueError("直播依赖锁中的包名、固定版本或 SHA-256 无效")
        lines.append(f"{name}=={version} --hash=sha256:{digest}\n")
    expected = "".join(lines)
    target = root / "requirements-live.txt"
    matches = target.is_file() and target.read_text(encoding="utf-8") == expected
    if check:
        return matches
    if not matches:
        target.write_text(expected, encoding="utf-8", newline="\n")
    return True


def main(argv=None, *, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只校验清单，不创建或修改文件")
    args = parser.parse_args(argv)
    try:
        if not sync(root, check=args.check):
            print("requirements-live.txt 与直播 JSON 锁不同步；请运行 python scripts/sync_live_requirements.py", file=sys.stderr)
            return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("直播依赖清单处理失败：" + str(error), file=sys.stderr)
        return 1
    print("直播依赖清单与 JSON 锁一致" if args.check else "直播依赖清单已同步")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
