"""依赖管理公开入口的隔离文件、网络与事务回归。"""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import threading
import time
import zipfile

import pytest

from video_downloader.services.dependency_manager import DependencyManager
from video_downloader.services.download_manager import DownloadManager
from video_downloader.services import dependency_manager as dependency_module


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive(files):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as zipped:
        for name, data in files.items():
            zipped.writestr(name, data)
    return target.getvalue()


FILES = {
    "dependency/yt-dlp.exe": b"trusted yt-dlp",
    "dependency/ffmpeg.exe": b"trusted ffmpeg",
    "dependency/deno.exe": b"trusted deno",
    "dependency/fantiadl.exe": b"trusted fantia",
}
_UNSET = object()


def fixture_catalog():
    full = archive(FILES)
    groups = []
    for group_id, paths, requires in (
        ("core", ["dependency/yt-dlp.exe", "dependency/ffmpeg.exe"], []),
        ("youtube", ["dependency/deno.exe"], ["core"]),
        ("fantia", ["dependency/fantiadl.exe"], ["core"]),
    ):
        groups.append({"id": group_id, "name": group_id, "description": "fixture",
                       "requires": requires, "files": paths, "source_only": False,
                       "installable": True,
                       "asset_name": f"video-downloader-v2.7.1-dependencies-{group_id}.zip"})
    return {"schema_version": 1, "version": "2.7.1", "release_tag": "v2.7.1",
            "revision": "b" * 64, "groups": groups,
            "full_asset": {"name": "video-downloader-v2.7.1-dependencies.zip",
                           "size": len(full), "sha256": digest(full)},
            "files": {name: {"size": len(data), "sha256": digest(data)} for name, data in FILES.items()}}, full


def wait(service):
    deadline = time.monotonic() + 8
    while service.snapshot()["running"] and time.monotonic() < deadline:
        time.sleep(.01)
    state = service.snapshot()
    assert not state["running"], state
    return state


def group(state, name):
    return next(item for item in state["groups"] if item["id"] == name)


@pytest.fixture
def factory(tmp_path):
    services = []

    def create(*, catalog=_UNSET, payload=None, frozen=False, **kwargs):
        data, default_payload = fixture_catalog()
        payload = default_payload if payload is None else payload
        if catalog is not _UNSET:
            data = catalog
        file = tmp_path / f"catalog-{len(services)}.json"
        file.write_text(json.dumps(data), encoding="utf-8")
        calls = []

        def release(url):
            calls.append(("release", url))
            return {"assets": [{"name": "video-downloader-v2.7.1-dependencies.zip",
                                "size": len(payload), "digest": "sha256:" + digest(payload)}]}

        def download(url, destination, **options):
            calls.append(("download", url))
            Path(destination).write_bytes(payload)
            options["progress"](len(payload), len(payload))

        manager = kwargs.pop("download_manager", DownloadManager())
        service = DependencyManager(tmp_path / "app", catalog_path=file, frozen=frozen,
                                    download_manager=manager,
                                    fetch_release=kwargs.pop("fetch_release", release),
                                    download_asset=kwargs.pop("download_asset", download), **kwargs)
        services.append(service)
        return service, manager, calls

    yield create
    for service in services:
        service.cancel()
        wait(service)


def test_snapshot_is_local_and_isolated_copy(factory, tmp_path):
    service, _, calls = factory()
    state = service.snapshot()
    assert state["available"] and not state["running"]
    assert not (tmp_path / "app").exists()
    assert calls == []
    state["groups"][0]["state"] = "invented"
    assert group(service.snapshot(), "core")["state"] == "unchecked"


def test_summary_snapshot_preserves_status_counts_and_missing_paths(factory, tmp_path):
    service, _, calls = factory()
    target = tmp_path / "app/dependency/yt-dlp.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(FILES["dependency/yt-dlp.exe"])
    assert service.check()["ok"]
    complete = wait(service)

    summary = service.snapshot(include_groups=False)
    assert "groups" not in summary
    assert summary == {key: value for key, value in complete.items() if key != "groups"}
    assert summary["existing_count"] == 1 and summary["missing_count"] == 3
    assert summary["missing_files"] == ["dependency/deno.exe", "dependency/fantiadl.exe", "dependency/ffmpeg.exe"]
    summary["missing_files"].clear()
    assert len(service.snapshot(include_groups=False)["missing_files"]) == 3
    assert group(service.snapshot(), "core")["state"] == "missing"
    assert calls == []


