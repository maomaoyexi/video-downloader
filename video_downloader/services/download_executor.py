import json
import os
import queue
import re
import subprocess
import threading
import time

from video_downloader.core.platform import clean_url, detect_platform, is_live_url, safe_decode


def _win_startup_info():
    """Windows 下隐藏子进程窗口（全局函数，避免在多处重复）。"""
    if os.name != "nt":
        return None, 0
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    creationflags = subprocess.CREATE_NO_WINDOW
    return startupinfo, creationflags


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
        emit_event,
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
        self._emit_event = emit_event
        # 批量下载密码阻塞等待机制
        self._password_event = threading.Event()
        self._password_value: str | None = None
        self._password_lock = threading.Lock()
        self._waiting_for_password = False

    def start_download(self, url, bili_parts=None, tc_password=None):
        url = clean_url(url)
        if not url:
            return {"error": "请输入有效的视频链接"}

        verbose = bool(tc_password)  # 弹窗密码重试时开启 yt-dlp 详细日志用于诊断
        config_snapshot = self._app_state.config_snapshot()
        # 本次下载的临时密码覆盖（来自密码弹窗），不写入持久配置。
        if tc_password:
            config_snapshot = dict(config_snapshot, TC_PASSWORD=tc_password)
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

        # 弹窗重试时开启 yt-dlp --verbose 以便诊断格式/密码问题。
        if verbose:
            cmd += ["--verbose"]

        handle = self._download_manager.begin("single")
        if handle is None:
            return {"error": "已有下载任务在运行"}
        self._cancel_idle_timer()
        self._broadcast_download_state()
        # 单链接下载也维护统计，让 成功/失败/总计 计数器实时更新。
        stats = self._app_state.batch_stats
        stats.clear()
        stats.update({"ok": 0, "fail": 0, "total": 1, "current": 1})
        self._app_state.publish({"type": "stats", "data": dict(stats)})
        audio_mode = config_snapshot.get("AUDIO_MODE", "0")
        audio_fmt = config_snapshot.get("AUDIO_FORMAT", "mp3")
        self._update_progress(0, "正在连接直播..." if is_live_download else "正在下载...")
        self._log(f"[下载] {url}", "info")
        try:
            threading.Thread(
                target=self._run_single,
                args=(handle, cmd, url, effective_platform, is_live_download, audio_mode, audio_fmt, verbose),
                daemon=True,
            ).start()
        except Exception as exc:
            self._download_manager.finish(handle)
            self._broadcast_download_state()
            self._start_idle_timer()
            return {"error": f"下载线程启动失败: {exc}"}
        return {"ok": True}

    def submit_password(self, url: str, password: str) -> dict:
        """处理密码提交：批量下载等待中则唤醒线程，否则启动新的单链接下载（密码重试）。"""
        with self._password_lock:
            if self._waiting_for_password:
                self._password_value = password
                self._password_event.set()
                return {"ok": True, "mode": "batch_retry"}
        # 无批量下载在等待 → 当作单链接密码重试，启动新下载任务
        return self.start_download(url, tc_password=password)

    def _wait_for_password(self, url: str, platform: str, timeout: float = 120.0) -> str | None:
        """阻塞等待用户通过前端弹窗提供密码。返回密码或 None（超时/取消）。"""
        with self._password_lock:
            self._waiting_for_password = True
            self._password_value = None
            self._password_event.clear()
        self._emit_event("password_required", {
            "url": url,
            "platform": platform,
            "reason": "retry",
        })
        received = self._password_event.wait(timeout)
        with self._password_lock:
            self._waiting_for_password = False
            pw = self._password_value
            self._password_value = None
        if not received:
            self._log(f"[{platform}] 等待密码超时，跳过此链接", "warn")
        return pw if received else None

    def _extract_audio_from_video(self, video_path, audio_fmt):
        """用 ffmpeg 从视频文件中提取指定格式的纯音频。"""
        base, _ = os.path.splitext(video_path)
        audio_ext = {"mp3": "mp3", "m4a": "m4a", "wav": "wav"}.get(audio_fmt, "mp3")
        audio_path = base + "." + audio_ext
        if os.path.isfile(audio_path):
            # 避免覆盖已有文件
            counter = 1
            while os.path.isfile(f"{base}_{counter}.{audio_ext}"):
                counter += 1
            audio_path = f"{base}_{counter}.{audio_ext}"
        ffmpeg = str(self._tool_dir / f"ffmpeg{self._exe_suffix}")
        codec_map = {
            "mp3": "libmp3lame",
            "m4a": "aac",
            "wav": "pcm_s16le",
        }
        codec = codec_map.get(audio_fmt, "libmp3lame")
        extract_cmd = [ffmpeg, "-y", "-i", video_path, "-vn", "-c:a", codec]
        if audio_fmt == "mp3":
            extract_cmd += ["-q:a", "2"]
        extract_cmd.append(audio_path)
        try:
            startupinfo, creationflags = _win_startup_info()
            proc = subprocess.Popen(
                extract_cmd, cwd=self._tool_dir,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                startupinfo=startupinfo, creationflags=creationflags,
            )
            # 根据视频文件大小动态估算超时（每 GB 最多 120 秒，最少 120 秒，最多 1800 秒）
            try:
                file_size = os.path.getsize(video_path)
            except OSError:
                file_size = 0
            dynamic_timeout = max(120, min(int(file_size / (1024 * 1024 * 1024) * 120), 1800)) if file_size > 0 else 300
            _, stderr = proc.communicate(timeout=dynamic_timeout)
            if proc.returncode == 0 and os.path.isfile(audio_path):
                self._log(f"[音频提取] 已生成: {os.path.basename(audio_path)}", "success")
            else:
                err = stderr.decode("utf-8", errors="replace").strip()[-200:] if stderr else ""
                self._log(f"[音频提取] 失败: {err}", "warn")
        except Exception as exc:
            self._log(f"[音频提取] 异常: {exc}", "warn")

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
        proc = None
        startupinfo, creationflags = _win_startup_info()
        try:
            proc = subprocess.Popen(
                cmd, cwd=self._tool_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                startupinfo=startupinfo, creationflags=creationflags,
            )
            try:
                stdout_output, stderr_output = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                self.kill_process_tree(proc)
                try:
                    proc.communicate(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    pass
                return {"error": "获取分P列表超时，已终止 yt-dlp 进程"}
            parts = []
            for line in stdout_output.splitlines()[:1000]:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    parts.append({
                        "index": entry.get("playlist_index", len(parts) + 1),
                        "title": entry.get("title") or f"P{len(parts) + 1}",
                        "id": entry.get("id", ""),
                        "duration": entry.get("duration") or 0,
                    })
                except json.JSONDecodeError:
                    continue
            if proc.returncode != 0:
                stderr_output = stderr_output.strip()
                return {"error": f"yt-dlp 进程退出码 {proc.returncode}" + (f": {stderr_output[:300]}" if stderr_output else "")}
            if not parts:
                return {"parts": [], "total": 0, "note": "未检测到分P列表，可能是单P视频"}
            return {"parts": parts, "total": len(parts)}
        except Exception as exc:
            if proc is not None and proc.poll() is None:
                self.kill_process_tree(proc)
            return {"error": f"获取分P列表失败: {exc}"}

    def _run_single(self, handle, cmd, url, effective_platform, is_live_download, audio_mode="0", audio_fmt="mp3", verbose=False):
        # 线程局部代际会随进度回调传递，旧工作线程无法覆盖新任务界面状态。
        self._app_state.download_thread_context.task_id = handle.generation
        stats = self._app_state.batch_stats

        def update_stats():
            if getattr(self._app_state.download_thread_context, "task_id", handle.generation) != self._download_manager.snapshot()["generation"]:
                return
            self._app_state.publish({"type": "stats", "data": dict(stats)})

        video_title = ""
        output_path = ""
        proc = None
        try:
            # 弹窗重试时记录完整命令，方便我debug。
            if verbose:
                masked = list(cmd)
                try:
                    idx = masked.index("--video-password")
                    masked[idx + 1] = "***"
                except (ValueError, IndexError):
                    pass
                self._log(f"[调试] yt-dlp 命令: {' '.join(masked)}", "info")
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
            password_required = False
            password_retry = False

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
                # 密码保护期：yt-dlp 提示需要 --video-password 时，标记以便结束后弹窗索取密码。
                # 仅 TwitCasting 使用 --video-password，限定平台避免其他平台的假阳性。
                if is_error and "--video-password" in line and effective_platform == "TwitCasting":
                    password_required = True
                # TwitCasting 密码错误时 yt-dlp 不报密码错误，而是报格式不可用。
                # 标记为 password_retry 以便显示不同的提示文案。
                # 限定 TwitCasting 平台，避免其他平台因格式不匹配误触发密码弹窗。
                if is_error and "format is not available" in line.lower() and effective_platform == "TwitCasting":
                    password_retry = True
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
                    "Trying video password", "Downloading m3u8",
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
                    raw_path = title_match.group(1).replace('"', "").replace("'", "").strip()
                    # 合并输出行给出最终文件名，优先于分离流的中间文件，用于定位同名封面。
                    output_path = raw_path
                    video_title = os.path.basename(raw_path)
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
                # 模式 2（同时输出音频）：下载完成后用 ffmpeg 从合并文件提取音频
                if audio_mode == "2" and output_path and os.path.isfile(output_path):
                    self._extract_audio_from_video(output_path, audio_fmt)
                stats["ok"] = 1
                self._log("[完成] 下载成功！", "success")
                self._update_progress(1, "下载完成", "", "")
                self._add_history(url, video_title, effective_platform, "success", output_path)
                update_stats()
            else:
                stats["fail"] = 1
                self._log(f"[错误] 下载结束，退出码: {rc}", "error")
                self._update_progress(0, f"失败 (退出码 {rc})", "", "")
                self._add_history(url, video_title, effective_platform, "fail")
                update_stats()
                # 密码保护/会员限定内容：通知前端弹窗索取密码后重试本条下载。
                if password_required or password_retry:
                    if password_retry:
                        self._log(f"[{effective_platform}] 下载失败，密码可能不正确，请重新输入密码", "warn")
                    else:
                        self._log(f"[{effective_platform}] 该内容受密码保护，请输入密码后重试", "warn")
                    self._emit_event("password_required", {
                        "url": url,
                        "platform": effective_platform,
                        "reason": "retry" if password_retry else "missing",
                    })
        except Exception as exc:
            stats["fail"] = 1
            self._log(f"[异常] {exc}", "error")
            self._update_progress(0, "异常终止", "", "")
            try:
                self._add_history(url, video_title, effective_platform, "fail")
            except Exception:
                pass
            update_stats()
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
        audio_mode = config_snapshot.get("AUDIO_MODE", "0")
        audio_fmt = config_snapshot.get("AUDIO_FORMAT", "mp3")
        stats.update({"ok": 0, "fail": 0, "total": len(urls), "current": 0})
        try:
            threading.Thread(target=self._run_batch, args=(handle, urls, config_snapshot, stats, bili_parts_map or {}, audio_mode, audio_fmt), daemon=True).start()
        except Exception as exc:
            self._download_manager.finish(handle)
            self._broadcast_download_state()
            self._start_idle_timer()
            return {"error": f"下载线程启动失败: {exc}"}
        return {"ok": True, "total": len(urls)}

    def _run_batch(self, handle, urls, config_snapshot, stats, bili_parts_map=None, audio_mode="0", audio_fmt="mp3"):
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
                bili_parts_for_url = (bili_parts_map or {}).get(url)

                # 密码重试循环（最多 2 次额外尝试）
                tc_password = config_snapshot.get("TC_PASSWORD")
                max_password_attempts = 3  # 初始 + 2 次重试
                pw_attempt = 0
                url_done = False

                while pw_attempt < max_password_attempts and not url_done:
                    if handle.cancel_event.is_set():
                        stopped = True
                        break
                    proc = None
                    output_path = ""
                    password_required = False
                    password_retry = False
                    try:
                        cmd_config = dict(config_snapshot)
                        if pw_attempt > 0 and tc_password:
                            cmd_config["TC_PASSWORD"] = tc_password
                        cmd = self._build_command(
                            url,
                            is_live=is_live_url(url, detected),
                            platform_override=effective_platform,
                            config_override=cmd_config,
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
                            is_error = "ERROR" in line
                            if is_error:
                                self._log(f"  {line}", "error")
                                if "--video-password" in line and effective_platform == "TwitCasting":
                                    password_required = True
                                if "format is not available" in line.lower() and effective_platform == "TwitCasting":
                                    password_retry = True
                            elif "WARNING" in line:
                                self._log(f"  {line}", "warn")
                            path_match = re.search(r"\[download\] Destination: (.+)", line) \
                                or re.search(r'\[Merger\] Merging formats into "(.+)"', line)
                            if path_match:
                                output_path = path_match.group(1).replace('"', "").replace("'", "").strip()
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
                            if audio_mode == "2" and output_path and os.path.isfile(output_path):
                                self._extract_audio_from_video(output_path, audio_fmt)
                            stats["ok"] += 1
                            self._log(f"[{index}/{len(urls)}] ✓ 完成", "success")
                            self._add_history(url, "", effective_platform, "success", output_path)
                            url_done = True
                        else:
                            # TwitCasting 密码保护：阻塞等待密码后重试
                            if (password_required or password_retry) and effective_platform == "TwitCasting":
                                pw_attempt += 1
                                if pw_attempt < max_password_attempts:
                                    self._log(f"[{effective_platform}] 需要密码，等待用户输入... ({pw_attempt}/{max_password_attempts - 1})", "warn")
                                    pw = self._wait_for_password(url, effective_platform)
                                    if pw:
                                        tc_password = pw
                                        continue  # 用新密码重试
                                # 超时或达到最大重试次数
                                stats["fail"] += 1
                                self._log(f"[{index}/{len(urls)}] ✗ 失败 (密码错误或超时)", "error")
                                self._add_history(url, "", effective_platform, "fail")
                                url_done = True
                            else:
                                stats["fail"] += 1
                                self._log(f"[{index}/{len(urls)}] ✗ 失败 (退出码 {rc})", "error")
                                self._add_history(url, "", effective_platform, "fail")
                                url_done = True
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
                        url_done = True
                if stopped:
                    break
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
                    startupinfo, creationflags = _win_startup_info()
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
        startupinfo, creationflags = _win_startup_info()
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
            pending_cr = False  # 上个字节是 \r，等下一个 \n 合并为 \r\n
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
                for i, value in enumerate(chunk):
                    if value == 0x0A:          # LF
                        if pending_cr:          # 前一个是 \r → \r\n 合并为一次 flush
                            pending_cr = False
                        if buffer:
                            try:
                                enqueue(safe_decode(buffer))
                            except Exception:
                                pass
                            buffer = bytearray()
                    elif value == 0x0D:         # CR — 等下一个字节判断
                        pending_cr = True
                        if i + 1 < len(chunk) and chunk[i + 1] == 0x0A:
                            pass               # 下个字节是 LF，一起 flush
                        else:
                            # 孤立的 \r（老 Mac 格式），当作换行处理
                            if buffer:
                                try:
                                    enqueue(safe_decode(buffer))
                                except Exception:
                                    pass
                                buffer = bytearray()
                            pending_cr = False
                    else:
                        if pending_cr:
                            # 前一个是 \r 但下一个不是 \n，先 flush 再追加
                            pending_cr = False
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
        # 仅当前代际有权广播结束态，旧线程迟到收尾不会伪造"空闲"。
        if self._download_manager.finish(handle):
            self._broadcast_download_state()
        if not self._app_state.has_sse_clients():
            self._start_idle_timer()
