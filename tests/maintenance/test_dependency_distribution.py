"""依赖清单来自可验证基线，发布仅使用完整依赖包并保留路径安全。"""
import copy
import hashlib
import json
import zipfile

import pytest

from scripts.generate_dependency_catalog import (
    build_catalog, catalog_from_inputs, catalog_from_release_manifest, write_catalog,
)
from scripts.package_release_assets import package_release
from tests.maintenance.test_release_assets import fixture


def test_component_catalog_covers_full_package_and_readonly_runtimes(tmp_path):
    root, _, _ = fixture(tmp_path)
    catalog = catalog_from_inputs(root, "2.8.0")
    groups = {group["id"]: group for group in catalog["groups"]}
    assert len(groups) == 10
    assert set(catalog["files"]) == set().union(*(set(g["files"]) for g in groups.values()))
    assert groups["core"]["requires"] == []
    assert groups["source_live_runtime"]["source_only"] is True
    assert groups["source_fanbox_runtime"]["installable"] is False
    assert catalog["files"]["dependency/yt-dlp.exe"]["user_updatable"] is True
    assert "cookies.txt" not in "\n".join(catalog["files"])
    assert catalog["full_asset"] == {
        "name": "video-downloader-v2.8.0-dependencies.zip", "size": None, "sha256": None,
    }
    assert all("asset_name" not in group for group in groups.values())
    for group in groups.values():
        if group["installable"]:
            assert "dependency/tool.LICENSE" in group["files"]


def test_revision_is_content_based_not_version_or_dictionary_order(tmp_path):
    root, _, _ = fixture(tmp_path)
    first = catalog_from_inputs(root, "2.7.1")
    second = build_catalog(dict(reversed(list(first["files"].items()))), "2.8.0")
    assert first["revision"] == second["revision"]
    changed = copy.deepcopy(first["files"])
    changed["dependency/ffmpeg.exe"]["sha256"] = "a" * 64
    assert build_catalog(changed, "2.7.1")["revision"] != first["revision"]


@pytest.mark.parametrize("name", [
    "dependency/../settings.ini", "dependency/cookies.txt", "dependency/unknown.exe",
    "dependency/Withny/credentials.yaml", "C:/dependency/ffmpeg.exe",
    "dependency/Withny/CON.txt", "dependency/Withny/ambiguous.",
    "dependency/Withny/ambiguous ", "dependency/Withny/<bad>",
])
def test_catalog_rejects_private_unsafe_and_unlisted_files(name):
    with pytest.raises((ValueError, TypeError)):
        build_catalog({name: {"size": 1, "sha256": "a" * 64}}, "2.7.1")


@pytest.mark.parametrize("record", [{"size": True, "sha256": "a" * 64},
                                  {"size": -1, "sha256": "a" * 64},
                                  {"size": 1, "sha256": "not-a-digest"}])
def test_catalog_rejects_invalid_sizes_and_hashes(record):
    with pytest.raises(ValueError):
        build_catalog({"dependency/ffmpeg.exe": record}, "2.7.1")


def test_release_catalog_verifies_archive_and_preserves_published_files(tmp_path):
    root, exe, output = fixture(tmp_path)
    report = package_release(root, "2.7.1", exe, output)
    archive = output / "video-downloader-v2.7.1-dependencies.zip"
    before = archive.read_bytes()
    manifest = output / "release-manifest.json"
    catalog = catalog_from_release_manifest(manifest, archive)
    assert catalog["full_asset"]["sha256"] == report["files"][archive.name]["sha256"]
    assert catalog["files"]["dependency/ffmpeg.exe"]["sha256"] == hashlib.sha256(
        (root / "dependency/ffmpeg.exe").read_bytes()).hexdigest()
    assert archive.read_bytes() == before
    corrupt = tmp_path / archive.name
    corrupt.write_bytes(before + b"corrupt")
    with pytest.raises(ValueError, match="校验"):
        catalog_from_release_manifest(manifest, corrupt)


def test_release_manifest_cannot_supply_false_per_file_hashes(tmp_path):
    root, exe, output = fixture(tmp_path)
    report = package_release(root, "2.7.1", exe, output)
    report["dependency_files"]["dependency/ffmpeg.exe"]["sha256"] = "b" * 64
    bad = tmp_path / "bad-manifest.json"
    bad.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="文件校验"):
        catalog_from_release_manifest(bad, output / "video-downloader-v2.7.1-dependencies.zip")


def test_release_has_only_complete_dependency_zip_and_standard_manifest(tmp_path):
    root, exe, output = fixture(tmp_path)
    report = package_release(root, "2.8.0", exe, output)
    archive_name = "video-downloader-v2.8.0-dependencies.zip"
    assert {path.name for path in output.iterdir()} == {
        "video-downloader-v2.8.0-GUI.exe", archive_name,
        "release-manifest.json", "SHA256SUMS.txt",
    }
    assert set(report["files"]) == {"video-downloader-v2.8.0-GUI.exe", archive_name}
    assert "dependency_groups" not in report
    assert "dependency_catalog_revision" not in report
    with zipfile.ZipFile(output / archive_name) as archive:
        assert set(archive.namelist()) == set(report["dependency_files"])
        assert "dependency/ffmpeg.exe" in archive.namelist()
        assert "dependency/tool.LICENSE" in archive.namelist()
        assert "dependency/live-python/installed.json" in archive.namelist()
        assert "dependency/fanbox-python/curl_cffi/__init__.py" in archive.namelist()
        assert archive.read("dependency/yt-dlp-plugins/video_downloader/yt_dlp_plugins/extractor/rplay.py") == b"new-plugin"
    sums = (output / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(sums) == 3
    for name in ("video-downloader-v2.8.0-GUI.exe", archive_name, "release-manifest.json"):
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() + "  " + name in sums


def test_failed_complete_archive_stage_does_not_publish_partial_assets(tmp_path, monkeypatch):
    from scripts import package_release_assets as assets
    root, exe, output = fixture(tmp_path)
    original = assets.write_dependency_zip

    def fail_archive_after_write(target, entries):
        original(target, entries)
        raise OSError("synthetic write failure")

    monkeypatch.setattr(assets, "write_dependency_zip", fail_archive_after_write)
    with pytest.raises(OSError, match="synthetic"):
        package_release(root, "2.8.0", exe, output)
    assert not output.exists()


def test_catalog_write_requires_explicit_replace(tmp_path):
    path = tmp_path / "catalog.json"
    write_catalog({"fixture": 1}, path)
    with pytest.raises(FileExistsError):
        write_catalog({"fixture": 2}, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"fixture": 1}
    write_catalog({"fixture": 2}, path, replace=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"fixture": 2}