def test_summary_snapshot_keeps_catalog_errors(factory):
    service, _, calls = factory(catalog=None)
    summary = service.snapshot(include_groups=False)
    assert not summary["available"] and summary["phase"] == "failed"
    assert summary["code"] == "invalid_catalog" and summary["error"]
    assert "groups" not in summary and summary["file_count"] == 0
    assert calls == []


def test_presence_checks_do_not_emit_unused_dependency_sse(factory):
    events = []
    service, _, _ = factory(emit_event=lambda event, data: events.append((event, data)))
    assert service.check()["ok"]
    assert wait(service)["phase"] == "completed"
    assert events == []


@pytest.mark.parametrize("bad", [None, [], "invalid", 1])
def test_invalid_catalog_does_not_break_program_start(factory, bad):
    service, _, calls = factory(catalog=bad)
    assert service.snapshot()["available"] is False
    assert service.check(["core"]).get("error")
    assert service.update()["code"] == "invalid_catalog"
    assert calls == []


@pytest.mark.parametrize("field", ["name", "description", "asset_name"])
def test_nested_ui_metadata_is_rejected_without_creating_app_directories(factory, tmp_path, field):
    catalog, _ = fixture_catalog()
    catalog["groups"][0][field] = [["invalid text"]]
    service, _, calls = factory(catalog=catalog)
    state = service.snapshot()
    assert not state["available"] and state["code"] == "invalid_catalog"
    assert state["groups"] == []
    assert not (tmp_path / "app").exists()
    assert service.install(["core"])["code"] == "invalid_catalog"
    assert calls == []


def test_deeply_nested_catalog_metadata_does_not_break_startup_or_snapshot(tmp_path):
    catalog, _ = fixture_catalog()
    raw = json.dumps(catalog).replace('"description": "fixture"',
                                      '"description": ' + '[' * 1500 + '"fixture"' + ']' * 1500, 1)
    path = tmp_path / "catalog.json"
    path.write_text(raw, encoding="utf-8")
    service = DependencyManager(tmp_path / "app", catalog_path=path)
    assert not service.snapshot()["available"]
    assert not (tmp_path / "app").exists()
    assert service.close()


def test_unknown_nested_group_metadata_is_not_copied_into_public_snapshot(factory):
    catalog, _ = fixture_catalog()
    catalog["groups"][0]["future_metadata"] = {"nested": ["not a public field"]}
    service, _, calls = factory(catalog=catalog)
    assert "future_metadata" not in group(service.snapshot(), "core")
    assert calls == []


@pytest.mark.parametrize("name", ["../settings.ini", "dependency/../cookies.txt", "dependency/CON.exe",
                                  "dependency/yt-dlp.exe:stream", "dependency\\yt-dlp.exe",
                                  "dependency/settings.ini", "dependency/sub/../../outside.exe"])
def test_catalog_rejects_unsafe_or_private_target(factory, name):
    catalog, _ = fixture_catalog()
    catalog["files"][name] = {"size": 1, "sha256": "a" * 64}
    service, _, calls = factory(catalog=catalog)
    assert service.snapshot()["available"] is False
    assert service.install(["core"]).get("error")
    assert calls == []


def test_presence_check_includes_all_managed_files_and_preserves_custom_content(factory, tmp_path, monkeypatch):
    service, _, calls = factory()
    root = tmp_path / "app"
    for name, data in FILES.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    custom = root / "dependency/yt-dlp.exe"
    custom.write_bytes(b"user separately updated yt-dlp")
    def unexpected_digest(*args):
        raise AssertionError("presence check must never hash files")
    monkeypatch.setattr(dependency_module, "_digest", unexpected_digest)
    assert service.check()["ok"]
    state = wait(service)
    assert group(state, "core")["state"] == "present"
    assert group(state, "youtube")["state"] == "present"
    assert group(state, "fantia")["state"] == "present"
    assert state["file_count"] == state["existing_count"] == 4
    assert state["missing_count"] == state["error_count"] == state["unchecked_count"] == 0
    assert custom.read_bytes() == b"user separately updated yt-dlp"
    assert calls == []


