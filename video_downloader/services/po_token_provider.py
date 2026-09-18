"""Lifecycle management for the local BgUtils YouTube PO Token provider."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections import deque
from urllib.request import ProxyHandler, build_opener

from video_downloader.core.paths import AppPaths


class PoTokenProviderService:
    """Start the bundled BgUtils HTTP provider on demand and stop owned processes."""

    HOST = "127.0.0.1"
    PORT = 4416
    START_TIMEOUT = 20.0

    def __init__(self, tool_dir, log):
        self._tool_dir = tool_dir
        self._paths = AppPaths(tool_dir)
        self._log = log
        self._lock = threading.RLock()
        self._process = None
        self._output_tail = deque(maxlen=12)
        self._active_base_url = None

    @property
    def base_url(self):
        return self._active_base_url or f"http://{self.HOST}:{self.PORT}"

    @property
    def _candidate_base_urls(self):
        # Upstream currently binds to "::". Some Windows systems expose that socket
        # on IPv4 too, while others only accept ::1, so probe both loopback families.
        return (
            f"http://{self.HOST}:{self.PORT}",
            f"http://[::1]:{self.PORT}",
        )

    def _ping(self, timeout=0.8):
        try:
            # Provider health checks must never inherit a system/user proxy.
            opener = build_opener(ProxyHandler({}))
            for base_url in self._candidate_base_urls:
                try:
                    with opener.open(f"{base_url}/ping", timeout=timeout) as response:
                        if response.status != 200:
                            continue
                        data = json.loads(response.read().decode("utf-8"))
                    if isinstance(data, dict) and data.get("version"):
                        self._active_base_url = base_url
                        return data
                except Exception:
                    continue
            return None
        except Exception:
            return None

    @staticmethod
    def _windows_process_options():
        if os.name != "nt":
            return None, 0
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo, subprocess.CREATE_NO_WINDOW

    def _drain_output(self, process):
        try:
            for line in iter(process.stdout.readline, ""):
                line = line.strip()
                if line:
                    self._output_tail.append(line)
        except Exception:
            pass
        finally:
            try:
                process.stdout.close()
            except Exception:
                pass

    def _dependency_error(self):
        deno = self._paths.executable("deno", ".exe" if os.name == "nt" else "")
        server_dir = self._paths.dependency("bgutil-ytdlp-pot-provider/server")
        node_modules = server_dir / "node_modules"
        main_script = server_dir / "src" / "main.ts"
        plugin = self._paths.dependency("yt-dlp-plugins/bgutil-ytdlp-pot-provider.zip")
        missing = []
        for path, label in (
            (deno, "dependency/deno.exe" if os.name == "nt" else "dependency/deno"),
            (main_script, "dependency/bgutil-ytdlp-pot-provider/server/src/main.ts"),
            (node_modules, "dependency/bgutil-ytdlp-pot-provider/server/node_modules"),
            (plugin, "dependency/yt-dlp-plugins/bgutil-ytdlp-pot-provider.zip"),
        ):
            if not path.exists():
                missing.append(label)
        if missing:
            return "PO Token Provider 缺少依赖: " + "、".join(missing)
        return None

    def ensure_running(self):
        """Ensure the HTTP provider is reachable, starting it if necessary."""
        with self._lock:
            ping = self._ping()
            if ping:
                if self._process is None:
                    self._log(
                        f"[PO Token] 已连接现有 Provider v{ping['version']} ({self.base_url})",
                        "success",
                    )
                return {
                    "ok": True,
                    "version": ping["version"],
                    "reused": True,
                    "base_url": self.base_url,
                }

            error = self._dependency_error()
            if error:
                return {"error": error}

            if self._process is not None and self._process.poll() is None:
                # A process exists but stopped answering; terminate it before restarting.
                self._stop_owned_process(self._process)
                self._process = None

            deno = self._paths.executable("deno", ".exe" if os.name == "nt" else "")
            node_modules = self._paths.dependency(
                "bgutil-ytdlp-pot-provider/server/node_modules"
            )
            command = [
                str(deno),
                "run",
                "--allow-env",
                "--allow-net",
                "--allow-ffi=.",
                "--allow-read=.",
                "../src/main.ts",
                "--port",
                str(self.PORT),
            ]
            startupinfo, creationflags = self._windows_process_options()
            self._output_tail.clear()
            try:
                env = self._paths.subprocess_env()
                process = subprocess.Popen(
                    command,
                    cwd=node_modules,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                )
            except Exception as exc:
                return {"error": f"PO Token Provider 启动失败: {exc}"}

            self._process = process
            threading.Thread(
                target=self._drain_output,
                args=(process,),
                daemon=True,
            ).start()

            deadline = time.monotonic() + self.START_TIMEOUT
            while time.monotonic() < deadline:
                ping = self._ping()
                if ping:
                    self._log(
                        f"[PO Token] Provider v{ping['version']} 已启动 ({self.base_url})",
                        "success",
                    )
                    return {
                        "ok": True,
                        "version": ping["version"],
                        "reused": False,
                        "base_url": self.base_url,
                    }
                if process.poll() is not None:
                    detail = self._failure_detail()
                    self._process = None
                    return {"error": f"PO Token Provider 启动后异常退出{detail}"}
                time.sleep(0.2)

            self._stop_owned_process(process)
            self._process = None
            detail = self._failure_detail()
            return {"error": f"PO Token Provider 启动超时，无法访问 {self.base_url}/ping{detail}"}

    def _failure_detail(self):
        if not self._output_tail:
            return ""
        return f"（{self._output_tail[-1][:300]}）"

    @staticmethod
    def _stop_owned_process(process):
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            startupinfo, creationflags = PoTokenProviderService._windows_process_options()
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    timeout=2,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                )
            except Exception:
                pass
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def stop(self):
        """Stop only a provider process started by this application."""
        with self._lock:
            process = self._process
            self._process = None
            if process is None:
                return
            self._stop_owned_process(process)
            self._log("[PO Token] Provider 已停止", "info")
