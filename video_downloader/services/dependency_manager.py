"""检查缺失文件并更新完整发布依赖；网络、文件事务与界面调用隔离。"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import threading
from urllib import request as urllib_request
from urllib.parse import quote, urlsplit
import uuid
import zipfile

from video_downloader.core.constants import GITHUB_OWNER, GITHUB_REPO
from video_downloader.core.platform import asset_digest
from video_downloader.services.download_manager import DownloadManager


MANUAL_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
MAX_ASSET_BYTES = 2 * 1024 ** 3
MAX_UNPACKED_BYTES = 8 * 1024 ** 3
MAX_FILES = 100000
DETAIL_LIMIT = 50
GROUP_METADATA = ("id", "name", "description", "requires", "source_only", "installable")
ROOT_FILES = {"yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe", "deno.exe", "fantiadl.exe",
              "nicochannel.zip", "withny-dl-windows-amd64.exe"}
ROOT_DIRS = {"BililiveRecorder", "Withny", "live-python", "fanbox-python",
             "yt-dlp-plugins", "bgutil-ytdlp-pot-provider"}
PRIVATE_NAMES = {"settings.ini", "presets.json", "cookies.txt", "cookies.json", "urls.txt",
                 "download_history.json", "twitcasting_passwords.xlsx", "twitcasting_passwords.csv",
                 "credentials.yaml", "credentials.json", "config.yaml", "config.yml",
                 "withny-live-config.yaml", "withny-live-config.yml", "withny-dl.json",
                 ".npmrc", ".netrc", ".git-credentials", ".gitconfig"}
PRIVATE_DIRS = {".git", "download", "logs", "__pycache__", ".venv", "venv", ".cache"}
PRIVATE_SUFFIXES = {".har", ".db", ".sqlite", ".sqlite3", ".key", ".pfx", ".p12", ".part", ".tmp", ".log"}
DOWNLOAD_HOSTS = {"github.com", "api.github.com", "objects.githubusercontent.com",
                  "release-assets.githubusercontent.com", "github-releases.githubusercontent.com"}


class DependencyError(Exception):
    def __init__(self, message, code="dependency_error", **details):
        super().__init__(message)
        self.code, self.details = code, details


class DependencyCancelled(DependencyError):
    def __init__(self):
        super().__init__("依赖操作已取消", "cancelled")


def _digest(path, cancel=None):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancel is not None and cancel.is_set():
                raise DependencyCancelled()
            checksum.update(chunk)
    return checksum.hexdigest()


def _hex(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _relative(name):
    if not isinstance(name, str) or "\\" in name or len(name) > 1024:
        raise DependencyError("依赖路径无效", "unsafe_path")
    parts = name.split("/")
    if (len(parts) < 2 or parts[0] != "dependency" or PurePosixPath(name).is_absolute()
            or any(not part or part in {".", ".."} or ":" in part or part.rstrip(" .") != part
                   or any(ord(char) < 32 for char in part) for part in parts)):
        raise DependencyError("依赖路径越界或存在 Windows 路径别名", "unsafe_path")
    for part in parts:
        stem = part.split(".")[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", stem):
            raise DependencyError("依赖路径含保留设备名", "unsafe_path")
    folded = [part.casefold() for part in parts]
    if (set(folded) & PRIVATE_DIRS or folded[-1] in PRIVATE_NAMES
            or folded[-1].startswith(".env") or PurePosixPath(name).suffix.casefold() in PRIVATE_SUFFIXES):
        raise DependencyError("依赖清单不能包含配置、凭据或下载数据", "unsafe_path")
    if not ((len(parts) == 2 and (parts[1] in ROOT_FILES or parts[1].endswith(".LICENSE")))
            or (len(parts) > 2 and parts[1] in ROOT_DIRS)):
        raise DependencyError("依赖路径不属于受管组件", "unsafe_path")
    return parts


def _is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _trusted_url(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in DOWNLOAD_HOSTS
                and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except (ValueError, TypeError):
        return False


class _TrustedRedirect(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _trusted_url(newurl):
            raise DependencyError("依赖下载重定向到了不可信来源", "untrusted_source")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DependencyManager:
    def __init__(self, tool_dir, *, catalog_path=None, frozen=None, download_manager=None,
                 has_active_downloads=None, cancel_idle_timer=None, start_idle_timer=None,
                 broadcast_download_state=None, maintenance_lock=None, log=None, emit_event=None,
                 fetch_release=None, download_asset=None):
        self._root = Path(tool_dir).resolve()
        self._frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        if catalog_path is None:
            base = Path(sys._MEIPASS) if self._frozen and hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parents[2] / "resource"
            catalog_path = base / "dependencies" / "dependency-catalog.json"
        self._manager = download_manager or DownloadManager()
        self._active = has_active_downloads or (lambda: False)
        self._cancel_idle = cancel_idle_timer or (lambda: None)
        self._start_idle = start_idle_timer or (lambda: None)
        self._broadcast = broadcast_download_state or (lambda: None)
        self._log = log or (lambda *args: None)
        # emit_event 仅保留构造兼容；当前页面通过状态接口轮询依赖进度。
        self._maintenance_lock = maintenance_lock or threading.RLock()
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread = None
        self._closed = False
        self._results = {}
        self._fetch_release = fetch_release or self._fetch_release_default
        self._download_asset = download_asset or self._download_asset_default
        self._catalog, self._groups = None, {}
        self._work = self._root / "download" / ".dependency-manager"
        self._state = {"available": False, "running": False, "action": None, "phase": "idle",
                       "progress": 0, "message": "尚未检查依赖", "error": None, "code": None,
                       "manual_update_url": MANUAL_URL, "catalog_version": None, "revision": None,
                       "operation_id": None, "download_mode": None, "download_bytes": None, "recovery_required": False,
                       "changed_files": [], "preserved_files": []}
        try:
            if Path(catalog_path).stat().st_size > 32 * 1024 * 1024:
                raise DependencyError("依赖清单超过允许大小", "invalid_catalog")
            catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
            self._validate_catalog(catalog)
            self._catalog = catalog
            self._groups = {group["id"]: group for group in catalog["groups"]}
            self._state.update(available=True, catalog_version=catalog["version"], revision=catalog["revision"])
        except (OSError, ValueError, TypeError, KeyError, RecursionError, DependencyError) as error:
            self._state.update(error="依赖清单暂不可用：" + str(error), code="invalid_catalog", phase="failed")
        if self._state["available"]:
            try:
                self._state["recovery_required"] = bool(self._pending_transactions())
                if self._state["recovery_required"]:
                    self._state["message"] = "检测到未完成的依赖安装，请点击安装／修复以恢复备份后继续"
            except (OSError, ValueError, TypeError, DependencyError) as error:
                self._state.update(recovery_required=True, error=str(error), code="recovery_required",
                                   message="维护记录需要恢复，请保留备份后重试安装或手动处理", phase="failed")

    @staticmethod
    def _validate_catalog(catalog):
        if not isinstance(catalog, dict) or catalog.get("schema_version") != 1:
            raise DependencyError("不支持的依赖清单", "invalid_catalog")
        version = catalog.get("version")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version) or catalog.get("release_tag") != "v" + version:
            raise DependencyError("依赖清单版本无效", "invalid_catalog")
        if not _hex(catalog.get("revision")):
            raise DependencyError("依赖修订标识无效", "invalid_catalog")
        files, groups = catalog.get("files"), catalog.get("groups")
        if not isinstance(files, dict) or not 0 < len(files) <= MAX_FILES or not isinstance(groups, list) or not 0 < len(groups) <= 100:
            raise DependencyError("依赖清单文件／分组无效", "invalid_catalog")
        seen, total = set(), 0
        for name, record in files.items():
            _relative(name)
            if name.casefold() in seen or not isinstance(record, dict):
                raise DependencyError("依赖清单存在重复或非法记录", "invalid_catalog")
            seen.add(name.casefold())
            size = record.get("size")
            if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_ASSET_BYTES or not _hex(record.get("sha256")):
                raise DependencyError("依赖文件大小或摘要无效", "invalid_catalog")
            if "user_updatable" in record and not isinstance(record["user_updatable"], bool):
                raise DependencyError("依赖更新标记无效", "invalid_catalog")
            total += size
        if total > MAX_UNPACKED_BYTES:
            raise DependencyError("依赖清单解压大小超限", "invalid_catalog")
        ids = set()
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("id"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", group["id"]):
                raise DependencyError("依赖分组标识无效", "invalid_catalog")
            group_id = group["id"]
            if (group_id in ids or not isinstance(group.get("name"), str)
                    or not group["name"] or len(group["name"]) > 256):
                raise DependencyError("依赖分组重复或名称无效", "invalid_catalog")
            if not isinstance(group.get("description", ""), str) or len(group.get("description", "")) > 4096:
                raise DependencyError("依赖分组说明必须为有效文本", "invalid_catalog")
            if (group.get("asset_name") is not None and
                    (not isinstance(group["asset_name"], str) or len(group["asset_name"]) > 256)):
                raise DependencyError("依赖分组包名称必须为有效文本", "invalid_catalog")
            ids.add(group_id)
            paths = group.get("files")
            if not isinstance(paths, list) or len(paths) != len(set(paths)) or any(path not in files for path in paths):
                raise DependencyError("分组文件不在可信清单内", "invalid_catalog")
            if not isinstance(group.get("requires"), list) or any(not isinstance(item, str) for item in group["requires"]):
                raise DependencyError("分组前置依赖无效", "invalid_catalog")
            for field in ("source_only", "installable"):
                if not isinstance(group.get(field), bool):
                    raise DependencyError("分组可安装标记无效", "invalid_catalog")
            if group["source_only"] and group["installable"]:
                raise DependencyError("运行库分组必须只读", "invalid_catalog")
            if group["installable"] and not paths:
                raise DependencyError("托管依赖范围不能为空", "invalid_catalog")
        graph = {group["id"]: group["requires"] for group in groups}
        def visit(item, visiting, visited):
            if item in visiting or item not in graph:
                raise DependencyError("分组前置依赖循环或缺失", "invalid_catalog")
            if item in visited:
                return
            visiting.add(item)
            for required in graph[item]:
                visit(required, visiting, visited)
            visiting.remove(item)
            visited.add(item)
        visited = set()
        for item in graph:
            visit(item, set(), visited)
        full = catalog.get("full_asset")
        if not isinstance(full, dict) or full.get("name") != f"video-downloader-v{version}-dependencies.zip":
            raise DependencyError("完整依赖包名称无效", "invalid_catalog")
        if full.get("size") is not None and (isinstance(full["size"], bool) or not isinstance(full["size"], int) or not 0 < full["size"] <= MAX_ASSET_BYTES):
            raise DependencyError("完整依赖包大小无效", "invalid_catalog")
        if full.get("sha256") is not None and not _hex(full["sha256"]):
            raise DependencyError("完整依赖包摘要无效", "invalid_catalog")

    def _safe_path(self, path):
        path = Path(path)
        if not path.is_relative_to(self._root):
            raise DependencyError("依赖维护路径越界", "unsafe_path")
        current = self._root
        for part in path.relative_to(self._root).parts:
            current = current / part
            if _is_link(current):
                raise DependencyError("依赖路径包含符号链接或目录联接", "unsafe_path")
        if not path.resolve().is_relative_to(self._root):
            raise DependencyError("依赖维护路径超出程序目录", "unsafe_path")
        return path

    def _target(self, relative):
        return self._safe_path(self._root.joinpath(*_relative(relative)))

    def _write_json(self, path, data):
        path = self._safe_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._safe_path(path.parent)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            self._safe_path(path)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _pending_transactions(self):
        operations = self._safe_path(self._work / "operations")
        if not operations.exists():
            return []
        pending = []
        for path in operations.iterdir():
            if not re.fullmatch(r"[0-9a-f]{32}", path.name):
                continue
            self._safe_path(path)
            journal = self._safe_path(path / "journal.json")
            if not journal.is_file():
                continue
            try:
                if journal.stat().st_size > 32 * 1024 * 1024:
                    raise DependencyError("未完成依赖维护记录超过允许大小", "recovery_required")
                record = json.loads(journal.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise DependencyError("未完成依赖维护记录损坏，请保留备份并手动处理", "recovery_required") from error
            if not isinstance(record, dict):
                raise DependencyError("未完成依赖维护记录格式无效", "recovery_required")
            if record.get("status") not in {"complete", "rolled_back"}:
                pending.append((path, record))
        return pending

    def snapshot(self, *, include_groups=True):
        """默认保留兼容详情；当前页面可只读取汇总，避免构造未使用的分组。"""
        with self._lock:
            state = copy.deepcopy(self._state)
            if include_groups:
                groups = []
                priority = {"error": 0, "changed": 1, "missing": 2, "present": 3, "unchecked": 4, "verified": 5}
                for definition in self._groups.values():
                    paths = definition["files"]
                    samples, states = {}, set()
                    for path in paths:
                        status = self._results.get(path, {}).get("state", "unchecked")
                        states.add(status)
                        bucket = samples.setdefault(status, [])
                        if len(bucket) < DETAIL_LIMIT:
                            bucket.append(path)
                    sample_paths = [path for status in sorted(samples, key=lambda item: priority.get(item, 9))
                                    for path in samples[status]][:DETAIL_LIMIT]
                    details = [dict(path=path, **self._results.get(path, {"state": "unchecked"})) for path in sample_paths]
                    for item in details:
                        item.pop("actual_sha256", None)
                        item["user_updatable"] = bool(self._catalog["files"][item["path"]].get("user_updatable"))
                    if definition["source_only"]:
                        status = "builtin" if self._frozen else "source_runtime"
                        for item in details:
                            item["state"] = status
                    else:
                        status = next((candidate for candidate in ("error", "changed", "missing", "unchecked", "present")
                                        if candidate in states), "verified")
                    groups.append({key: copy.deepcopy(definition[key]) for key in GROUP_METADATA if key in definition} | {
                        "selectable": definition["installable"] and not definition["source_only"], "state": status,
                        "requires_confirmation": any(self._results.get(path, {}).get("state") == "changed"
                                                     and not self._catalog["files"][path].get("user_updatable")
                                                     for path in paths),
                        "size": sum(self._catalog["files"][path]["size"] for path in paths), "file_count": len(paths),
                        "details": details, "details_truncated": len(paths) > DETAIL_LIMIT})
                state["groups"] = groups
            managed = sorted({path for definition in self._groups.values()
                              if definition["installable"] and not definition["source_only"]
                              for path in definition["files"]})
            counts = {"existing_count": 0, "missing_count": 0, "error_count": 0, "unchecked_count": 0}
            missing = []
            for path in managed:
                status = self._results.get(path, {}).get("state", "unchecked")
                key = ("missing_count" if status == "missing" else "error_count" if status == "error"
                       else "unchecked_count" if status == "unchecked" else "existing_count")
                counts[key] += 1
                if status == "missing" and len(missing) < DETAIL_LIMIT:
                    missing.append(path)
            state.update(counts, file_count=len(managed), missing_files=missing,
                         missing_truncated=counts["missing_count"] > DETAIL_LIMIT)
            return state

    def _notice(self, message, level="info"):
        try:
            self._log(message, level)
        except Exception:
            pass

    def _state_update(self, **values):
        with self._lock:
            self._state.update(values)

    def _selected(self, ids, *, install):
        if ids is None and not install:
            ids = [key for key, group in self._groups.items() if group["installable"]]
        if (not isinstance(ids, list) or not ids or len(ids) > 100 or any(not isinstance(item, str) for item in ids)
                or len(ids) != len(set(ids)) or any(item not in self._groups for item in ids)):
            raise DependencyError("请选择有效且不重复的依赖分组", "invalid_selection")
        expanded = []
        def add(item):
            if item in expanded:
                return
            definition = self._groups[item]
            if not definition["installable"] or definition["source_only"]:
                raise DependencyError("内置或源码运行库应按对应运行方式维护", "readonly_group")
            for required in definition["requires"]:
                add(required)
            if item not in expanded:
                expanded.append(item)
        for item in ids:
            add(item)
        return expanded

    def check(self, group_ids=None, full=False):
        """只检查文件是否存在；full 参数仅保留旧调用兼容，不再触发哈希检查。"""
        if not isinstance(full, bool):
            return {"error": "完整校验开关必须为布尔值", "code": "invalid_selection"}
        return self._start("check", group_ids, full=False)

    def update(self):
        """明确更新完整托管依赖；保留用户自行更新的 yt-dlp。"""
        selected = [key for key, group in self._groups.items() if group["installable"] and not group["source_only"]]
        return self._start("install", selected, replace_changed=True, preserve_user_updates=True)

    def install(self, group_ids, replace_changed=False):
        if not isinstance(replace_changed, bool):
            return {"error": "替换确认必须为布尔值", "code": "invalid_selection"}
        return self._start("install", group_ids, replace_changed=replace_changed)

    def cancel(self):
        with self._lock:
            if self._state["running"]:
                self._cancel.set()
                self._state["message"] = "正在取消，等待当前读取结束并恢复必要备份…"
        return {"ok": True}

    def close(self, timeout=35):
        """取消并等待本模块自己的线程；超时保留事务记录，不冒充恢复完成。"""
        with self._maintenance_lock:
            with self._lock:
                self._closed = True
                self._cancel.set()
                worker = self._thread
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=max(0, timeout))
        return worker is None or not worker.is_alive()

    def _end_maintenance(self):
        try:
            self._manager.resume()
        except Exception as error:
            self._state_update(phase="failed", error="依赖维护结束后任务接收未恢复：" + str(error),
                               code="maintenance_release_failed")
        self._state_update(running=False)
        for callback in (self._broadcast, self._start_idle):
            try:
                callback()
            except Exception:
                pass

    def _start(self, action, ids, **options):
        with self._maintenance_lock:
            with self._lock:
                if self._closed:
                    return {"error": "依赖管理已关闭", "code": "closed"}
                if self._state["running"]:
                    return {"error": "依赖操作正在进行，请等待或取消", "code": "busy"}
                if not self._state["available"]:
                    return {"error": self._state["error"] or "依赖清单不可用", "code": "invalid_catalog"}
                try:
                    selected = self._selected(ids, install=action == "install")
                except DependencyError as error:
                    return {"error": str(error), "code": error.code}
                self._cancel = threading.Event()
                operation_id = uuid.uuid4().hex
                self._state.update(running=True, action=action, phase="starting", progress=0,
                                   message="正在准备依赖操作…", error=None, code=None, changed_files=[], preserved_files=[],
                                   operation_id=operation_id, selected_groups=selected, download_mode=None, download_bytes=None)
                self._state["verification_mode"] = "full" if action == "install" else "existence"
            maintained = False
            try:
                if action == "install":
                    if self._active():
                        raise DependencyError("请先完成或取消下载、音频工具及监控任务", "active_tasks")
                    if not self._manager.suspend():
                        raise DependencyError("请先停止当前任务或等待其他维护结束", "active_tasks")
                    maintained = True
                    self._cancel_idle()
                    self._broadcast()
                self._thread = threading.Thread(target=self._run, args=(action, selected, options, maintained),
                                                name="dependency-" + action, daemon=True)
                self._thread.start()
            except Exception as error:
                if self._thread is not None and self._thread.ident is None:
                    self._thread = None
                code = error.code if isinstance(error, DependencyError) else "start_failed"
                self._state_update(phase="failed", error=str(error), code=code,
                                   message="依赖操作未启动：" + str(error))
                if maintained:
                    self._end_maintenance()
                else:
                    self._state_update(running=False)
                return {"error": str(error), "code": code}
            return {"ok": True, "operation_id": operation_id}

    def _ensure_not_cancelled(self):
        if self._cancel.is_set():
            raise DependencyCancelled()

    def _run(self, action, selected, options, maintained):
        try:
            if action == "install":
                self._install(selected, options["replace_changed"], preserve_user_updates=options.get("preserve_user_updates", False))
            else:
                self._inspect_groups(selected, full=False)
            preserved = self._state["preserved_files"]
            message = ("已保留用户自行更新的组件（兼容性尚未验证）：" + "、".join(preserved)
                       + "；其余托管依赖已处理" if preserved else "托管依赖已更新并通过校验")
            self._state_update(phase="completed", progress=100,
                               message=message if action == "install" else "依赖缺失检查完成（仅检查文件是否存在）")
        except Exception as error:
            cancelled = self._cancel.is_set() and not self._state["recovery_required"]
            code = "cancelled" if cancelled else error.code if isinstance(error, DependencyError) else "operation_failed"
            extra = error.details if isinstance(error, DependencyError) else {}
            self._state_update(phase="cancelled" if cancelled else "failed", error=None if cancelled else str(error),
                               code=code, message="依赖操作已取消" if cancelled else str(error), **extra)
            self._notice("[依赖] " + ("操作已取消" if cancelled else str(error)), "warn" if cancelled else "error")
        finally:
            if maintained:
                self._end_maintenance()
            else:
                self._state_update(running=False)
                try:
                    self._start_idle()
                except Exception:
                    pass

    def _inspect_groups(self, selected, *, full):
        paths = sorted({path for group_id in selected for path in self._groups[group_id]["files"]})
        self._state_update(phase="checking", progress=0, message="正在校验更新所需的文件 SHA-256…" if full else "正在检查托管依赖文件是否存在…")
        for index, name in enumerate(paths):
            self._ensure_not_cancelled()
            expected = self._catalog["files"][name]
            result = {"state": "missing", "size": expected["size"]}
            try:
                path = self._target(name)
                if path.exists():
                    if not path.is_file():
                        raise DependencyError("路径不是普通文件", "unsafe_path")
                    info = path.stat()
                    if full:
                        actual = _digest(path, self._cancel)
                        valid = info.st_size == expected["size"] and actual == expected["sha256"]
                        result.update(state="verified" if valid else "changed", actual_sha256=actual, verification="sha256")
                    else:
                        result.update(state="present", verification="existence")
            except DependencyCancelled:
                raise
            except (OSError, DependencyError) as error:
                result.update(state="error", reason=str(error))
            with self._lock:
                self._results[name] = result
            self._state_update(progress=round((index + 1) / max(len(paths), 1) * 100, 1))

    @staticmethod
    def _fetch_release_default(url):
        if not _trusted_url(url) or urlsplit(url).hostname != "api.github.com":
            raise DependencyError("发布元数据来源无效", "untrusted_source")
        opener = urllib_request.build_opener(_TrustedRedirect())
        req = urllib_request.Request(url, headers={"User-Agent": "VideoDownloader-Dependencies/1.0", "Accept": "application/json"})
        with opener.open(req, timeout=20) as response:
            if not _trusted_url(response.geturl()):
                raise DependencyError("发布元数据跳转来源无效", "untrusted_source")
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise DependencyError("发布元数据超限", "invalid_release")
            return json.loads(body.decode("utf-8"))

    @staticmethod
    def _download_asset_default(url, destination, *, size, cancel_event, progress):
        if not _trusted_url(url):
            raise DependencyError("依赖包来源无效", "untrusted_source")
        opener = urllib_request.build_opener(_TrustedRedirect())
        req = urllib_request.Request(url, headers={"User-Agent": "VideoDownloader-Dependencies/1.0", "Accept-Encoding": "identity"})
        with opener.open(req, timeout=20) as response:
            if not _trusted_url(response.geturl()):
                raise DependencyError("依赖包最终来源无效", "untrusted_source")
            length = int(response.headers.get("Content-Length", 0))
            if length and length != size:
                raise DependencyError("依赖包下载大小与发布清单不一致", "archive_size_mismatch")
            written = 0
            with Path(destination).open("xb") as output:
                while True:
                    if cancel_event.is_set():
                        raise DependencyCancelled()
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > size or written > MAX_ASSET_BYTES:
                        raise DependencyError("依赖包下载超过允许大小", "archive_size_mismatch")
                    output.write(chunk)
                    progress(written, size)
            if written != size:
                raise DependencyError("依赖包下载不完整", "archive_size_mismatch")

    def _asset_plan(self, selected):
        tag = self._catalog["release_tag"]
        full = self._catalog["full_asset"]
        api = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{quote(tag, safe='')}"
        try:
            release = self._fetch_release(api)
            if not isinstance(release, dict) or not isinstance(release.get("assets"), list):
                raise ValueError("发布资源格式无效")
            item = next((item for item in release["assets"]
                         if isinstance(item, dict) and item.get("name") == full["name"]), {})
        except Exception:
            release, item = {}, {}
        sha = full.get("sha256") or asset_digest(item, release.get("body", ""))
        size = full.get("size") or item.get("size")
        if not _hex(sha) or isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_ASSET_BYTES:
            raise DependencyError("该版本没有可验证的完整依赖包，请使用 GitHub 手动更新入口", "asset_unavailable")
        plan = {"name": full["name"], "size": size, "sha256": sha, "groups": selected,
                "url": f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/{quote(tag, safe='')}/{quote(full['name'], safe='')}"}
        self._state_update(download_mode="full", download_bytes=size, message="将下载该版本的完整依赖包并安全更新托管组件")
        return [plan]

    def _extract(self, archive, staged, wanted):
        seen, found = set(), set()
        total = 0
        with zipfile.ZipFile(archive) as zipped:
            entries = zipped.infolist()
            if len(entries) > MAX_FILES:
                raise DependencyError("依赖包文件数量超限", "unsafe_archive")
            for info in entries:
                self._ensure_not_cancelled()
                name = info.filename
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or info.external_attr & 0x400:
                    raise DependencyError("依赖包不允许链接或重解析点", "unsafe_archive")
                if info.is_dir():
                    directory_name = name.rstrip("/")
                    if ("\\" in directory_name or not directory_name or directory_name.startswith("/")
                            or any(part in {"", ".", ".."} or ":" in part for part in directory_name.split("/"))
                            or not any(path.startswith(directory_name + "/") for path in self._catalog["files"])):
                        raise DependencyError("依赖包目录不安全或未声明", "unsafe_archive")
                    continue
                _relative(name)
                if name.casefold() in seen or name not in self._catalog["files"]:
                    raise DependencyError("依赖包存在重复或未声明文件", "unsafe_archive")
                seen.add(name.casefold())
                expected = self._catalog["files"][name]
                total += info.file_size
                if info.file_size != expected["size"] or total > MAX_UNPACKED_BYTES:
                    raise DependencyError("依赖包文件大小与可信清单不符", "unsafe_archive")
                if name not in wanted:
                    continue
                target = self._safe_path(staged.joinpath(*_relative(name)))
                target.parent.mkdir(parents=True, exist_ok=True)
                checksum, written = hashlib.sha256(), 0
                with zipped.open(info) as stream, target.open("xb") as output:
                    while chunk := stream.read(256 * 1024):
                        self._ensure_not_cancelled()
                        written += len(chunk)
                        if written > expected["size"]:
                            raise DependencyError("解压文件超过可信大小", "unsafe_archive")
                        checksum.update(chunk)
                        output.write(chunk)
                if written != expected["size"] or checksum.hexdigest() != expected["sha256"]:
                    raise DependencyError("依赖文件 SHA-256 校验失败：" + name, "file_hash_mismatch")
                found.add(name)
        if wanted - found:
            raise DependencyError("依赖包缺少所选组件文件", "missing_archive_files")

    def _validate_journal(self, directory, record):
        if (record.get("schema_version") != 1 or record.get("revision") != self._catalog["revision"]
                or record.get("operation_id") != directory.name or not isinstance(record.get("entries"), list)
                or len(record["entries"]) > MAX_FILES):
            raise DependencyError("依赖备份记录与当前清单不兼容，请保留备份并手动处理", "recovery_required")
        allowed = {path for group in self._groups.values() if group["installable"] and not group["source_only"] for path in group["files"]}
        seen = set()
        for entry in record["entries"]:
            if not isinstance(entry, dict) or entry.get("path") not in allowed or entry["path"] in seen:
                raise DependencyError("依赖备份记录包含未授权路径", "recovery_required")
            name = entry["path"]
            seen.add(name)
            if (not isinstance(entry.get("existed"), bool) or entry.get("new_sha256") != self._catalog["files"][name]["sha256"]
                    or (entry["existed"] and not _hex(entry.get("old_sha256")))):
                raise DependencyError("依赖备份记录摘要无效", "recovery_required")
            self._target(name)
            self._safe_path(directory / "backup" / Path(*_relative(name)))

    def _rollback(self, directory, record):
        self._validate_journal(directory, record)
        with self._lock:
            for entry in record["entries"]:
                self._results.pop(entry["path"], None)
        self._state_update(phase="rolling_back", message="正在恢复原依赖文件…", recovery_required=True)
        record["status"] = "rolling_back"
        self._write_json(directory / "journal.json", record)
        for entry in reversed(record["entries"]):
            target = self._target(entry["path"])
            backup = self._safe_path(directory / "backup" / Path(*_relative(entry["path"])))
            if entry["existed"]:
                if backup.is_file():
                    if _digest(backup) != entry["old_sha256"]:
                        raise DependencyError("依赖备份校验失败，请保留备份手动恢复", "recovery_required")
                    if target.exists() and (not target.is_file() or _digest(target) != entry["new_sha256"]):
                        raise DependencyError("依赖安装中断后文件又被修改，已保留备份，需手动处理", "recovery_required")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, target)
                elif not target.is_file() or _digest(target) != entry["old_sha256"]:
                    raise DependencyError("依赖原文件与备份不完整，请手动恢复", "recovery_required")
            elif target.exists():
                if not target.is_file() or _digest(target) != entry["new_sha256"]:
                    raise DependencyError("新增依赖安装后被修改，拒绝自动删除", "recovery_required")
                target.unlink()
        record["status"] = "rolled_back"
        self._write_json(directory / "journal.json", record)
        self._state_update(recovery_required=False)

    def _install(self, selected, replace_changed, *, preserve_user_updates=False):
        try:
            for directory, record in self._pending_transactions():
                self._rollback(directory, record)
        except Exception as error:
            self._state_update(recovery_required=True)
            raise DependencyError("未完成依赖维护需要恢复：" + str(error), "recovery_required") from error
        self._state_update(recovery_required=False)
        self._inspect_groups(selected, full=True)
        paths = sorted({path for group_id in selected for path in self._groups[group_id]["files"]})
        failures = [path for path in paths if self._results[path]["state"] == "error"]
        if failures:
            raise DependencyError("依赖文件路径或读取异常，请先处理：" + failures[0], "unsafe_path")
        changed = [path for path in paths if self._results[path]["state"] == "changed"]
        preserved = [path for path in changed if self._catalog["files"][path].get("user_updatable")
                     and (preserve_user_updates or not replace_changed)]
        confirmation = [path for path in changed if path not in preserved]
        self._state_update(preserved_files=preserved)
        if confirmation and not replace_changed:
            raise DependencyError("部分文件与发布基线不同，可能由用户更新；确认备份后才能替换", "changed_files", changed_files=changed[:100])
        needed = {path for path in paths if self._results[path]["state"] != "verified" and path not in preserved}
        if not needed:
            return
        self._ensure_not_cancelled()
        self._state_update(phase="resolving", progress=0, message="正在获取对应版本的可信依赖包信息…")
        plans = self._asset_plan(selected)
        directory = self._safe_path(self._work / "operations" / self._state["operation_id"])
        directory.mkdir(parents=True, exist_ok=False)
        record = None
        try:
            required = sum(self._catalog["files"][name]["size"] * 2 for name in needed) + sum(plan["size"] for plan in plans)
            if shutil.disk_usage(self._root).free < required + 16 * 1024 * 1024:
                raise DependencyError("磁盘空间不足以准备依赖和保留备份", "insufficient_space")
            staged = self._safe_path(directory / "staged")
            staged.mkdir()
            staged_names = set()
            for index, plan in enumerate(plans):
                self._ensure_not_cancelled()
                wanted = (needed & {path for group_id in plan["groups"] for path in self._groups[group_id]["files"]}) - staged_names
                if not wanted:
                    continue
                archive = directory / f"archive-{index}.zip"
                self._state_update(phase="downloading", progress=0,
                                   message="正在下载完整依赖包：" + plan["name"])
                self._download_asset(plan["url"], archive, size=plan["size"], cancel_event=self._cancel,
                                     progress=lambda done, total: self._state_update(progress=round(done / max(total, 1) * 100, 1)))
                self._ensure_not_cancelled()
                if archive.stat().st_size != plan["size"] or _digest(archive, self._cancel) != plan["sha256"]:
                    raise DependencyError("依赖包 SHA-256 或大小校验失败", "archive_hash_mismatch")
                self._state_update(phase="verifying", progress=0, message="正在逐文件验证所选依赖…")
                self._extract(archive, staged, wanted)
                staged_names.update(wanted)
                archive.unlink()
            self._ensure_not_cancelled()
            entries = []
            for name in sorted(needed):
                target = self._target(name)
                expected = self._results[name]
                existed = target.exists()
                old_sha = _digest(target, self._cancel) if existed and target.is_file() else None
                if existed != (expected["state"] == "changed") or (existed and old_sha != expected.get("actual_sha256")):
                    raise DependencyError("下载期间依赖文件被更改，已停止替换", "concurrent_modification")
                entries.append({"path": name, "existed": existed, "old_sha256": old_sha,
                                "new_sha256": self._catalog["files"][name]["sha256"]})
            planned_record = {"schema_version": 1, "revision": self._catalog["revision"], "operation_id": directory.name,
                              "status": "committing", "entries": entries}
            self._validate_journal(directory, planned_record)
            self._write_json(directory / "journal.json", planned_record)
            record = planned_record
            self._state_update(phase="installing", progress=0, message="校验通过，正在备份并安装所选组件…", recovery_required=True)
            for index, entry in enumerate(entries):
                self._ensure_not_cancelled()
                target = self._target(entry["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                if entry["existed"]:
                    backup = self._safe_path(directory / "backup" / Path(*_relative(entry["path"])))
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, backup)
                self._safe_path(target)
                os.replace(staged / Path(*_relative(entry["path"])), target)
                self._state_update(progress=round((index + 1) / len(entries) * 100, 1))
            self._ensure_not_cancelled()
            self._inspect_groups(selected, full=True)
            invalid = [name for name in needed if self._results[name]["state"] != "verified"]
            if invalid:
                raise DependencyError("安装后的依赖未通过复核：" + sorted(invalid)[0], "post_install_verification_failed")
            record["status"] = "complete"
            self._write_json(directory / "journal.json", record)
            self._state_update(recovery_required=False)
        except Exception:
            if record is not None:
                try:
                    self._rollback(directory, record)
                except Exception as error:
                    self._state_update(recovery_required=True)
                    raise DependencyError("依赖安装未完成，自动恢复也未完成；请保留备份并手动处理：" + str(error), "recovery_required") from error
            raise
        finally:
            if directory.exists() and not _is_link(directory):
                self._safe_path(directory)
                if record is None:
                    shutil.rmtree(directory)
                else:
                    stage = directory / "staged"
                    if stage.exists() and not _is_link(stage):
                        shutil.rmtree(stage)
                    for archive in directory.glob("archive-*.zip"):
                        if archive.is_file() and not _is_link(archive):
                            archive.unlink()
