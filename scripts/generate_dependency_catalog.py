"""从可信发布清单或正式构建输入生成依赖目录；不下载、安装或修改依赖。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from scripts import package_release_assets as release_assets


GROUP_DEFINITIONS = (
    ("core", "基础视频工具", "yt-dlp、FFmpeg 与 ffprobe，供视频下载及媒体处理共享", False),
    ("youtube", "YouTube 增强", "Deno 与 PO Token Provider", False),
    ("bilibili_live", "Bilibili 直播", "录播姬及对应许可与来源材料", False),
    ("fantia", "Fantia 工具", "Fantia 下载工具", False),
    ("withny", "Withny 工具", "历史存档与受管直播组件", False),
    ("nicochannel", "NicoChannel 插件", "NicoChannel 下载插件", False),
    ("rplay", "Rplay 插件", "Rplay 提取器及授权、转播适配", False),
    ("live_plugins", "直播平台插件", "Niconico 与 TwitCasting 提取及后处理插件", False),
    ("source_live_runtime", "直播源码运行库", "EXE 内置；源码环境按 README 安装，不在运行中替换", True),
    ("source_fanbox_runtime", "FANBOX 源码运行库", "EXE 内置；源码环境按 README 安装，不在运行中替换", True),
)
_RPLAY = frozenset({"rplay.py", "_rplay_auth.py", "_rplay_relay.py"})


def normalized_version(value):
    version = str(value).removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("版本号必须为 major.minor.patch")
    return version


def _primary_group(name):
    relative = name.removeprefix("dependency/")
    if relative in {"yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"}:
        return "core"
    if (relative == "deno.exe" or relative.startswith("bgutil-ytdlp-pot-provider/")
            or relative == "yt-dlp-plugins/bgutil-ytdlp-pot-provider.zip"):
        return "youtube"
    if relative.startswith("BililiveRecorder/") or relative == "BililiveRecorder.LICENSE":
        return "bilibili_live"
    if relative == "fantiadl.exe":
        return "fantia"
    if (relative.startswith("Withny/")
            or relative in {"withny-dl-windows-amd64.exe", "withny-dl.LICENSE"}):
        return "withny"
    if relative == "nicochannel.zip":
        return "nicochannel"
    plugin_prefix = "yt-dlp-plugins/video_downloader/yt_dlp_plugins/"
    if relative.startswith(plugin_prefix):
        return "rplay" if Path(relative).name in _RPLAY else "live_plugins"
    if relative.startswith("fanbox-python/") or relative.startswith("fanbox-") and relative.endswith(".LICENSE"):
        return "source_fanbox_runtime"
    if relative.startswith("live-python/") or relative.endswith(".LICENSE"):
        return "source_live_runtime"
    raise ValueError("依赖文件未定义分组：" + name)


def _records(values):
    if not isinstance(values, dict) or not values:
        raise ValueError("依赖文件清单必须是非空对象")
    if len(values) > 100000:
        raise ValueError("依赖文件清单超过数量限制")
    release_assets.validate_names(values)
    result = {}
    for name, value in sorted(values.items()):
        for part in name.split("/"):
            reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                        *(f"LPT{i}" for i in range(1, 10))}
            if (part.endswith((".", " ")) or part.split(".")[0].upper() in reserved
                    or any(ord(char) < 32 or char in '<>"|?*' for char in part)):
                raise ValueError("依赖路径不能包含 Windows 保留名称或字符")
        if not isinstance(value, dict):
            raise ValueError("依赖文件记录必须是对象")
        size, digest = value.get("size"), value.get("sha256")
        if type(size) is not int or size < 0 or size > 4 * 1024**3:
            raise ValueError("依赖文件大小无效")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("依赖文件 SHA-256 无效")
        result[name] = {"size": size, "sha256": digest.lower()}
        if name == "dependency/yt-dlp.exe":
            result[name]["user_updatable"] = True
    if sum(record["size"] for record in result.values()) > 4 * 1024**3:
        raise ValueError("依赖文件总大小超过限制")
    return result


def build_catalog(values, version, full_asset=None):
    """公开生成接口：文件记录是正确基线，组件归类与 revision 确定性生成。"""
    version = normalized_version(version)
    records = _records(values)
    license_files = [name for name in records if len(name.split("/")) == 2 and name.endswith(".LICENSE")]
    members = {definition[0]: [] for definition in GROUP_DEFINITIONS}
    for name in records:
        members[_primary_group(name)].append(name)
    groups = []
    for group_id, name, description, source_only in GROUP_DEFINITIONS:
        files = set(members[group_id])
        if not source_only:
            files.update(license_files)
        groups.append({
            "id": group_id, "name": name, "description": description,
            "requires": [] if group_id == "core" or source_only else ["core"],
            "files": sorted(files), "source_only": source_only,
            "installable": not source_only,
        })
    asset = {"name": f"video-downloader-v{version}-dependencies.zip", "size": None, "sha256": None}
    if full_asset is not None:
        if not isinstance(full_asset, dict) or full_asset.get("name", asset["name"]) != asset["name"]:
            raise ValueError("完整依赖包名称不匹配")
        size, digest = full_asset.get("size"), full_asset.get("sha256")
        if type(size) is not int or size <= 0:
            raise ValueError("完整依赖包大小无效")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("完整依赖包 SHA-256 无效")
        asset.update(size=size, sha256=digest.lower())
    revision_groups = [{key: group[key] for key in ("id", "requires", "files", "source_only", "installable")}
                       for group in groups]
    revision = hashlib.sha256(json.dumps(
        {"files": records, "groups": revision_groups}, sort_keys=True,
        ensure_ascii=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"schema_version": 1, "version": version, "release_tag": "v" + version,
            "revision": revision, "full_asset": asset, "groups": groups, "files": records}


def catalog_from_inputs(root, version):
    """仅用于正式构建输入；不把应用当前安装状态当作可信运行基线。"""
    entries, _ = release_assets.collect_dependencies(root)
    records = {name: {"size": path.stat().st_size, "sha256": release_assets.sha256(path)}
               for name, path in sorted(entries.items())}
    return build_catalog(records, version)


def catalog_from_release_manifest(manifest_path, archive_path):
    """校验完整包字节与逐文件记录，再复用已发布版本的依赖基线。"""
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("发布清单必须是对象")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("不支持的发布清单版本")
    version = normalized_version(data.get("version", ""))
    records = _records(data.get("dependency_files"))
    if type(data.get("dependency_file_count")) is not int or data["dependency_file_count"] != len(records):
        raise ValueError("发布清单文件数量不匹配")
    missing = release_assets.REQUIRED - records.keys()
    if missing:
        raise ValueError("发布清单缺少必要依赖：" + ", ".join(sorted(missing)))
    name = f"video-downloader-v{version}-dependencies.zip"
    assets = data.get("files")
    if not isinstance(assets, dict):
        raise ValueError("发布资产清单必须是对象")
    info = assets.get(name)
    if not isinstance(info, dict):
        raise ValueError("发布清单缺少完整依赖包元数据")
    archive_path = Path(archive_path)
    if (archive_path.name != name or archive_path.stat().st_size != info.get("size")
            or release_assets.sha256(archive_path) != info.get("sha256")):
        raise ValueError("完整依赖包校验失败")
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        release_assets.validate_names([item.filename for item in infos])
        if set(archive.namelist()) != set(records):
            raise ValueError("归档与发布文件清单不一致")
        for item in infos:
            mode = item.external_attr >> 16
            if item.is_dir() or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError("归档不能含目录或链接")
            record = records[item.filename]
            if item.file_size != record["size"]:
                raise ValueError("依赖文件校验失败：" + item.filename)
            with archive.open(item) as file:
                digest = hashlib.file_digest(file, "sha256").hexdigest()
            if digest != record["sha256"]:
                raise ValueError("依赖文件校验失败：" + item.filename)
    return build_catalog(records, version, {"name": name, **info})


def write_catalog(catalog, output, *, replace=False):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if not replace:
        with output.open("xb") as file:
            file.write(data)
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=output.name + ".", suffix=".tmp", dir=output.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="正式构建输入根目录")
    parser.add_argument("--version", help="构建版本；不指定时读取源码版本")
    parser.add_argument("--release-manifest", type=Path, help="已核验的历史发布清单")
    parser.add_argument("--archive", type=Path, help="对应已发布完整依赖 ZIP")
    parser.add_argument("--output", type=Path, default=ROOT / "resource/dependencies/dependency-catalog.json")
    parser.add_argument("--replace", action="store_true", help="明确替换已有生成清单")
    args = parser.parse_args(argv)
    if bool(args.release_manifest) != bool(args.archive):
        parser.error("--release-manifest 与 --archive 必须同时指定")
    if args.release_manifest:
        catalog = catalog_from_release_manifest(args.release_manifest, args.archive)
        if args.version and normalized_version(args.version) != catalog["version"]:
            parser.error("不能将历史发布清单冒充其他版本")
    else:
        if args.version:
            version = args.version
        else:
            sys.path.insert(0, str(args.root))
            from video_downloader.core.constants import VERSION_NUM
            from video_downloader.core.platform import version_num_to_str
            version = version_num_to_str(VERSION_NUM)
        catalog = catalog_from_inputs(args.root, version)
    write_catalog(catalog, args.output, replace=args.replace)
    print(json.dumps({"version": catalog["version"], "revision": catalog["revision"],
                      "file_count": len(catalog["files"]), "group_count": len(catalog["groups"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
