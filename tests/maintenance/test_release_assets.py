"""候选发布资产仅包含可分发依赖，源码插件覆盖旧副本且不覆盖已有资产。"""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts.package_release_assets import (
    REQUIRED, allowed, package_release, validate_names,
)


def fixture(tmp_path):
    root = tmp_path / "source"
    for name in REQUIRED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("public:" + name).encode())
    plugin = "video_downloader/yt_dlp_plugins/extractor/rplay.py"
    source = root / "resource/yt-dlp-plugins" / plugin
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new-plugin")
    (root / "dependency/yt-dlp-plugins" / plugin).write_bytes(b"old-plugin")
    for relative in ["fanbox-python/cookies.txt", "live-python/__pycache__/cache.pyc",
                     "Withny/credentials.yaml", "bgutil-ytdlp-pot-provider/.env"]:
        path = root / "dependency" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-private-never-package")
    (root / "dependency/tool.LICENSE").write_text("public license")
    exe = tmp_path / "source.exe"
    exe.write_bytes(b"MZ-synthetic-executable")
    return root, exe, tmp_path / "candidate"


@pytest.mark.parametrize("name", [
    "/dependency/tool.exe", "../dependency/tool.exe", "dependency/../tool.exe",
    "C:/dependency/tool.exe", r"dependency\tool.exe",
])
def test_unsafe_archive_paths_are_rejected(name):
    with pytest.raises(ValueError, match="路径"):
        allowed(name)


def test_private_cache_and_unlisted_root_paths_are_excluded():
    for name in ["dependency/cookies.txt", "dependency/settings.ini",
                 "dependency/Withny/credentials.yaml", "dependency/live-python/a.db",
                 "dependency/fanbox-python/__pycache__/a.pyc",
                 "dependency/bgutil-ytdlp-pot-provider/.env.local",
                 "dependency/unlisted.exe"]:
        assert allowed(name) is False
    assert allowed("dependency/ffmpeg.exe")
    assert allowed("dependency/tool.LICENSE")
    assert allowed("dependency/Withny/manifest.json")


def test_case_insensitive_collisions_are_rejected():
    with pytest.raises(ValueError, match="大小写重复"):
        validate_names(["dependency/live-python/example.py",
                        "dependency/live-python/Example.py"])


def test_assets_have_safe_structure_overlay_and_verified_file_hashes(tmp_path):
    root, exe, output = fixture(tmp_path)
    report = package_release(root, "v2.7.1", exe, output)
    archive_path = output / "video-downloader-v2.7.1-dependencies.zip"
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert all(name.startswith("dependency/") for name in names)
        assert len(names) == len({name.casefold() for name in names})
        assert not any(token in "\n".join(names) for token in
                       ["cookies.txt", "credentials.yaml", "__pycache__", "/.env"])
        assert archive.read("dependency/yt-dlp-plugins/video_downloader/"
                            "yt_dlp_plugins/extractor/rplay.py") == b"new-plugin"
        assert archive.testzip() is None
        for name, record in report["dependency_files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == record["sha256"]
    manifest = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest == report
    assert report["excluded_file_count"] == 4
    assert (output / "video-downloader-v2.7.1-GUI.exe").read_bytes() == exe.read_bytes()
    assert set(p.name for p in output.iterdir()) == {
        "video-downloader-v2.7.1-GUI.exe", "video-downloader-v2.7.1-dependencies.zip",
        "release-manifest.json", "SHA256SUMS.txt",
    }


def test_existing_candidate_is_preserved_without_other_writes(tmp_path):
    root, exe, output = fixture(tmp_path)
    output.mkdir()
    target = output / "video-downloader-v2.7.1-GUI.exe"
    target.write_bytes(b"existing")
    with pytest.raises(FileExistsError, match="已存在"):
        package_release(root, "2.7.1", exe, output)
    assert target.read_bytes() == b"existing"
    assert list(output.iterdir()) == [target]


def test_required_dependency_and_exe_validation_fail_before_publishing(tmp_path):
    root, exe, output = fixture(tmp_path)
    (root / "dependency/ffmpeg.exe").unlink()
    with pytest.raises(ValueError, match="必要发布依赖"):
        package_release(root, "2.7.1", exe, output)
    assert not output.exists()
    exe.write_bytes(b"not-an-exe")
    with pytest.raises(ValueError, match="Windows EXE"):
        package_release(root, "2.7.1", exe, output)
    assert not output.exists()
