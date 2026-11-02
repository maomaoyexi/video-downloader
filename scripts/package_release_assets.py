"""从当前生产依赖与源码插件生成隔离的候选发布资产，不覆盖已有文件。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = frozenset({
    "yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe", "deno.exe", "fantiadl.exe",
    "nicochannel.zip", "withny-dl-windows-amd64.exe",
})
ROOT_DIRS = frozenset({
    "BililiveRecorder", "Withny", "live-python", "fanbox-python",
    "yt-dlp-plugins", "bgutil-ytdlp-pot-provider",
})
PRIVATE_NAMES = frozenset({
    "cookies.txt", "cookies.json", "settings.ini", "presets.json", "urls.txt",
    "download_history.json", "twitcasting_passwords.xlsx", "twitcasting_passwords.csv",
    "credentials.yaml", "credentials.json", "config.yaml", "config.yml",
    "withny-live-config.yaml", "withny-live-config.yml", "withny-dl.json",
    ".npmrc", ".netrc", ".git-credentials", ".gitconfig", ".ds_store", "thumbs.db",
})
EXCLUDED_DIRS = frozenset({
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git",
    ".venv", "venv", ".cache", "logs", "download",
})
EXCLUDED_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".log", ".har", ".sqlite", ".sqlite3", ".db", ".part",
    ".ytdl", ".temp", ".tmp", ".pfx", ".p12", ".key",
})
PLUGIN_FILES = (
    "extractor/_rplay_auth.py", "extractor/_rplay_relay.py",
    "extractor/niconico_live.py", "extractor/rplay.py", "extractor/twitcasting.py",
    "postprocessor/niconico_live_mux.py", "postprocessor/twitcasting_parallel.py",
)
REQUIRED = frozenset(
    {"dependency/" + name for name in ROOT_FILES}
    | {
        "dependency/Withny/withny-dl.exe", "dependency/Withny/manifest.json",
        "dependency/BililiveRecorder/BililiveRecorder.Cli.exe",
        "dependency/BililiveRecorder/manifest.json",
        "dependency/BililiveRecorder/corresponding-source-v2.20.0.zip",
        "dependency/live-python/installed.json",
        "dependency/fanbox-python/curl_cffi/__init__.py",
        "dependency/bgutil-ytdlp-pot-provider/server/deno.json",
    }
    | {"dependency/yt-dlp-plugins/video_downloader/yt_dlp_plugins/" + name
       for name in PLUGIN_FILES}
)


def sha256(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def allowed(name):
    """校验归档路径，并仅允许生产目录中的非本地数据文件。"""
    path = PurePosixPath(name)
    if (not path.parts or path.is_absolute() or "\\" in name
            or any(part in {"", ".", ".."} or ":" in part for part in name.split("/"))
            or path.parts[0] != "dependency" or len(path.parts) < 2):
        raise ValueError("归档路径不安全")
    parts = tuple(part.casefold() for part in path.parts)
    if (set(parts) & EXCLUDED_DIRS or path.name.casefold() in PRIVATE_NAMES
            or path.name.casefold().startswith(".env")
            or path.suffix.casefold() in EXCLUDED_SUFFIXES):
        return False
    return ((len(path.parts) == 2 and
             (path.name in ROOT_FILES or path.name.endswith(".LICENSE")))
            or (len(path.parts) > 2 and path.parts[1] in ROOT_DIRS))


def validate_names(names):
    seen = set()
    for name in names:
        if not allowed(name):
            raise ValueError("归档包含应排除的路径")
        if name.casefold() in seen:
            raise ValueError("归档存在大小写重复路径")
        seen.add(name.casefold())


def collect_dependencies(root):
    root = Path(root).resolve()
    entries, folded = {}, {}
    excluded = 0
    for directory, prefix in (
        (root / "dependency", "dependency"),
        (root / "resource/yt-dlp-plugins", "dependency/yt-dlp-plugins"),
    ):
        if not directory.is_dir():
            raise FileNotFoundError("缺少生产依赖或源码插件目录")
        for file in sorted(directory.rglob("*")):
            if file.is_symlink() or (hasattr(file, "is_junction") and file.is_junction()):
                raise ValueError("发布输入不能包含链接或目录联接")
            if not file.is_file():
                continue
            if not file.resolve().is_relative_to(directory.resolve()):
                raise ValueError("发布输入超出允许目录")
            name = prefix + "/" + file.relative_to(directory).as_posix()
            if not allowed(name):
                excluded += 1
                continue
            previous = folded.setdefault(name.casefold(), name)
            if previous != name:
                raise ValueError("发布输入存在大小写重复路径")
            # 第二个输入专门覆盖同路径的旧插件，其他路径不做合并猜测。
            entries[name] = file
    validate_names(entries)
    missing = REQUIRED - entries.keys()
    if missing:
        raise ValueError("缺少必要发布依赖：" + ", ".join(sorted(missing)))
    return entries, excluded


def write_dependency_zip(target, entries):
    expected = {}
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as archive:
        for name, source in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            digest, size = hashlib.sha256(), 0
            with source.open("rb") as file, archive.open(info, "w", force_zip64=True) as output:
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            expected[name] = {"size": size, "sha256": digest.hexdigest()}
    with zipfile.ZipFile(target) as archive:
        validate_names(archive.namelist())
        if set(archive.namelist()) != set(expected) or archive.testzip() is not None:
            raise ValueError("依赖 ZIP 结构或 CRC 校验失败")
        for name, record in expected.items():
            with archive.open(name) as file:
                actual = hashlib.file_digest(file, "sha256").hexdigest()
            if actual != record["sha256"] or archive.getinfo(name).file_size != record["size"]:
                raise ValueError("依赖 ZIP 文件哈希校验失败：" + name)
    return expected


def package_release(root, version, exe, output):
    root, exe, output = Path(root).resolve(), Path(exe).resolve(), Path(output).resolve()
    version = str(version).removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("版本号必须为 major.minor.patch")
    if output == root or output.is_relative_to(root / "dependency"):
        raise ValueError("候选输出不能写入源码根或生产依赖目录")
    with exe.open("rb") as file:
        if file.read(2) != b"MZ":
            raise ValueError("主程序不是 Windows EXE")
    names = [f"video-downloader-v{version}-GUI.exe",
             f"video-downloader-v{version}-dependencies.zip",
             "release-manifest.json", "SHA256SUMS.txt"]
    if any((output / name).exists() for name in names):
        raise FileExistsError("候选产物已存在；先核验目标状态，不自动覆盖")
    entries, excluded = collect_dependencies(root)
    build = root / "build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-assets-", dir=build) as temporary:
        stage = Path(temporary)
        dependency_files = write_dependency_zip(stage / names[1], entries)
        shutil.copyfile(exe, stage / names[0])
        files = {name: {"size": (stage / name).stat().st_size,
                        "sha256": sha256(stage / name)} for name in names[:2]}
        if files[names[0]]["sha256"] != sha256(exe):
            raise ValueError("主程序复制校验失败")
        report = {
            "schema_version": 1, "version": "v" + version,
            "files": files, "dependency_file_count": len(dependency_files),
            "dependency_files": dependency_files, "excluded_file_count": excluded,
            "source_plugins_overlay": True,
            "checks": {"dependency_root_only": True, "case_unique": True,
                       "required_paths": True, "private_path_exclusion": True,
                       "zip_crc": True, "per_file_sha256": True},
        }
        (stage / names[2]).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        (stage / names[3]).write_text(
            "".join(sha256(stage / name) + "  " + name + "\n" for name in names[:3]),
            encoding="utf-8")
        output.mkdir(parents=True, exist_ok=True)
        created = []
        try:
            for name in names:
                target = output / name
                # 排他创建避免覆盖上一次候选或并发生成的同名文件。
                with target.open("xb") as destination:
                    created.append(target)
                    with (stage / name).open("rb") as source:
                        shutil.copyfileobj(source, destination, 1024 * 1024)
                if sha256(target) != sha256(stage / name):
                    raise ValueError("候选产物写入校验失败")
        except Exception:
            for target in reversed(created):
                target.unlink(missing_ok=True)
            raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = package_release(ROOT, args.version, args.exe, args.output)
    print(json.dumps({key: value for key, value in report.items()
                      if key != "dependency_files"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