def test_install_extracts_only_selected_groups_and_downloads_full_fallback_once(factory, tmp_path):
    service, manager, calls = factory()
    root = tmp_path / "app"
    root.mkdir()
    private = root / "settings.ini"
    private.write_bytes(b"preserve personal settings")
    assert service.install(["youtube"])["ok"]
    state = wait(service)
    assert state["phase"] == "completed", state
    for name in ("yt-dlp.exe", "ffmpeg.exe", "deno.exe"):
        assert (root / "dependency" / name).read_bytes() == FILES["dependency/" + name]
    assert not (root / "dependency/fantiadl.exe").exists()
    assert private.read_bytes() == b"preserve personal settings"
    assert len([call for call in calls if call[0] == "download"]) == 1
    assert state["download_mode"] == "full"
    assert manager.snapshot()["accepting"]
    assert service.check(["core"])["ok"]
    state = wait(service)
    assert state["download_mode"] is None and state["download_bytes"] is None


def test_changed_files_require_explicit_confirmation_before_network_or_replace(factory, tmp_path):
    service, manager, calls = factory()
    target = tmp_path / "app/dependency/yt-dlp.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"custom binary")
    assert service.install(["core"])["ok"]
    state = wait(service)
    assert state["code"] == "changed_files"
    assert "dependency/yt-dlp.exe" in state["changed_files"]
    assert target.read_bytes() == b"custom binary"
    assert calls == [] and manager.snapshot()["accepting"]
    assert service.install(["core"], replace_changed=True)["ok"]
    assert wait(service)["phase"] == "completed"
    assert target.read_bytes() == FILES["dependency/yt-dlp.exe"]


def test_running_tasks_reject_install_and_leave_download_manager_accepting(factory):
    service, manager, calls = factory(has_active_downloads=lambda: True)
    assert service.install(["core"]).get("error")
    assert service.update()["code"] == "active_tasks"
    assert calls == [] and manager.snapshot()["accepting"]


def test_empty_selection_and_unknown_groups_never_mean_install_everything(factory):
    service, _, calls = factory()
    for selection in ([], ["unknown"], ["../core"], "core", [1], ["core", "core"]):
        assert service.install(selection).get("error")
    assert calls == []


def test_cancelling_download_restores_maintenance_and_does_not_install(factory, tmp_path):
    entered = threading.Event()

    def downloading(url, destination, *, cancel_event, **kwargs):
        entered.set()
        cancel_event.wait(5)
        raise OSError("cancelled fixture")

    service, manager, _ = factory(download_asset=downloading)
    assert service.install(["youtube"])["ok"]
    assert entered.wait(3)
    assert not manager.snapshot()["accepting"]
    assert service.cancel()["ok"]
    state = wait(service)
    assert state["phase"] == "cancelled"
    assert manager.snapshot()["accepting"]
    assert not (tmp_path / "app/dependency/yt-dlp.exe").exists()


def test_user_updated_ytdlp_is_preserved_while_installing_shared_and_provider_files(factory, tmp_path):
    catalog, _ = fixture_catalog()
    catalog["files"]["dependency/yt-dlp.exe"]["user_updatable"] = True
    service, _, calls = factory(catalog=catalog)
    target = tmp_path / "app/dependency/yt-dlp.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user's newer yt-dlp")
    assert service.install(["youtube"])["ok"]
    state = wait(service)
    assert state["phase"] == "completed", state
    assert state["preserved_files"] == ["dependency/yt-dlp.exe"]
    assert "兼容性尚未验证" in state["message"]
    assert target.read_bytes() == b"user's newer yt-dlp"
    assert (target.parent / "ffmpeg.exe").read_bytes() == FILES["dependency/ffmpeg.exe"]
    assert (target.parent / "deno.exe").read_bytes() == FILES["dependency/deno.exe"]
    core = group(state, "core")
    assert core["state"] == "changed" and core["requires_confirmation"] is False
    assert next(item for item in core["details"] if item["path"] == "dependency/yt-dlp.exe")["user_updatable"]
    assert len([call for call in calls if call[0] == "download"]) == 1
    assert service.install(["youtube"], replace_changed=True)["ok"]
    assert wait(service)["phase"] == "completed"
    assert target.read_bytes() == FILES["dependency/yt-dlp.exe"]


