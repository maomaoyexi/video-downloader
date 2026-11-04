"""Durable, credential-free recording journal. Media is never deleted here."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def public_url(value):
    try:
        parts = urlsplit(str(value))
        if parts.scheme in {"http", "https"}:
            return urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))
    except ValueError:
        pass
    return str(value)


def redact_command(command):
    sensitive = {"--cookie", "--cookies", "--cookies-from-browser", "--password",
                 "--video-password", "--username", "--http-basic-user", "--http-basic-pass",
                 "--webhook-url", "--add-header", "--add-headers", "--proxy", "--extractor-args",
                 "--ap-password", "--client-certificate-password"}
    result, hide = [], False
    for raw in command:
        value = str(raw)
        option = value.split("=", 1)[0]
        if hide:
            result.append("***")
            hide = False
        elif option in sensitive:
            result.append(option + "=***" if "=" in value else option)
            hide = "=" not in value
        else:
            result.append(public_url(value))
    return result


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())
    # Windows readers and antivirus scanners can briefly hold a handle without
    # FILE_SHARE_DELETE. Keep the previous complete journal until replace works.
    for attempt in range(6):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.02 * (attempt + 1))


class LiveSession:
    def __init__(self, root, platform, mode, url, probe=None):
        self.root = Path(root) / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.media = self.root / "media"
        self.media.mkdir()
        self.lock = threading.RLock()
        self.data = {
            "schema_version": 1, "job_id": self.root.name, "platform": platform,
            "mode": mode, "url": public_url(url), "probe": probe,
            "started_at": time.time(), "ended_at": None, "state": "recording",
            "owner_pid": os.getpid(),
            "parts": [], "outputs": [], "retries": [], "exit_codes": [], "ffprobe": [],
        }
        self.save()

    def save(self):
        with self.lock:
            atomic_json(self.root / "session.json", self.data)

    def event(self, kind, **data):
        with self.lock:
            with (self.root / "events.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps({"type": kind, "at": time.time(), **data},
                                        ensure_ascii=False, allow_nan=False) + "\n")

    def part(self, engine, command, reason="initial"):
        with self.lock:
            directory = self.media / f"part-{len(self.data['parts']) + 1:03d}"
            directory.mkdir()
            record = {"directory": str(directory), "engine": engine, "reason": reason,
                      "started_at": time.time(), "ended_at": None,
                      "process_cmd": redact_command(command), "exit_code": None}
            self.data["parts"].append(record)
            if reason != "initial":
                self.data["retries"].append({"reason": reason, "at": time.time()})
            self.save()
            return directory, record

    def finish(self, reason, report):
        with self.lock:
            self.data.update(ended_at=time.time(), state="finished", stop_reason=reason,
                             outputs=[f["path"] for f in report["files"]],
                             ffprobe=report["files"], conclusion=report["conclusion"])
            self.data["sidecars"] = [{"path": str(file), "size": file.stat().st_size}
                                     for file in self.media.rglob("*.xml") if file.is_file()]
            atomic_json(self.root / "integrity-report.json", report)
            self.save()


MEDIA_SUFFIXES = {".flv", ".mp4", ".mkv", ".webm", ".ts", ".m4a", ".mp3", ".aac", ".wav"}


def media_files(root):
    return sorted(p for p in Path(root).rglob("*") if p.is_file() and
                  (p.suffix.lower() in MEDIA_SUFFIXES or
                   (p.suffix == ".part" and p.with_suffix("").suffix.lower() in MEDIA_SUFFIXES)))


def _process_exists(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # Access denied is not proof that an owner died.
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def recover_interrupted(root):
    """Mark abandoned sessions explicitly; retain every byte and never auto-resume."""
    recovered = 0
    for path in Path(root).glob("*/session.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            if data.get("state") != "recording" or _process_exists(data.get("owner_pid")):
                continue
            files = [{"path": str(file), "size": file.stat().st_size, "valid": False,
                      "errors": ["application_interrupted_unverified"]} for file in media_files(path.parent / "media")]
            report = {"schema_version": 1, "conclusion": "failed", "stop_reason": "application_interrupted",
                      "scope": "recording_interval_only", "segment_completeness_verified": False,
                      "files": files, "exit_codes": data.get("exit_codes", []), "warnings": ["parts_retained"]}
            atomic_json(path.parent / "integrity-report.json", report)
            for private in ("withny.private.yaml", "danmaku/request.json", "danmaku/cookies.private", "danmaku/stop"):
                target = path.parent / private
                if target.resolve().is_relative_to(path.parent.resolve()):
                    target.unlink(missing_ok=True)
            data.update(state="finished", ended_at=time.time(), stop_reason="application_interrupted", conclusion="failed")
            atomic_json(path, data)
            recovered += 1
        except (OSError, ValueError, TypeError):
            continue
    return recovered


class RecordingStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._export_lock = threading.Lock()

    def export_comments(self, job_id, values):
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            return {"error": "无效的录制任务 id"}
        root = (self.root / job_id).resolve()
        if root.parent != self.root:
            return {"error": "无效的录制目录"}
        if not self._export_lock.acquire(blocking=False):
            return {"error": "正在导出弹幕，请稍后再试"}
        try:
            from .danmaku.reexport import export_saved
            return export_saved(root, job_id, values)
        finally:
            self._export_lock.release()

    def report(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            return None
        path = (self.root / job_id / "integrity-report.json").resolve()
        if not path.is_relative_to(self.root):
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def recent(self, limit=20):
        result = []
        for path in sorted(self.root.glob("*/session.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                parts = data.get("parts", [])
                result.append({"job_id": data["job_id"], "engine": parts[-1]["engine"] if parts else "",
                               "part": len(parts), "report_dir": str(path.parent),
                               "conclusion": data.get("conclusion"), "stop_reason": data.get("stop_reason"),
                               "comments": data.get("comments", {}),
                               "catch_up": data.get("catch_up", {}),
                               "report": str(path.parent / "integrity-report.json") if data.get("conclusion") else ""})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return result
