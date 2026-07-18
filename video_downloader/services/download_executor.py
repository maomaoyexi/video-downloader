import json
import os
import queue
import re
import subprocess
import threading
import time

from video_downloader.core.platform import clean_url, detect_platform, is_live_url, safe_decode


class DownloadExecutor:
    def __init__(
        self,
        tool_dir,
        exe_suffix,
        app_state,
        download_manager,
        build_command,
        log,
        update_progress,
        broadcast_download_state,
        add_history,
        cancel_idle_timer,
        start_idle_timer,
    ):
        self._tool_dir = tool_dir
        self._exe_suffix = exe_suffix
        self._app_state = app_state
        self._download_manager = download_manager
        self._build_command = build_command
        self._log = log
        self._update_progress = update_progress
        self._broadcast_download_state = broadcast_download_state
        self._add_history = add_history
        self._cancel_idle_timer = cancel_idle_timer
        self._start_idle_timer = start_idle_timer

    def start_download(self, url, bili_parts=None):
        url = clean_url(url)
        if not url:
            return {"error": "请输入有效的视频链接"}

        config_snapshot = self._app_state.config_snapshot()
        detected = detect_platform(url)
        effective_platform = detected if detected else config_snapshot["PLATFORM"]
        if detected:
            self._log(f"[自动识别] 检测到{detected}链接", "info")
        else:
            self._log(f"[提示] 未识别平台，使用: {config_snapshot['PLATFORM']}", "warn")

        missing = self._missing_dependency()
        if missing:
            return {"error": f"缺少依赖: {missing}"}

        is_live_download = is_live_url(url, detected)
        try:
            cmd = self._build_command(
                url,
                is_live=is_live_download,
                platform_override=effective_platform,
                config_override=config_snapshot,
                bili_parts=bili_parts,
            )
        except Exception as exc:
            return {"error": f"下载配置无效: {exc}"}

        handle = self._download_manager.begin("single")
        if handle is None:
            return {"error": "已有下载任务在运行"}
        self._cancel_idle_timer()
        self._broadcast_download_state()
        self._update_progress(0, "正在连接直播..." if is_live_download else "正在下载...")
        self._log(f"[下载] {url}", "info")
        try:
            threading.Thread(
                target=self._run_single,
                args=(handle, cmd, url, effective_platform, is_live_download),
                daemon=True,
            ).start()
        except Exception as exc:
            self._download_manager.finish(handle)
            self._broadcast_download_state()
            self._start_idle_timer()
            return {"error": f"下载线程启动失败: {exc}"}
        return {"ok": True}

    def fetch_bili_playlist(self, url):
        """获取 Bilibili 视频的分P列表。返回 {parts: [...], total: N} 或 {error: ...}。"""
        url = clean_url(url)
        if not url:
            return {"error": "无效链接"}
        config_snapshot = self._app_state.config_snapshot()
        # 构建轻量命令：仅提取播放列表元数据，不实际下载
        ytdlp = str(self._tool_dir / f"yt-dlp{self._exe_suffix}")
        cmd = [ytdlp, "--flat-playlist", "--dump-json", "--encoding", "utf-8"]
        if config_snapshot["USE_COOKIES"]:
            if config_snapshot["COOKIE_MODE"] == 1:
                cookie_file = self._tool_dir / "cookies.txt"
                if cookie_file.exists():
                    cmd += ["--cookies", str(cookie_file)]
            else:
                cmd += ["--cookies-from-browser", f"{config_snapshot['BROWSER_NAME']}:{config_snapshot['BROWSER_PROFILE']}"]
        if config_snapshot["PROXY_ENABLED"]:
            cmd += ["--proxy", f"{config_snapshot['PROXY_TYPE']}://{config_snapshot['PROXY_ADDR']}:{config_snapshot['PROXY_PORT']}"]
        cmd.append(url)
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(
                cmd, cwd=self._tool_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                startupinfo=startupinfo, creationflags=creationflags,
            )
            parts = []
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    parts.append({
                        "index": entry.get("playlist_index", len(parts) + 1),
                        "title": entry.get("title", f"P{len(parts) + 1}"),
                        "id": entry.get("id", ""),
                        "duration": entry.get("duration") or 0,
                    })
                except json.JSONDecodeError:
                    continue
            proc.wait(timeout=30)
            if proc.returncode != 0:
                stderr_output = proc.stderr.read().strip() if proc.stderr else ""
                return {"error": f"yt-dlp 进程退出码 {proc.returncode}" + (f": {stderr_output[:300]}" if stderr_output else "")}
            if not parts:
                return {"parts": [], "total": 0, "note": "未检测到分P列表，可能是单P视频"}
            return {"parts": parts, "total": len(parts)}
        except Exception as exc:
            return {"error": f"获取分P列表失败: {exc}"}

    def _run_single(self, handle, cmd, url, effective_platform, is_live_download):
        # 线程局部代际会随进度回调传递，旧工作线程无法覆盖新任务界面状态。
        self._app_state.download_thread_context.task_id = handle.generation
        video_title = ""
        proc = None
        try:
            proc = self._spawn(cmd)
            if not self._download_manager.publish_process(handle, proc):
                self.kill_process_tree(proc)
                return
            line_q, read_done = self._start_reader(proc)
            live_connected = False
            live_start_time = time.time()
            live_size = ""
            live_speed = ""
            live_frag = ""

            def fmt_live_status():
                elapsed = int(time.time() - live_start_time)
                mins, secs = divmod(elapsed, 60)
                hrs, mins = divmod(mins, 60)
                time_str = f"{hrs}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins}:{secs:02d}"
                parts = [part for part in [live_size, live_frag, live_speed] if part]
                parts.append(f"录制 {time_str}")
                return "直播录制中 - " + " | ".join(parts), live_speed

            while not read_done.is_set() or not line_q.empty():
                if handle.cancel_event.is_set():
                    break
                try:
                    line = line_q.get(timeout=0.5)
                except queue.Empty:
                    if live_connected:
                        status_text, speed = fmt_live_status()
                        self._update_progress(-1, status_text, speed=speed, eta="")
                    continue
                line = line.strip()
                if not line:
                    continue
                if is_live_download and not live_connected and ("Connecting to WebSocket" in line or "Downloading m3u8" in line):
                    live_connected = True
                    live_start_time = time.time()
                    self._update_progress(-1, "直播录制中...")

                is_error = "ERROR" in line
                is_warning = "WARNING" in line
                has_pct = bool(re.search(r"\d+(?:\.\d+)?%", line))
                has_ffmpeg_progress = is_live_download and (
                    re.search(r"(?:size|Lsize)=\s*\S+", line)
                    or re.search(r"frame=\s*\d+", line) and re.search(r"fps=", line)
                ) and any(value in line for value in ["time=", "bitrate=", "speed=", "fps="])
                has_ytdlp_live = is_live_download and re.search(r"\d+\.?\d*\s*[KMG]iB", line) and re.search(r"\d+\.?\d*\s*[KMG]iB/s", line)
                has_fragment = is_live_download and "fragment" in line.lower() and ("Downloading" in line or "Downloaded" in line)
                is_live_progress = has_ytdlp_live or has_ffmpeg_progress or has_fragment
                is_keyword = any(kw in line for kw in [
                    "Destination:", "Merging formats", "Deleting original", "Extracting URL",
                    "Downloading webpage", "Connecting to WebSocket", "has already been recorded",
                    "video only", "audio only", "Resuming",
                ])

                if is_error:
                    self._log(line, "error")
                elif is_warning:
                    self._log(line, "warn")
                elif not has_pct and not (is_live_progress and not is_keyword):
                    if is_keyword and len(line) < 200:
                        self._log(line, "info")
                    elif live_connected and len(line) < 200 and not any(skip in line for skip in ["[download]", "[hls]", "[fragment]"]):
                        self._log(line, "info")

                title_match = re.search(r"\[download\] Destination: (.+)", line)
                if not title_match:
                    title_match = re.search(r'\[Merger\] Merging formats into "(.+)"', line)
                if title_match:
                    video_title = os.path.basename(title_match.group(1).replace('"', "").replace("'", ""))
                    video_title = re.sub(r"\s*\[[a-zA-Z0-9_-]{6,}\]\.\w+$", "", video_title)

                progress_match = re.search(r"(\d+(?:\.\d+)?)%", line)
                if progress_match:
                    speed_match = re.search(r"(\d+(?:\.\d+)?\s*[KMG]iB/s)", line)
                    eta_match = re.search(r"ETA (\d+:\d+)", line)
                    self._update_progress(
                        float(progress_match.group(1)) / 100,
                        speed=speed_match.group(1).replace(" ", "") if speed_match else "",
                        eta=eta_match.group(1) if eta_match else "",
                    )
                elif is_live_progress:
                    if has_ytdlp_live:
                        size_match = re.search(r"(\d+\.?\d*\s*[KMG]iB)", line)
                        speed_match = re.search(r"(\d+\.?\d*\s*[KMG]iB/s)", line)
                        if size_match:
                            live_size = "已下载 " + size_match.group(1).replace(" ", "")
                        if speed_match:
                            live_speed = speed_match.group(1).replace(" ", "")
                    elif has_ffmpeg_progress:
                        size_match = re.search(r"(?:size|Lsize)=\s*(\d+\.?\d*\s*[kKmMgG][bB]?|N/A)", line)
                        speed_match = re.search(r"speed=\s*(\d+\.?\d*x)", line)
                        fps_match = re.search(r"fps=\s*(\d+)", line)
                        bitrate_match = re.search(r"bitrate=\s*(\d+\.?\d*\s*kbits/s)", line)
                        time_match = re.search(r"time=(\d+:\d+:\d+\.\d+|\d+:\d+\.\d+)", line)
                        if size_match and size_match.group(1) != "N/A":
                            live_size = "已下载 " + size_match.group(1).replace(" ", "")
                        if speed_match:
                            live_speed = speed_match.group(1).replace(" ", "")
                        elif fps_match:
                            live_speed = f"{fps_match.group(1)} fps"
                        elif bitrate_match:
                            live_speed = bitrate_match.group(1).replace(" ", "")
                        if time_match:
                            parts = time_match.group(1).split(".")[0].split(":")
                            if len(parts) == 3:
                                live_start_time = time.time() - (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
                    elif has_fragment:
                        fragment_match = re.search(r"fragment\s+(\d+)", line, re.IGNORECASE)
                        if fragment_match:
                            live_frag = f"分片 {fragment_match.group(1)}"
                    status_text, speed = fmt_live_status()
                    self._update_progress(-1, status_text, speed=speed, eta="")

            self._close_process(proc)
            rc = proc.returncode if proc.returncode is not None else -1
            if handle.cancel_event.is_set():
                self._log("[停止] 下载已取消", "warn")
                self._update_progress(0, "已停止", "", "")
            elif rc == 0:
                self._log("[完成] 下载成功！", "success")
                self._update_progress(1, "下载完成", "", "")
                self._add_history(url, video_title, effective_platform, "success")
            else:
                self._log(f"[错误] 下载结束，退出码: {rc}", "error")
                self._update_progress(0, f"失败 (退出码 {rc})", "", "")
                self._add_history(url, video_title, effective_platform, "fail")
        except Exception as exc:
            self._log(f"[异常] {exc}", "error")
            self._update_progress(0, "异常终止", "", "")
            try:
                self._add_history(url, video_title, effective_platform, "fail")
            except Exception:
                pass
            self.kill_process_tree(proc)
        finally:
            self._finish(handle, proc)

    def batch_download(self, urls, bili_parts_map=None):
        urls = [url for raw_url in urls if (url := clean_url(raw_url))]
        if not urls:
            return {"error": "没有有效的视频链接"}
        missing = self._missing_dependency()
        if missing:
            return {"error": f"缺少依赖: {missing}"}
        handle = self._download_manager.begin("batch")
        if handle is None:
            return {"error": "已有下载任务在运行"}
        config_snapshot = self._app_state.config_snapshot()
        self._cancel_idle_timer()
        self._broadcast_download_state()
        stats = self._app_state.batch_stats
        stats.clear()
        stats.update({"ok": 0, "fail": 0, "total": len(urls), "current": 0})
        try:
            threading.Thread(target=self._run_batch, args=(handle, urls, config_snapshot, stats, bili_parts_map or {}), daemon=True).start()
        except Exception as exc:
            self._download_manager.finish(handle)
            self._broadcast_download_state()
            self._start_idle_timer()
            return {"error": f"下载线程启动失败: {exc}"}
        return {"ok": True, "total": len(urls)}

    def _run_batch(self, handle, urls, config_snapshot, stats, bili_parts_map=None):
        # 批量统计与进度共用任务代际，避免停止后迟到事件污染下一任务。
        self._app_state.download_thread_context.task_id = handle.generation
        stopped = False

        def update_stats():
            if getattr(self._app_state.download_thread_context, "task_id", handle.generation) != self._download_manager.snapshot()["generation"]:
                return
            self._app_state.publish({"type": "stats", "data": dict(stats)})

        try:
            self._log(f"[批量下载] 开始，共 {len(urls)} 个链接", "info")
            update_stats()
            for index, url in enumerate(urls, 1):
                if handle.cancel_event.is_set():
                    stopped = True
                    self._log("[批量下载] 已停止", "warn")
                    break
                stats["current"] = index
                update_stats()
                detected = detect_platform(url)
                effective_platform = detected if detected else config_snapshot["PLATFORM"]
                if detected:
                    self._log(f"[{index}/{len(urls)}] [自动识别] {detected}", "info")
                else:
                    self._log(f"[{index}/{len(urls)}] 未识别平台，使用: {config_snapshot['PLATFORM']}", "warn")
                self._log(f"[{index}/{len(urls)}] 下载: {url}", "info")
                self._update_progress(0, f"批量下载 {index}/{len(urls)}")
                proc = None
                try:
                    bili_parts_for_url = (bili_parts_map or {}).get(url)
                    cmd = self._build_command(
                        url,
                        is_live=is_live_url(url, detected),
                        platform_override=effective_platform,
                        config_override=config_snapshot,
                        bili_parts=bili_parts_for_url,
                    )
                    proc = self._spawn(cmd)
                    if not self._download_manager.publish_process(handle, proc):
                        stopped = True
                        self.kill_process_tree(proc)
                        break
                    line_q, read_done = self._start_reader(proc)
                    while not read_done.is_set() or not line_q.empty():
                        if handle.cancel_event.is_set():
                            break
                        try:
                            line = line_q.get(timeout=0.5).strip()
                        except queue.Empty:
                            continue
                        if not line:
                            continue
                        if "ERROR" in line:
                            self._log(f"  {line}", "error")
                        elif "WARNING" in line:
                            self._log(f"  {line}", "warn")
                        progress_match = re.search(r"(\d+(?:\.\d+)?)%", line)
                        if progress_match:
                            overall = ((index - 1) + float(progress_match.group(1)) / 100) / len(urls)
                            self._update_progress(overall, f"批量下载 {index}/{len(urls)}")
                    self._close_process(proc)
                    self._download_manager.clear_process(handle, proc)
                    if handle.cancel_event.is_set():
                        stopped = True
                        self._log(f"[{index}/{len(urls)}] ✗ 已取消", "warn")
                        update_stats()
                        break
                    rc = proc.returncode if proc.returncode is not None else -1
                    if rc == 0:
                        stats["ok"] += 1
                        self._log(f"[{index}/{len(urls)}] ✓ 完成", "success")
                        self._add_history(url, "", effective_platform, "success")
                    else:
                        stats["fail"] += 1
                        self._log(f"[{index}/{len(urls)}] ✗ 失败 (退出码 {rc})", "error")
                        self._add_history(url, "", effective_platform, "fail")
                    update_stats()
                except Exception as exc:
                    stats["fail"] += 1
                    self._log(f"[{index}/{len(urls)}] ✗ 异常: {exc}", "error")
                    try:
                        self._add_history(url, "", effective_platform, "fail")
                    except Exception:
                        pass
                    update_stats()
                    if proc is not None:
                        self.kill_process_tree(proc)
                    self._download_manager.clear_process(handle, proc)
            if stopped:
                self._log("[批量下载] 已停止", "warn")
                self._update_progress(0, "已停止")
            else:
                self._log(f"[批量下载] 完成: 成功{stats['ok']} 失败{stats['fail']} 总计{stats['total']}", "success")
                status = "批量下载完成" if stats["ok"] == stats["total"] else f"批量下载完成 (成功{stats['ok']}/{stats['total']})"
                self._update_progress(1, status)
            update_stats()
        except Exception as exc:
            self._log(f"[批量下载] 异常: {exc}", "error")
            self._update_progress(0, "异常终止")
        finally:
            self._finish(handle, None)

    def stop_download(self):
        ticket = self._download_manager.request_stop()
        if not ticket.active:
            return {"ok": True, "stopping": False}
        self._broadcast_download_state()
        if ticket.process is not None:
            self.kill_process_tree(ticket.process)
            self._log("[停止] 正在停止下载...", "warn")
        else:
            self._log("[停止] 正在取消...", "warn")
        return {"ok": True, "stopping": True}

    def kill_process_tree(self, process):
        if process is None:
            return
        try:
            if process.poll() is None:
                if os.name == "nt":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                    creationflags = subprocess.CREATE_NO_WINDOW
                    try:
                        subprocess.run(["taskkill", "/T", "/PID", str(process.pid)], capture_output=True, timeout=2, startupinfo=startupinfo, creationflags=creationflags)
                    except Exception:
                        pass
                    try:
                        process.wait(timeout=1)
                    except Exception:
                        pass
                    if process.poll() is None:
                        try:
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=5, startupinfo=startupinfo, creationflags=creationflags)
                        except Exception:
                            pass
                        try:
                            process.wait(timeout=3)
                        except Exception:
                            pass
                if process.poll() is None:
                    try:
                        process.kill()
                        process.wait(timeout=2)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            if process.stdout:
                process.stdout.close()
        except Exception:
            pass

    def _missing_dependency(self):
        for dependency in ["yt-dlp", "ffmpeg", "ffprobe"]:
            filename = f"{dependency}{self._exe_suffix}"
            if not (self._tool_dir / filename).exists():
                return filename
        return None

    def _spawn(self, cmd):
        env = os.environ.copy()
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"})
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(
            cmd,
            cwd=self._tool_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

    def _start_reader(self, process):
        # 独立读线程持续排空子进程管道，避免主线程处理日志时令子进程写端阻塞。
        line_q = queue.Queue(maxsize=1024)
        read_done = threading.Event()

        def enqueue(line):
            try:
                line_q.put_nowait(line)
            except queue.Full:
                # 消费端落后时保留最新输出，限制高频进度日志的内存占用。
                try:
                    line_q.get_nowait()
                    line_q.put_nowait(line)
                except queue.Empty:
                    pass

        def read_output():
            buffer = bytearray()
            while True:
                try:
                    chunk = os.read(process.stdout.fileno(), 4096)
                except Exception:
                    chunk = None
                if not chunk:
                    if buffer:
                        try:
                            enqueue(safe_decode(buffer))
                        except Exception:
                            pass
                    break
                for value in chunk:
                    if value in (0x0D, 0x0A):
                        if buffer:
                            try:
                                enqueue(safe_decode(buffer))
                            except Exception:
                                pass
                            buffer = bytearray()
                    else:
                        buffer.append(value)
            read_done.set()

        threading.Thread(target=read_output, daemon=True).start()
        return line_q, read_done

    @staticmethod
    def _close_process(process):
        try:
            if process.poll() is None:
                process.wait(timeout=5)
        except Exception:
            pass
        try:
            process.stdout.close()
        except Exception:
            pass

    def _finish(self, handle, process):
        self._download_manager.clear_process(handle, process)
        # 仅当前代际有权广播结束态，旧线程迟到收尾不会伪造“空闲”。
        if self._download_manager.finish(handle):
            self._broadcast_download_state()
        if not self._app_state.has_sse_clients():
            self._start_idle_timer()
