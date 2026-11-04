"""真实容器、回环 HTTP 与微型依赖包；运行数据完全位于 tmp_path。"""
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

import pytest

from video_downloader import container
from video_downloader.services.dependency_manager import DependencyManager


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def wired(tmp_path, monkeypatch):
    files = {"dependency/yt-dlp.exe": b"synthetic yt-dlp, never executed",
             "dependency/deno.exe": b"synthetic deno, never executed",
             "dependency/fantiadl.exe": b"synthetic fantia, never executed"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    payload = buffer.getvalue()
    catalog = {"schema_version": 1, "version": "2.7.1", "release_tag": "v2.7.1",
               "revision": "c" * 64, "groups": [],
               "full_asset": {"name": "video-downloader-v2.7.1-dependencies.zip",
                              "size": len(payload), "sha256": sha(payload)},
               "files": {name: {"size": len(data), "sha256": sha(data)} for name, data in files.items()}}
    catalog["files"]["dependency/yt-dlp.exe"]["user_updatable"] = True
    for group_id, name in (("core", "yt-dlp"), ("youtube", "deno"), ("fantia", "fantiadl")):
        catalog["groups"].append({"id": group_id, "name": group_id, "description": "本机合成组件",
                                  "requires": [] if group_id == "core" else ["core"],
                                  "files": [f"dependency/{name}.exe"], "source_only": False,
                                  "installable": True,
                                  "asset_name": f"video-downloader-v2.7.1-dependencies-{group_id}.zip"})
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    downloads = []
    hold, entered, release = threading.Event(), threading.Event(), threading.Event()

    def download(url, destination, **options):
        downloads.append(url)
        entered.set()
        if hold.is_set():
            assert release.wait(5)
        Path(destination).write_bytes(payload)
        options["progress"](len(payload), len(payload))

    def manager(tool_dir, **kwargs):
        return DependencyManager(tool_dir, catalog_path=catalog_path,
                                 fetch_release=lambda url: {"assets": []},
                                 download_asset=download, **kwargs)

    monkeypatch.setattr(container, "DependencyManager", manager)
    controllers = []
    controller_type = container.FanboxController

    def controller(*args, **kwargs):
        value = controller_type(*args, **kwargs)
        controllers.append(value)
        return value

    monkeypatch.setattr(container, "FanboxController", controller)
    app_root = tmp_path / "app"
    app = container.AppContainer(app_root).wire()
    app.updater.start_check_thread = Mock()
    monkeypatch.setattr(container.webbrowser, "open", Mock())
    yield app, app_root, files, downloads, hold, entered, release, controllers
    release.set()
    app.request_exit()
    app.cancel_idle_timer()
    app.http_service.stop()


def wait_for(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    assert predicate(), "隔离集成操作未及时结束"


def client(app):
    url = app.http_service.start()
    with urlopen(url, timeout=5) as response:
        token = re.search(r'window\.SESSION_TOKEN\s*=\s*"([^"]+)"', response.read().decode()).group(1)

    def request(path, data=None):
        req = Request(url + path, data=None if data is None else json.dumps(data).encode(),
                      headers={"Content-Type": "application/json", "Origin": url,
                               "X-Session-Token": token})
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    return request


def test_real_container_checks_missing_and_updates_complete_dependencies_via_http(wired):
    app, root, files, downloads, *_ = wired
    request = client(app)
    assert request("/api/dependencies/check", {})[0] == 200
    wait_for(lambda: not app.dependency_manager.snapshot()["running"])
    assert not downloads
    before = request("/api/dependencies")[1]
    assert before["file_count"] == before["missing_count"] == 3
    assert before["existing_count"] == 0
    assert request("/api/dependencies/update", {})[0] == 200
    wait_for(lambda: not app.dependency_manager.snapshot()["running"])
    state = request("/api/dependencies")[1]
    assert state["phase"] == "completed", state
    assert state["download_mode"] == "full"
    assert len(downloads) == 1
    assert state["missing_count"] == 0 and state["existing_count"] == 3
    for name in files:
        assert (root / name).read_bytes() == files[name]
    assert app.dependency_manager._manager.snapshot()["accepting"]


def test_real_install_blocks_operations_and_cancel_releases_guard(wired):
    app, root, _, _, hold, entered, release, *_ = wired
    request = client(app)
    hold.set()
    assert request("/api/dependencies/update", {})[0] == 200
    assert entered.wait(3)
    assert request("/api/start", {"url": "https://example.invalid/video"})[0] == 409
    assert request("/api/tool", {"action": "update-ytdlp"})[0] == 409
    assert request("/api/live/inspect", {"url": "https://example.invalid/live"})[0] == 409
    assert request("/api/exit", {})[0] == 409
    assert request("/api/dependencies/cancel", {})[0] == 200
    release.set()
    wait_for(lambda: not app.dependency_manager.snapshot()["running"])
    assert app.dependency_manager.snapshot()["phase"] == "cancelled"
    assert not (root / "dependency/yt-dlp.exe").exists()
    assert app.dependency_manager._manager.snapshot()["accepting"]
    assert request("/api/dependencies/check", {})[0] == 200
    wait_for(lambda: not app.dependency_manager.snapshot()["running"])


def test_main_starts_local_check_without_installing(wired):
    app, _, _, downloads, *_ = wired
    main = threading.Thread(target=app.main)
    try:
        main.start()
        wait_for(lambda: app.http_service.url is not None)
        wait_for(lambda: app.dependency_manager.snapshot()["phase"] == "completed")
        state = client(app)("/api/dependencies")[1]
        assert state["action"] == "check"
        assert state["verification_mode"] == "existence"
        assert state["missing_count"] == 3
        assert downloads == []
    finally:
        app.request_exit()
        main.join(5)
    assert not main.is_alive()
    assert app.dependency_manager.check()["code"] == "closed"


@pytest.mark.parametrize("task_mode", [0, 1])
@pytest.mark.parametrize("state", [{"recovery_required": True}, {"running": True, "action": "install"}])
def test_background_fanbox_resume_obeys_dependency_guard(wired, monkeypatch, task_mode, state):
    app, _, _, _, _, _, _, controllers = wired
    app.app_state.replace_config({"TASK_MODE": task_mode})
    submit = Mock(return_value={"ok": True})
    exclusive = Mock(return_value={"ok": True})
    monkeypatch.setattr(container.TaskManager, "submit", submit)
    monkeypatch.setattr(container.TaskManager, "start_exclusive", exclusive)
    app.dependency_manager._state.update(state)
    try:
        result = controllers[0].start("synthetic-job", "https://sample.fanbox.cc", True, {})
        assert result.get("code") == "dependency_maintenance", result
        submit.assert_not_called()
        exclusive.assert_not_called()
        app.dependency_manager._state.update(running=False, recovery_required=False, action="check")
        assert controllers[0].start("synthetic-job", "https://sample.fanbox.cc", True, {})["ok"]
        assert submit.call_count + exclusive.call_count == 1
    finally:
        app.dependency_manager._state.update(running=False, recovery_required=False)


def test_fanbox_background_resume_cannot_invert_http_maintenance_locks(wired, monkeypatch):
    app, _, _, _, _, _, _, controllers = wired
    controller = controllers[0]
    monkeypatch.setattr(container.TaskManager, "submit", Mock(return_value={"ok": True}))
    entered = threading.Event()

    def background_resume():
        if not controller.lock.acquire(timeout=.2):
            return
        try:
            entered.set()
            controller.start("synthetic-job", "https://sample.fanbox.cc", True, {})
        finally:
            controller.lock.release()

    guard = app.dependency_manager._maintenance_lock
    worker = threading.Thread(target=background_resume)
    guard.acquire()
    acquired = False
    try:
        worker.start()
        entered.wait(.25)
        # HTTP 已持有维护锁，仍应能进入控制器；后台恢复不能反向占住控制器锁。
        acquired = controller.lock.acquire(timeout=.2)
        if acquired:
            controller.lock.release()
    finally:
        guard.release()
        worker.join(3)
    assert acquired, "FANBOX 自动继续与 HTTP 维护门禁存在反向锁依赖"
    assert not worker.is_alive()


def test_startup_defers_watch_until_explicit_transaction_recovery(wired, monkeypatch):
    original, root, files, downloads, *_ = wired
    original.request_exit()
    name = "dependency/yt-dlp.exe"
    old = b"old synthetic dependency"
    operation = "a" * 32
    directory = root / "download/.dependency-manager/operations" / operation
    backup = directory / "backup" / name
    backup.parent.mkdir(parents=True)
    backup.write_bytes(old)
    (root / name).write_bytes(files[name])
    (directory / "journal.json").write_text(json.dumps({
        "schema_version": 1, "revision": "c" * 64, "operation_id": operation,
        "status": "committing", "entries": [{"path": name, "existed": True,
                                               "old_sha256": sha(old), "new_sha256": sha(files[name])}]
    }), encoding="utf-8")
    starts = []
    monkeypatch.setattr(container.LiveWatchService, "start", lambda self: starts.append(self))
    # 重启时保留的 WAITING 监控尚未启动，不能挡住依赖事务恢复。
    monkeypatch.setattr(container.LiveWatchService, "has_active_jobs", lambda self: True)
    app = container.AppContainer(root).wire()
    app.updater.start_check_thread = Mock()
    assert app.dependency_manager.snapshot()["recovery_required"]
    main = threading.Thread(target=app.main)
    try:
        main.start()
        wait_for(lambda: app.http_service.url is not None)
        wait_for(lambda: not app.dependency_manager.snapshot()["running"])
        request = client(app)
        assert not starts and not downloads
        assert backup.read_bytes() == old
        assert request("/api/start", {"url": "https://example.invalid/video"})[0] == 409
        assert request("/api/dependencies/update", {})[0] == 200
        wait_for(lambda: not app.dependency_manager.snapshot()["running"])
        state = app.dependency_manager.snapshot()
        assert state["phase"] == "completed" and not state["recovery_required"], state
        wait_for(lambda: len(starts) == 1)
        assert app.dependency_manager.update()["code"] == "active_tasks"
        assert json.loads((directory / "journal.json").read_text(encoding="utf-8"))["status"] == "rolled_back"
        # 事务先恢复原文件；新的一键更新继续保留用户更新过的 yt-dlp。
        assert (root / name).read_bytes() == old
    finally:
        app.request_exit()
        app.cancel_idle_timer()
        main.join(5)
        app.http_service.stop()
    assert not main.is_alive()


def test_simple_update_keeps_user_ytdlp_and_configuration(wired):
    app, root, files, downloads, *_ = wired
    custom = b"user updated yt-dlp, never executed"
    (root / "dependency/yt-dlp.exe").write_bytes(custom)
    (root / "dependency/deno.exe").write_bytes(b"outdated synthetic tool")
    settings = root / "settings.ini"
    settings.write_text("synthetic-setting=keep", encoding="utf-8")
    request = client(app)
    assert request("/api/dependencies/check", {})[0] == 200
    wait_for(lambda: not app.dependency_manager.snapshot()["running"])
    assert app.dependency_manager.snapshot()["existing_count"] == 2
    assert app.dependency_manager.snapshot()["missing_count"] == 1
    assert downloads == []
    assert request("/api/dependencies/update", {})[0] == 200
    wait_for(lambda: not app.dependency_manager.snapshot()["running"])
    state = app.dependency_manager.snapshot()
    assert state["phase"] == "completed", state
    assert (root / "dependency/yt-dlp.exe").read_bytes() == custom
    assert (root / "dependency/deno.exe").read_bytes() == files["dependency/deno.exe"]
    assert (root / "dependency/fantiadl.exe").read_bytes() == files["dependency/fantiadl.exe"]
    assert settings.read_text(encoding="utf-8") == "synthetic-setting=keep"
    assert state["preserved_files"] == ["dependency/yt-dlp.exe"]
    assert state["missing_count"] == 0
    assert len(downloads) == 1