def test_non_updatable_change_requires_confirmation_even_with_preserved_ytdlp(factory, tmp_path):
    catalog, _ = fixture_catalog()
    catalog["files"]["dependency/yt-dlp.exe"]["user_updatable"] = True
    service, _, calls = factory(catalog=catalog)
    root = tmp_path / "app/dependency"
    root.mkdir(parents=True)
    (root / "yt-dlp.exe").write_bytes(b"custom yt-dlp")
    (root / "fantiadl.exe").write_bytes(b"custom fantia")
    assert service.install(["fantia"])["ok"]
    state = wait(service)
    assert state["code"] == "changed_files"
    assert group(state, "core")["requires_confirmation"] is False
    assert group(state, "fantia")["requires_confirmation"] is True
    assert calls == []


def test_update_uses_all_managed_external_files_and_preserves_user_ytdlp_and_readonly_runtime(factory, tmp_path):
    catalog, _ = fixture_catalog()
    catalog["files"]["dependency/yt-dlp.exe"]["user_updatable"] = True
    runtime = "dependency/live-python/runtime.pyd"
    catalog["files"][runtime] = {"size": 7, "sha256": digest(b"runtime")}
    catalog["groups"].append({"id": "source_runtime", "name": "源码运行库", "description": "只读",
                              "requires": [], "files": [runtime], "source_only": True, "installable": False})
    payload = archive(FILES | {runtime: b"runtime"})
    catalog["full_asset"].update(size=len(payload), sha256=digest(payload))
    for definition in catalog["groups"]:
        definition.pop("asset_name", None)
    service, _, calls = factory(catalog=catalog, payload=payload)
    root = tmp_path / "app/dependency"
    root.mkdir(parents=True)
    (root / "yt-dlp.exe").write_bytes(b"newer yt-dlp from user")
    (root / "ffmpeg.exe").write_bytes(b"old ffmpeg to update")
    assert service.update()["ok"]
    state = wait(service)
    assert state["phase"] == "completed" and state["action"] == "install", state
    assert state["selected_groups"] == ["core", "youtube", "fantia"]
    assert state["preserved_files"] == ["dependency/yt-dlp.exe"]
    assert (root / "yt-dlp.exe").read_bytes() == b"newer yt-dlp from user"
    for name in ("ffmpeg.exe", "deno.exe", "fantiadl.exe"):
        assert (root / name).read_bytes() == FILES["dependency/" + name]
    assert not (tmp_path / "app" / runtime).exists()
    assert state["file_count"] == state["existing_count"] == 4
    assert state["missing_count"] == state["error_count"] == 0
    assert len([call for call in calls if call[0] == "download"]) == 1
    backups = list((tmp_path / "app/download/.dependency-manager/operations").glob("*/backup/dependency/ffmpeg.exe"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"old ffmpeg to update"
    assert all("asset_name" not in item for item in state["groups"])


def test_presence_totals_cover_errors_and_truncate_missing_paths(factory, tmp_path):
    catalog, _ = fixture_catalog()
    paths = [f"dependency/Withny/part-{index:02}.dll" for index in range(56)]
    catalog["files"].update({name: {"size": 1, "sha256": digest(b"a")} for name in paths})
    catalog["groups"][0]["files"] = paths
    service, _, calls = factory(catalog=catalog)
    initial = service.snapshot()
    assert initial["file_count"] == initial["unchecked_count"] == 58
    directory = tmp_path / "app" / paths[0]
    directory.mkdir(parents=True)
    assert service.check()["ok"]
    state = wait(service)
    assert state["error_count"] == 1 and state["missing_count"] == 57
    assert state["existing_count"] == state["unchecked_count"] == 0
    assert len(state["missing_files"]) == 50 and state["missing_truncated"]
    assert paths[0] not in state["missing_files"] and calls == []


def test_only_full_package_is_used_even_when_group_assets_exist_and_shared_files_are_deduplicated(factory, tmp_path):
    catalog, _ = fixture_catalog()
    license_path = "dependency/ffmpeg.LICENSE"
    payloads = {}
    catalog["files"][license_path] = {"size": 7, "sha256": digest(b"license")}
    for definition in catalog["groups"][:2]:
        definition["files"].append(license_path)
        payloads[definition["asset_name"]] = archive({name: b"license" if name == license_path else FILES[name]
                                                   for name in definition["files"]})
    full_name = catalog["full_asset"]["name"]
    full_payload = archive(FILES | {license_path: b"license"})
    payloads[full_name] = full_payload
    catalog["full_asset"].update(size=len(full_payload), sha256=digest(full_payload))
    downloads = []

    def release(url):
        return {"assets": [{"name": name, "size": len(data), "digest": "sha256:" + digest(data)}
                           for name, data in payloads.items()]}

    def download(url, destination, **kwargs):
        name = url.rsplit("/", 1)[-1]
        downloads.append(name)
        Path(destination).write_bytes(payloads[name])

    service, _, _ = factory(catalog=catalog, fetch_release=release, download_asset=download)
    assert service.update()["ok"]
    state = wait(service)
    assert state["phase"] == "completed", state
    assert state["download_mode"] == "full"
    assert state["download_bytes"] == len(full_payload)
    assert downloads == [full_name]
    assert (tmp_path / "app" / license_path).read_bytes() == b"license"


@pytest.mark.parametrize("case", ["archive_digest", "file_digest", "unsafe_path", "unknown_file", "case_duplicate", "symlink", "unsafe_directory"])
def test_untrusted_archives_never_replace_dependencies(factory, tmp_path, case):
    catalog, payload = fixture_catalog()
    content = dict(FILES)
    if case == "archive_digest":
        payload = b"x" * len(payload)
    else:
        target = io.BytesIO()
        with zipfile.ZipFile(target, "w") as zipped:
            for name, data in content.items():
                zipped.writestr(name, b"x" * len(data) if case == "file_digest" and name.endswith("yt-dlp.exe") else data)
            if case == "unsafe_path":
                zipped.writestr("dependency/../settings.ini", b"evil")
            elif case == "unknown_file":
                zipped.writestr("dependency/ffprobe.exe", b"unknown")
            elif case == "case_duplicate":
                zipped.writestr("dependency/YT-DLP.EXE", FILES["dependency/yt-dlp.exe"])
            elif case == "symlink":
                info = zipfile.ZipInfo("dependency/ffprobe.exe")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zipped.writestr(info, "outside")
            elif case == "unsafe_directory":
                zipped.writestr("dependency/../", b"")
        payload = target.getvalue()
        catalog["full_asset"].update(size=len(payload), sha256=digest(payload))
    service, manager, _ = factory(catalog=catalog, payload=payload)
    root = tmp_path / "app"
    root.mkdir()
    private = root / "settings.ini"
    private.write_bytes(b"private")
    assert service.install(["core"])["ok"]
    state = wait(service)
    assert state["phase"] == "failed", state
    assert state["code"] in {"archive_hash_mismatch", "file_hash_mismatch", "unsafe_archive", "unsafe_path"}
    assert private.read_bytes() == b"private"
    assert not (root / "dependency/yt-dlp.exe").exists()
    assert manager.snapshot()["accepting"] and not state["recovery_required"]


def test_partial_replace_failure_restores_every_original_file(factory, tmp_path, monkeypatch):
    service, manager, _ = factory()
    root = tmp_path / "app/dependency"
    root.mkdir(parents=True)
    for name in ("yt-dlp.exe", "ffmpeg.exe"):
        (root / name).write_bytes(("old " + name).encode())
    original = os.replace
    failed = []

    def replace(source, destination):
        if "staged" in Path(source).parts and Path(destination).name == "yt-dlp.exe" and not failed:
            failed.append(True)
            raise OSError("fixture commit failure")
        return original(source, destination)

    monkeypatch.setattr(dependency_module.os, "replace", replace)
    assert service.install(["core"], replace_changed=True)["ok"]
    state = wait(service)
    assert state["phase"] == "failed" and not state["recovery_required"], state
    for name in ("yt-dlp.exe", "ffmpeg.exe"):
        assert (root / name).read_bytes() == ("old " + name).encode()
    journals = list((tmp_path / "app/download/.dependency-manager/operations").glob("*/journal.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["status"] == "rolled_back"
    assert manager.snapshot()["accepting"]


def test_close_cancels_waits_and_rejects_new_operations(factory):
    entered = threading.Event()

    def download(url, destination, *, cancel_event, **kwargs):
        entered.set()
        assert cancel_event.wait(3)
        raise OSError("fixture cancelled")

    service, manager, _ = factory(download_asset=download)
    assert service.install(["core"])["ok"]
    assert entered.wait(3)
    assert service.close(timeout=3)
    assert not service.snapshot()["running"] and manager.snapshot()["accepting"]
    assert service.check()["code"] == "closed"
    assert service.install(["core"])["code"] == "closed"
    assert service.update()["code"] == "closed"


def test_late_completion_cannot_clear_new_operations_busy_flag(factory):
    entered, release = threading.Event(), threading.Event()
    started = threading.Event()
    second = []
    holder = {}

    def broadcast():
        state = holder["service"].snapshot()
        if state["action"] == "install" and state["phase"] == "completed" and not state["running"]:
            service = holder["service"]
            original = service._inspect_groups

            def blocked(selected, *, full):
                entered.set()
                assert release.wait(3)
                original(selected, full=full)

            service._inspect_groups = blocked
            second.append(service.check(["youtube"]))
            started.set()

    service, _, _ = factory(broadcast_download_state=broadcast)
    holder["service"] = service
    assert service.install(["core"])["ok"]
    try:
        assert entered.wait(3)
        assert started.wait(3)
        assert second and second[0]["ok"]
        assert service.snapshot()["running"]
        assert service.install(["core"])["code"] == "busy"
    finally:
        release.set()
    assert wait(service)["phase"] == "completed"


@pytest.mark.parametrize("callback", ["cancel_idle_timer", "broadcast_download_state"])
def test_start_callback_failure_restores_download_acceptance(factory, callback):
    def fail():
        raise RuntimeError("fixture callback failed")

    service, manager, calls = factory(**{callback: fail})
    response = service.install(["core"])
    assert response["code"] == "start_failed"
    assert not service.snapshot()["running"] and manager.snapshot()["accepting"]
    assert calls == []


@pytest.mark.parametrize("action", ["install", "check"])
def test_idle_timer_callback_observes_finished_dependency_operation(factory, action):
    observed = []
    holder = {}
    notified = threading.Event()

    def idle():
        observed.append(holder["service"].snapshot()["running"])
        notified.set()

    service, _, _ = factory(start_idle_timer=idle)
    holder["service"] = service
    assert getattr(service, action)(["core"])["ok"]
    wait(service)
    assert notified.wait(3)
    assert observed == [False]


@pytest.mark.parametrize("full", [False, True])
def test_presence_check_ignores_hash_cache_and_legacy_full_flag(factory, tmp_path, monkeypatch, full):
    service, _, _ = factory()
    root = tmp_path / "app"
    for name, data in FILES.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    legacy_cache = root / "download/.dependency-manager/validation-cache.json"
    legacy_cache.parent.mkdir(parents=True)
    legacy_cache.write_bytes(b"legacy cache must not be read or rewritten")
    def unexpected_digest(*args):
        raise AssertionError("presence check must avoid hashing")

    monkeypatch.setattr(dependency_module, "_digest", unexpected_digest)
    assert service.check(None, full=full)["ok"]
    state = wait(service)
    assert state["verification_mode"] == "existence" and state["phase"] == "completed"
    assert group(state, "core")["state"] == "present"
    assert state["existing_count"] == 4
    assert legacy_cache.read_bytes() == b"legacy cache must not be read or rewritten"


def test_snapshot_caps_details_and_prioritizes_missing_files(factory, tmp_path):
    catalog, _ = fixture_catalog()
    paths = [f"dependency/Withny/module-{index:02}.dll" for index in range(55)]
    catalog["groups"][0]["files"] = paths
    catalog["files"].update({path: {"size": 1, "sha256": digest(b"a")} for path in paths})
    service, _, _ = factory(catalog=catalog)
    for name in paths[:-1]:
        target = tmp_path / "app" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"a")
    assert service.check(["core"])["ok"]
    core = group(wait(service), "core")
    assert core["file_count"] == 55 and core["details_truncated"]
    assert len(core["details"]) == 50
    assert core["details"][0]["path"] == paths[-1]
    assert all("actual_sha256" not in item for item in core["details"])


def test_cancelling_during_commit_rolls_back_new_and_changed_files(factory, tmp_path, monkeypatch):
    service, manager, _ = factory()
    root = tmp_path / "app/dependency"
    root.mkdir(parents=True)
    old = root / "ffmpeg.exe"
    old.write_bytes(b"old ffmpeg")
    original = os.replace

    def replace(source, destination):
        result = original(source, destination)
        if "staged" in Path(source).parts and Path(destination).name == "ffmpeg.exe":
            service.cancel()
        return result

    monkeypatch.setattr(dependency_module.os, "replace", replace)
    assert service.install(["core"], replace_changed=True)["ok"]
    state = wait(service)
    assert state["phase"] == "cancelled" and not state["recovery_required"], state
    assert old.read_bytes() == b"old ffmpeg"
    assert not (root / "yt-dlp.exe").exists()
    assert manager.snapshot()["accepting"]


def test_failed_rollback_preserves_backups_until_explicit_recovery_install(factory, tmp_path, monkeypatch):
    service, _, _ = factory()
    root = tmp_path / "app/dependency"
    root.mkdir(parents=True)
    for name in ("yt-dlp.exe", "ffmpeg.exe"):
        (root / name).write_bytes(("original " + name).encode())
    original = os.replace

    def replace(source, destination):
        source = Path(source)
        if source.name == "yt-dlp.exe" and ("staged" in source.parts or "backup" in source.parts):
            raise OSError("fixture replacement unavailable")
        return original(source, destination)

    monkeypatch.setattr(dependency_module.os, "replace", replace)
    assert service.install(["core"], replace_changed=True)["ok"]
    state = wait(service)
    assert state["phase"] == "failed" and state["recovery_required"]
    assert state["code"] == "recovery_required"
    operations = tmp_path / "app/download/.dependency-manager/operations"
    backup = next(operations.glob("*/backup/dependency/yt-dlp.exe"))
    assert backup.read_bytes() == b"original yt-dlp.exe"
    assert not list(operations.glob("*/staged"))
    monkeypatch.setattr(dependency_module.os, "replace", original)
    restarted, _, calls = factory()
    assert restarted.snapshot()["recovery_required"]
    assert not (root / "yt-dlp.exe").exists()
    assert calls == [], "constructing the service must not recover or download"
    assert restarted.install(["core"], replace_changed=True)["ok"]
    state = wait(restarted)
    assert state["phase"] == "completed" and not state["recovery_required"], state
    assert (root / "yt-dlp.exe").read_bytes() == FILES["dependency/yt-dlp.exe"]


def test_tampered_recovery_journal_cannot_write_personal_configuration(factory, tmp_path):
    catalog, _ = fixture_catalog()
    root = tmp_path / "app"
    operation = "a" * 32
    directory = root / "download/.dependency-manager/operations" / operation
    directory.mkdir(parents=True)
    private = root / "settings.ini"
    private.write_bytes(b"keep my settings")
    record = {"schema_version": 1, "revision": catalog["revision"], "operation_id": operation,
              "status": "committing", "entries": [{"path": "settings.ini", "existed": False,
                                                        "new_sha256": digest(b"keep my settings")} ]}
    (directory / "journal.json").write_text(json.dumps(record), encoding="utf-8")
    service, manager, calls = factory()
    assert service.snapshot()["recovery_required"]
    assert service.install(["core"])["ok"]
    state = wait(service)
    assert state["recovery_required"] and state["code"] == "recovery_required"
    assert private.read_bytes() == b"keep my settings"
    assert calls == [] and manager.snapshot()["accepting"]


def test_thread_start_failure_can_be_closed_and_retried(factory, monkeypatch):
    service, manager, calls = factory()
    original = threading.Thread.start

    def fail(worker):
        raise RuntimeError("fixture thread failed")

    monkeypatch.setattr(threading.Thread, "start", fail)
    assert service.install(["core"])["code"] == "start_failed"
    assert manager.snapshot()["accepting"] and calls == []
    monkeypatch.setattr(threading.Thread, "start", original)
    assert service.check(["core"])["ok"]
    assert wait(service)["phase"] == "completed"
    assert service.close()


def test_close_timeout_does_not_report_operation_or_recovery_completed(factory):
    entered, release = threading.Event(), threading.Event()

    def downloading(url, destination, **kwargs):
        entered.set()
        assert release.wait(3)
        raise OSError("fixture download interrupted")

    service, manager, _ = factory(download_asset=downloading)
    assert service.install(["core"])["ok"]
    assert entered.wait(3)
    try:
        assert service.close(timeout=0) is False
        assert service.snapshot()["running"]
        assert not manager.snapshot()["accepting"]
    finally:
        release.set()
    assert wait(service)["phase"] == "cancelled"
    assert manager.snapshot()["accepting"]


@pytest.mark.parametrize("frozen, expected", [(False, "source_runtime"), (True, "builtin")])
def test_runtime_libraries_are_readonly_and_never_network_installed(factory, frozen, expected):
    catalog, _ = fixture_catalog()
    catalog["groups"].append({"id": "runtime", "name": "runtime", "description": "fixture",
                              "requires": [], "files": [], "source_only": True,
                              "installable": False, "asset_name": None})
    service, _, calls = factory(catalog=catalog, frozen=frozen)
    assert group(service.snapshot(), "runtime")["state"] == expected
    assert service.install(["runtime"])["code"] == "readonly_group"
    assert calls == []


def test_changed_catalog_revision_does_not_trigger_hashing_during_presence_check(factory, tmp_path, monkeypatch):
    service, _, _ = factory()
    target = tmp_path / "app/dependency/yt-dlp.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(FILES["dependency/yt-dlp.exe"])
    assert service.check(["core"])["ok"]
    wait(service)
    catalog, _ = fixture_catalog()
    catalog["revision"] = "c" * 64
    second, _, _ = factory(catalog=catalog)
    monkeypatch.setattr(dependency_module, "_digest", lambda *args: pytest.fail("revision changes must not hash during detection"))
    assert second.check(["core"], full=False)["ok"]
    state = wait(second)
    assert state["verification_mode"] == "existence"
    assert next(item for item in group(state, "core")["details"] if item["path"] == "dependency/yt-dlp.exe")["verification"] == "existence"


def test_missing_detection_reports_counts_without_using_same_revision_cache(factory, tmp_path):
    service, _, _ = factory()
    assert service.check(["core"])["ok"]
    wait(service)
    target = tmp_path / "app/dependency/yt-dlp.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * len(FILES["dependency/yt-dlp.exe"]))
    restarted, _, _ = factory()
    assert restarted.check(None, full=False)["ok"]
    state = wait(restarted)
    assert state["verification_mode"] == "existence"
    assert group(state, "core")["state"] == "missing"
    assert state["file_count"] == 4 and state["existing_count"] == 1 and state["missing_count"] == 3
    assert "dependency/yt-dlp.exe" not in state["missing_files"]


def test_install_completion_requires_post_install_hash_verification(factory, tmp_path, monkeypatch):
    service, manager, _ = factory()
    original = service._inspect_groups
    scans = []

    def scan(selected, *, full):
        scans.append(True)
        if len(scans) == 2:
            (tmp_path / "app/dependency/yt-dlp.exe").unlink()
        original(selected, full=full)

    monkeypatch.setattr(service, "_inspect_groups", scan)
    assert service.install(["core"])["ok"]
    state = wait(service)
    assert state["phase"] == "failed", state
    assert state["code"] == "post_install_verification_failed"
    assert not state["recovery_required"]
    assert not (tmp_path / "app/dependency/ffmpeg.exe").exists()
    assert group(state, "core")["state"] != "verified"
    assert manager.snapshot()["accepting"]
