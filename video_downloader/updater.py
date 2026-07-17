import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib import request as urllib_request

from .constants import (
    EXE_NAME,
    GITHUB_OWNER,
    GITHUB_REPO,
    MAX_UPDATE_SIZE,
    VERSION,
    VERSION_NUM,
)
from .utils import asset_digest, is_allowed_update_url, parse_version_tag, version_num_to_str


class UpdaterService:
    def __init__(self, download_manager, emit_event, log, broadcast_download_state, kill_process_tree):
        self._download_manager = download_manager
        self._emit_event = emit_event
        self._log = log
        self._broadcast_download_state = broadcast_download_state
        self._kill_process_tree = kill_process_tree
        # 流程锁在外、状态锁在内，禁止反向嵌套以免死锁。
        self._check_lock = threading.Lock()
        self._download_lock = threading.Lock()
        self._status_lock = threading.RLock()
        self._status = {
            "checking": False,
            "update_available": False,
            "latest_version": None,
            "latest_version_num": 0,
            "release_notes": "",
            "download_url": None,
            "download_size": 0,
            "download_digest": None,
            "downloading": False,
            "download_progress": 0,
            "download_speed": "",
            "downloaded_size": 0,
            "total_size": 0,
            "update_done": False,
            "error": None,
        }

    def snapshot(self):
        with self._status_lock:
            return dict(self._status)

    def is_checking(self):
        with self._status_lock:
            return self._status["checking"]

    def _update_status(self, values):
        with self._status_lock:
            self._status.update(values)

    def _fetch_url(self, url, timeout=10):
        req = urllib_request.Request(url, headers={
            "User-Agent": "VideoDownloader-UpdateChecker/1.0",
            "Accept": "application/json, text/plain, */*",
        })
        try:
            with urllib_request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    def _download_file(self, url, dest_path, progress_callback=None):
        req = urllib_request.Request(url, headers={"User-Agent": "VideoDownloader-Updater/1.0"})
        try:
            with urllib_request.urlopen(req, timeout=30) as resp:
                if not is_allowed_update_url(resp.geturl()):
                    return False, "更新下载地址重定向到了不可信来源"
                total = int(resp.headers.get("Content-Length", 0))
                if total > MAX_UPDATE_SIZE:
                    return False, "更新文件超过允许的大小限制"
                downloaded = 0
                start_time = time.time()
                last_report = 0
                digest = hashlib.sha256()
                with open(dest_path, "wb") as file:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        if downloaded + len(chunk) > MAX_UPDATE_SIZE:
                            raise ValueError("更新文件超过允许的大小限制")
                        file.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        elapsed = now - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        if progress_callback and (now - last_report >= 0.2 or downloaded == total):
                            progress_callback(downloaded, total, speed)
                            last_report = now
                if total and downloaded != total:
                    return False, f"更新文件下载不完整: {downloaded}/{total} 字节"
                return True, {"size": downloaded, "sha256": digest.hexdigest()}
        except Exception as exc:
            try:
                os.remove(dest_path)
            except OSError:
                pass
            return False, str(exc)

    def _is_valid_exe(self, path):
        try:
            if os.path.getsize(path) < 1024 * 1024:
                return False
            with open(path, "rb") as file:
                return file.read(2) == b"MZ"
        except Exception:
            return False

    def _release_info(self, data):
        tag = data.get("tag_name", "")
        version_num = parse_version_tag(tag)
        if version_num <= VERSION_NUM:
            return None
        assets = data.get("assets") or []
        exe_assets = [asset for asset in assets if str(asset.get("name", "")).lower().endswith(".exe")]
        asset = next((item for item in exe_assets if "gui" in str(item.get("name", "")).lower()), None)
        if asset is None and exe_assets:
            asset = exe_assets[0]
        notes = data.get("body") or ""
        return {
            "tag": tag,
            "ver_num": version_num,
            "notes": notes,
            "download_url": (asset or {}).get("browser_download_url") or (asset or {}).get("url"),
            "download_size": int((asset or {}).get("size") or 0),
            "download_digest": asset_digest(asset or {}, notes),
        }

    def check_update(self):
        if not self._check_lock.acquire(blocking=False):
            status = self.snapshot()
            return {"has_update": status["update_available"], "checking": True}
        self._update_status({"checking": True, "error": None})
        release_info = None
        error = None
        try:
            api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
            text = self._fetch_url(api_url, timeout=8)
            if text:
                release_info = self._release_info(json.loads(text))
            else:
                error = "GitHub: 请求失败"
        except Exception as exc:
            error = f"GitHub: {exc}"
        finally:
            self._update_status({"checking": False})
            self._check_lock.release()
        if release_info:
            self._update_status({
                "update_available": True,
                "latest_version": release_info["tag"],
                "latest_version_num": release_info["ver_num"],
                "release_notes": release_info["notes"],
                "download_url": release_info["download_url"],
                "download_size": release_info["download_size"],
                "download_digest": release_info["download_digest"],
            })
            return {
                "has_update": True,
                "current_version": VERSION,
                "latest_version": release_info["tag"],
                "release_notes": release_info["notes"],
                "download_url": release_info["download_url"],
                "download_size": release_info["download_size"],
                "download_digest": release_info["download_digest"],
            }
        self._update_status({
            "update_available": False,
            "latest_version": None,
            "latest_version_num": 0,
            "release_notes": "",
            "download_url": None,
            "download_size": 0,
            "download_digest": None,
            "error": error,
        })
        return {
            "has_update": False,
            "current_version": VERSION,
            "latest_version": version_num_to_str(VERSION_NUM),
            "error": error,
        }

    def do_update(self):
        with self._download_lock:
            status = self.snapshot()
            if status["downloading"]:
                return {"error": "已在下载更新中"}
            url = status.get("download_url")
            if not status.get("update_available") or not url:
                return {"error": "没有可用的下载链接，请先检查更新"}
            if not is_allowed_update_url(url):
                return {"error": "更新下载地址不在可信来源列表中"}
            expected_size = int(status.get("download_size") or 0)
            expected_digest = str(status.get("download_digest") or "").lower()
            if expected_size > MAX_UPDATE_SIZE:
                return {"error": "更新文件超过允许的大小限制"}
            if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
                return {"error": "发布信息缺少有效的 SHA-256，已禁止自动更新"}
            if not self._download_manager.suspend():
                return {"error": "请先停止当前下载任务再更新"}
            self._broadcast_download_state()
            self._update_status({
                "downloading": True,
                "download_progress": 0,
                "download_speed": "",
                "error": None,
                "update_done": False,
            })

        def progress_callback(downloaded, total, speed):
            percent = (downloaded / total * 100) if total > 0 else 0
            if speed > 1024 * 1024:
                speed_text = f"{speed / (1024 * 1024):.1f} MB/s"
            elif speed > 1024:
                speed_text = f"{speed / 1024:.0f} KB/s"
            elif speed > 0:
                speed_text = f"{speed:.0f} B/s"
            else:
                speed_text = ""
            self._update_status({
                "download_progress": percent,
                "downloaded_size": downloaded,
                "total_size": total,
                "download_speed": speed_text,
            })
            self._emit_event("update_progress", {
                "percent": percent,
                "speed": speed_text,
                "downloaded": downloaded,
                "total": total,
            })

        def fail_update(message, tmp_dir=None):
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            status = self.snapshot()
            self._update_status({"error": message, "downloading": False})
            self._download_manager.resume()
            self._broadcast_download_state()
            self._log(f"[更新] {message}", "error")
            self._emit_event("update_progress", {
                "percent": status["download_progress"],
                "error": message,
            })

        def download_and_replace():
            tmp_dir = None
            try:
                tmp_dir = tempfile.mkdtemp(prefix="video_downloader_update_")
                os.makedirs(tmp_dir, exist_ok=True)
                status = self.snapshot()
                new_exe_name = re.sub(r"v\d+\.\d+\.\d+", status.get("latest_version", "new"), EXE_NAME, count=1)
                tmp_path = os.path.join(tmp_dir, f"_update_{new_exe_name}")
                self._log(f"[更新] 开始下载新版本 {status.get('latest_version', '')}...", "info")
                ok, result = self._download_file(url, tmp_path, progress_callback=progress_callback)
                if not ok:
                    fail_update(f"下载失败: {result}", tmp_dir)
                    return
                if expected_size and result["size"] != expected_size:
                    fail_update("更新文件大小与发布信息不一致", tmp_dir)
                    return
                if not secrets.compare_digest(result["sha256"], expected_digest):
                    fail_update("更新文件 SHA-256 校验失败", tmp_dir)
                    return
                if not self._is_valid_exe(tmp_path):
                    fail_update("下载文件不是有效的 Windows EXE", tmp_dir)
                    return
                self._update_status({"download_progress": 100})
                self._log("[更新] 下载完成，准备替换...", "success")
                current_exe = sys.executable if getattr(sys, "frozen", False) else None
                if current_exe and os.name == "nt":
                    # 主进程无法覆盖自身，交由 BAT 等待退出后替换并重启。
                    replace_bat = os.path.join(tmp_dir, "_update_replace.bat")
                    target_path = os.path.join(os.path.dirname(current_exe), os.path.basename(current_exe))
                    current_pid = os.getpid()
                    error_path = os.path.join(tmp_dir, "_update_error.txt")
                    bat_content = f'''@echo off
chcp 936 >nul
echo 正在更新...
timeout /t 2 /nobreak >nul
:wait
tasklist /fi "PID eq {current_pid}" 2>nul | find "{current_pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
copy /y "{tmp_path}" "{target_path}" >nul
if errorlevel 1 (
    echo 更新失败！
    pause
    exit /b 1
)
echo 更新完成！正在启动新版本...
start "" "{target_path}"
if errorlevel 1 (
    echo 无法启动新版本，请手动运行："{target_path}" > "{error_path}"
    exit /b 1
)
del /q "{tmp_path}"
del "%~f0"
rmdir "{tmp_dir}"
'''
                    with open(replace_bat, "w", encoding="gbk") as file:
                        file.write(bat_content)
                    self._update_status({"update_done": True, "downloading": False})
                    self._log("[更新] 更新已准备就绪，程序将在关闭后自动替换并重启", "success")
                    self._emit_event("update_progress", {
                        "percent": 100,
                        "done": True,
                        "message": "更新下载完成！程序将自动重启以完成更新。",
                    })

                    def exit_and_update():
                        time.sleep(1.5)
                        try:
                            # 先启动接管脚本，再退出主进程，确保更新链路不断档。
                            subprocess.Popen(
                                ["cmd.exe", "/c", replace_bat],
                                cwd=tempfile.gettempdir(),
                                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                            )
                        except Exception as exc:
                            self._update_status({"update_done": False})
                            fail_update(f"无法启动更新替换脚本: {exc}", tmp_dir)
                            return
                        self._emit_event("exit")
                        time.sleep(0.5)
                        ticket = self._download_manager.request_stop()
                        self._kill_process_tree(ticket.process)
                        os._exit(0)

                    try:
                        threading.Thread(target=exit_and_update, daemon=True).start()
                    except Exception as exc:
                        self._update_status({"update_done": False})
                        fail_update(f"无法启动更新线程: {exc}", tmp_dir)
                else:
                    self._update_status({"update_done": True, "downloading": False})
                    self._download_manager.resume()
                    self._broadcast_download_state()
                    self._log(f"[更新] 新版本已下载到: {tmp_path}", "success")
                    self._log("[更新] 开发模式，请手动替换文件后重启", "warn")
                    self._emit_event("update_progress", {
                        "percent": 100,
                        "done": True,
                        "message": f"新版本已下载到: {tmp_path}，请手动替换后重启。",
                    })
            except Exception as exc:
                fail_update(f"更新异常: {exc}", tmp_dir)

        try:
            threading.Thread(target=download_and_replace, daemon=True).start()
        except Exception as exc:
            message = f"无法启动更新线程: {exc}"
            fail_update(message)
            return {"error": message}
        return {"ok": True, "message": "开始下载更新..."}

    def start_check_thread(self, silent=True):
        def worker():
            result = self.check_update()
            if result.get("has_update"):
                self._log(f"[更新] 发现新版本 {result['latest_version']}！", "warn")
                self._emit_event("update_available", result)
            elif not silent:
                self._log("[更新] 当前已是最新版本", "info")

        threading.Thread(target=worker, daemon=True).start()
