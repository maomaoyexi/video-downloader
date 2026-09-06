import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

from video_downloader.core.constants import LEGACY_ALL_SUBTITLE_LANGS, RECOMMENDED_SUBTITLE_LANGS
from video_downloader.core.platform import clean_url, detect_platform, is_live_url, safe_decode
from video_downloader.core.subtitles import classify_subtitle_result
from video_downloader.services.withny_archive import WithnyArchiveError, build_ffmpeg_command, load_and_select, redact_line


def _win_startup_info():
    """获取 Windows 下隐藏子进程窗口的启动信息。

    返回 (STARTUPINFO, creationflags) 元组供 subprocess.Popen 使用。
    非 Windows 平台返回 (None, 0)。

    Returns:
        tuple: (STARTUPINFO | None, int) — Windows 下为隐藏窗口配置，其他平台为 (None, 0)。
    """
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
        pick_withny_archive=None,
        pick_withny_live_config=None,
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
        self._pick_withny_archive = pick_withny_archive
        self._pick_withny_live_config = pick_withny_live_config
        # 批量下载密码阻塞等待机制
        self._password_event = threading.Event()
        self._password_value: str | None = None
        self._password_lock = threading.Lock()
        self._waiting_for_password = False
        self._command_lock = threading.Lock()
        self._current_ytdlp_command = None

    def _remember_ytdlp_command(self, command):
        with self._command_lock:
            self._current_ytdlp_command = list(command)

    def get_current_ytdlp_command(self):
        """返回最近一次实际执行的 yt-dlp 命令，敏感参数值会被遮盖。"""
        with self._command_lock:
            command = list(self._current_ytdlp_command or [])
        if not command:
            return {"error": "当前还没有可复制的 yt-dlp 下载命令"}
        sensitive_options = {"--video-password", "--password"}
        masked = []
        hide_next = False
        for value in command:
            if hide_next:
                masked.append("***")
                hide_next = False
                continue
            masked.append(str(value))
            if value in sensitive_options:
                hide_next = True
        return {
            "ok": True,
            "command": subprocess.list2cmdline(masked),
            "redacted": masked != [str(value) for value in command],
        }

    @staticmethod
    def _with_ffmpeg_downloader(cmd):
        """为已构建好的 yt-dlp 命令追加 --downloader m3u8:ffmpeg（幂等）。

        TwitCasting 的 fMP4 录像可能在同一 m3u8 播放列表中包含多个初始化片段，
        原生 hlsnative 下载器会因此报 "Initialization fragment found after media
        fragments"。此时改用 FFmpeg 下载 m3u8 即可兼容。若命令已带该选项则原样返回。
        """
        if not cmd:
            return list(cmd)
        if "--downloader" in cmd and "m3u8:ffmpeg" in cmd:
            return list(cmd)
        # yt-dlp 允许选项出现在 URL 之后（如本工程末尾追加的 --verbose），
        # 直接追加到末尾即可生效。
        return list(cmd) + ["--downloader", "m3u8:ffmpeg"]

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

        is_live_download = is_live_url(url, detected)

        missing = self._missing_dependency(platform=detected, config=config_snapshot, is_live=is_live_download)
        if missing:
            return {"error": f"缺少依赖: {missing}"}
        try:
            cmd = self._build_command(
                url,
                is_live=is_live_download,
                platform_override=effective_platform,
                config_override=config_snapshot,
                bili_parts=bili_parts,
                include_subtitles=False,
            )
            subtitle_cmd = None
            if config_snapshot.get("DOWNLOAD_SUBTITLES", 0):
                subtitle_cmd = self._build_command(
                    url,
                    is_live=is_live_download,
                    platform_override=effective_platform,
                    config_override=config_snapshot,
                    bili_parts=bili_parts,
                    subtitle_only=True,
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
        initial_stage = "audio" if audio_mode == "3" else "video"
        self._update_progress(
            0,
            "正在连接直播..." if is_live_download else "正在下载...",
            stage=initial_stage,
        )
        self._log(f"[下载] {url}", "info")
        try:
            threading.Thread(
                target=self._run_single,
                args=(handle, cmd, url, effective_platform, is_live_download, audio_mode, audio_fmt, verbose, subtitle_cmd),
                daemon=True,
            ).start()
        except Exception as exc:
            self._download_manager.finish(handle)
            self._broadcast_download_state()
            self._start_idle_timer()
            return {"error": f"下载线程启动失败: {exc}"}
        return {"ok": True}

    def start_withny_archive(self):
        if self._pick_withny_archive is None:
            return {"error": "Withny 存档文件选择器不可用"}
        selection = self._pick_withny_archive()
        if selection.get("error"):
            return {"error": selection["error"]}
        if selection.get("cancelled"):
            return {"ok": True, "cancelled": True}

        ffmpeg = self._tool_dir / f"ffmpeg{self._exe_suffix}"
        if not ffmpeg.is_file():
            return {"error": f"缺少依赖: {ffmpeg.name}"}
        try:
            selected, archive_url, duration, cookie_header = load_and_select(selection["har_path"])
            output = Path(selection["output_path"]).expanduser().resolve()
            if output.suffix.lower() not in {".mp4", ".mkv", ".ts"}:
                return {"error": "输出格式只允许 mp4、mkv 或 ts"}
            if output.exists():
                return {"error": "输出文件已存在，请选择其他文件名"}
            output.parent.mkdir(parents=True, exist_ok=True)
            command, temp = build_ffmpeg_command(ffmpeg, selected["raw_url"], output, cookie_header)
        except WithnyArchiveError as exc:
            return {"error": str(exc)}
        except OSError as exc:
            return {"error": f"无法准备输出文件: {exc}"}

        handle = self._download_manager.begin("withny-archive")
        if handle is None:
            return {"error": "已有下载任务在运行"}
        self._cancel_idle_timer()
        self._broadcast_download_state()
        stats = self._app_state.batch_stats
        stats.clear()
        stats.update({"ok": 0, "fail": 0, "total": 1, "current": 1})
        self._app_state.publish({"type": "stats", "data": dict(stats)})
        self._update_progress(0, "正在连接 Withny 存档...")
        self._log(f"[Withny] 已验证普通 HLS: {selected['display_url']}", "info")
        try:
            threading.Thread(
                target=self._run_withny_archive,
                args=(handle, command, temp, output, selected["raw_url"], archive_url, duration),
                daemon=True,
            ).start()
        except Exception as exc:
            self._download_manager.finish(handle)
            self._broadcast_download_state()
            self._start_idle_timer()
            return {"error": f"下载线程启动失败: {exc}"}
        return {"ok": True}

    def _run_withny_archive(self, handle, command, temp, output, raw_url, archive_url, duration):
        self._app_state.download_thread_context.task_id = handle.generation
        stats = self._app_state.batch_stats
        proc = None
        try:
            proc = self._spawn(command)
            if not self._download_manager.publish_process(handle, proc):
                self.kill_process_tree(proc)
                return
            self._broadcast_download_state()
            line_q, read_done = self._start_reader(proc)
            self._update_progress(-1 if duration <= 0 else 0, "正在下载 Withny 存档...")
            while not read_done.is_set() or not line_q.empty():
                if handle.cancel_event.is_set():
                    break
                try:
                    line = line_q.get(timeout=0.5).strip()
                except queue.Empty:
                    continue
                if not line:
                    continue
                if line.startswith("out_time_ms=") or line.startswith("out_time_us="):
                    try:
                        seconds = int(line.split("=", 1)[1]) / 1_000_000
                        if duration > 0:
                            self._update_progress(min(seconds / duration, 0.99), "正在下载 Withny 存档...")
                    except ValueError:
                        pass
                elif not line.startswith("progress="):
                    cleaned = redact_line(line, raw_url)
                    if cleaned:
                        self._log(f"[FFmpeg] {cleaned[:300]}", "warn" if "error" in cleaned.lower() else "info")
            self._close_process(proc)
            rc = proc.returncode if proc.returncode is not None else -1
            if handle.cancel_event.is_set():
                self._log("[Withny] 下载已取消", "warn")
                self._update_progress(0, "已停止", "", "")
            elif rc == 0 and temp.is_file() and temp.stat().st_size > 0:
                os.replace(temp, output)
                stats["ok"] = 1
                self._app_state.publish({"type": "stats", "data": dict(stats)})
                self._log(f"[Withny] 保存完成: {output.name}", "success")
                self._update_progress(1, "下载完成", "", "")
                self._add_history(archive_url, output.name, "Withny", "success", str(output))
            else:
                stats["fail"] = 1
                self._app_state.publish({"type": "stats", "data": dict(stats)})
                self._log(f"[Withny] 下载失败，退出码: {rc}", "error")
                self._update_progress(0, f"失败 (退出码 {rc})", "", "")
                self._add_history(archive_url, output.name, "Withny", "fail")
        except Exception as exc:
            stats["fail"] = 1
            self._app_state.publish({"type": "stats", "data": dict(stats)})
            self._log(f"[Withny] 异常: {redact_line(str(exc), raw_url)}", "error")
            self._update_progress(0, "异常终止", "", "")
            self.kill_process_tree(proc)
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass
            self._finish(handle, proc)

    def start_withny_live(self):
        if self._pick_withny_live_config is None:
            return {"error": "Withny 直播配置选择器不可用"}
        selection = self._pick_withny_live_config()
        if selection.get("error"):
            return {"error": selection["error"]}
        if selection.get("cancelled"):
            return {"ok": True, "cancelled": True}

        executable = self._tool_dir / f"withny-dl-windows-amd64{self._exe_suffix}"
        if not executable.is_file():
            return {"error": f"缺少依赖: {executable.name}"}
        try:
            config_path = Path(selection["config_path"]).expanduser().resolve(strict=True)
        except (KeyError, OSError) as exc:
            return {"error": f"无法读取 Withny 直播配置: {exc}"}
        if config_path.suffix.lower() not in {".yaml", ".yml"}:
            return {"error": "Withny 直播配置只允许 yaml 或 yml 文件"}

        handle = self._download_manager.begin("withny-live")
        if handle is None:
            return {"error": "已有下载任务在运行"}
        self._cancel_idle_timer()
        self._broadcast_download_state()
        stats = self._app_state.batch_stats
        stats.clear()
        stats.update({"ok": 0, "fail": 0, "total": 1, "current": 1})
        self._app_state.publish({"type": "stats", "data": dict(stats)})
        self._update_progress(-1, "正在启动 Withny 直播监控...")
        self._log(f"[Withny 直播] 已加载配置: {config_path.name}", "info")
        command = [str(executable), "watch", "--config", str(config_path), "--pprof.listen-address", "127.0.0.1:0"]
        try:
            threading.Thread(
                target=self._run_withny_live,
                args=(handle, command, config_path.parent),
                daemon=True,
            ).start()
        except Exception as exc:
            self._download_manager.finish(handle)
            self._broadcast_download_state()
            self._start_idle_timer()
            return {"error": f"直播录制线程启动失败: {exc}"}
        return {"ok": True}

    def _run_withny_live(self, handle, command, working_dir):
        self._app_state.download_thread_context.task_id = handle.generation
        stats = self._app_state.batch_stats
        proc = None
        try:
            proc = self._spawn(command, cwd=working_dir)
            if not self._download_manager.publish_process(handle, proc):
                self.kill_process_tree(proc)
                return
            self._broadcast_download_state()
            line_q, read_done = self._start_reader(proc)
            self._update_progress(-1, "Withny 直播监控运行中")
            while not read_done.is_set() or not line_q.empty():
                if handle.cancel_event.is_set():
                    break
                try:
                    line = line_q.get(timeout=0.5).strip()
                except queue.Empty:
                    continue
                if not line:
                    continue
                cleaned = self._sanitize_withny_live_line(line)
                if cleaned:
                    level = "error" if any(word in cleaned.lower() for word in ("error", "panic", "fatal")) else "info"
                    self._log(f"[withny-dl] {cleaned[:500]}", level)
                    if "download" in cleaned.lower() or "stream" in cleaned.lower():
                        self._update_progress(-1, "Withny 直播录制中")
            self._close_process(proc)
            rc = proc.returncode if proc.returncode is not None else -1
            if handle.cancel_event.is_set():
                self._log("[Withny 直播] 监控和录制已停止", "warn")
                self._update_progress(0, "已停止", "", "")
            else:
                stats["fail"] = 1
                self._app_state.publish({"type": "stats", "data": dict(stats)})
                self._log(f"[Withny 直播] 进程意外退出，退出码: {rc}", "error")
                self._update_progress(0, f"失败 (退出码 {rc})", "", "")
        except Exception as exc:
            stats["fail"] = 1
            self._app_state.publish({"type": "stats", "data": dict(stats)})
            self._log(f"[Withny 直播] 异常: {self._sanitize_withny_live_line(str(exc))}", "error")
            self._update_progress(0, "异常终止", "", "")
            self.kill_process_tree(proc)
        finally:
            self._finish(handle, proc)

    @staticmethod
    def _sanitize_withny_live_line(line):
        cleaned = str(line)
        cleaned = re.sub(r"(?i)((?:authorization[=:]\s*)?bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[已隐藏]", cleaned)
        cleaned = re.sub(r'(?i)(["\']?(?:authorization|token|password|passcode|secret|encryptionkey)["\']?\s*[=:]\s*["\']?)[^\s,;"\']+', r"\1[已隐藏]", cleaned)
        return cleaned

    def submit_password(self, url: str, password: str) -> dict:
        """处理密码提交：批量下载等待中则唤醒线程，否则启动新的单链接下载（密码重试）。"""
        with self._password_lock:
            if self._waiting_for_password:
                self._password_value = password
                self._password_event.set()
                return {"ok": True, "mode": "batch_retry"}
        # 无批量下载在等待 → 当作单链接密码重试，启动新下载任务
        return self.start_download(url, tc_password=password)

    def _wait_for_password(
        self,
        url: str,
        platform: str,
        timeout: float = 120.0,
        reason: str = "retry",
    ) -> str | None:
        """阻塞等待用户通过前端弹窗提供密码。返回密码或 None（超时/取消）。"""
        with self._password_lock:
            self._waiting_for_password = True
            self._password_value = None
            self._password_event.clear()
        self._emit_event("password_required", {
            "url": url,
            "platform": platform,
            "reason": reason,
        })
        received = self._password_event.wait(timeout)
        with self._password_lock:
            self._waiting_for_password = False
            pw = self._password_value
            self._password_value = None
        if not received:
            self._log(f"[{platform}] 等待密码超时，跳过此链接", "warn")
        return pw if received else None

    @staticmethod
    def _media_stage_from_line(line, fallback="video"):
        """从自定义 yt-dlp 进度标记中识别当前下载的是视频还是音频。"""
        match = re.search(r"__VD_STAGE__([^|\s]+)\|([^\s]+)", line)
        if not match:
            return fallback
        video_codec, audio_codec = (value.lower() for value in match.groups())
        empty_values = {"none", "null", "na", "n/a", "unknown"}
        if video_codec in empty_values and audio_codec not in empty_values:
            return "audio"
        if video_codec not in empty_values:
            return "video"
        return fallback

    @staticmethod
    def _progress_metrics_from_line(line):
        """兼容自定义模板和 yt-dlp 默认输出，提取速度与剩余时间。"""
        speed = ""
        eta = ""
        speed_match = re.search(r"\bat\s+(.+?)\s+ETA(?:\s|$)", line)
        if speed_match:
            speed = speed_match.group(1).strip().replace(" ", "")
        else:
            legacy_speed = re.search(r"(\d+(?:\.\d+)?\s*[KMGT]?i?B/s)", line)
            if legacy_speed:
                speed = legacy_speed.group(1).replace(" ", "")
        eta_match = re.search(r"\bETA\s+(.+?)(?:\s+__VD_STAGE__|$)", line)
        if eta_match:
            eta = eta_match.group(1).strip()
        # yt-dlp 未知速度/剩余时间会带单位后缀，如 "Unknown B/s"；归一化后再判断，
        # 避免把 "UnknownB/s" 这类垃圾值显示到前端速度指示器上。
        def _is_placeholder(value):
            lowered = value.lower()
            return lowered in {"", "unknown", "n/a", "na", "none"} or lowered.startswith("unknown")

        if _is_placeholder(speed):
            speed = ""
        if _is_placeholder(eta):
            eta = ""
        return speed, eta

    def _extract_audio_from_video(self, video_path, audio_fmt, handle=None, status="正在提取音频..."):
        """用 ffmpeg 从视频文件中提取指定格式的纯音频。

        仅用于音频模式 2（同时输出音频），从合并后的视频文件中提取音频轨。

        Args:
            video_path: 视频文件的完整路径。
            audio_fmt: 目标音频格式（mp3/m4a/wav）。
        """
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
        extract_cmd = [
            ffmpeg, "-y", "-i", video_path, "-vn", "-c:a", codec,
            "-progress", "pipe:1", "-nostats",
        ]
        if audio_fmt == "mp3":
            extract_cmd += ["-q:a", "2"]
        extract_cmd.append(audio_path)
        proc = None
        succeeded = False
        duration = 0.0
        try:
            self._update_progress(0, status, "", "", stage="audio")
            startupinfo, creationflags = _win_startup_info()
            proc = subprocess.Popen(
                extract_cmd, cwd=self._tool_dir,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                startupinfo=startupinfo, creationflags=creationflags,
            )
            if handle is not None and not self._download_manager.publish_process(handle, proc):
                self.kill_process_tree(proc)
                return False
            line_q, read_done = self._start_reader(proc)
            while not read_done.is_set() or not line_q.empty():
                if handle is not None and handle.cancel_event.is_set():
                    self.kill_process_tree(proc)
                    break
                try:
                    line = line_q.get(timeout=0.1).strip()
                except queue.Empty:
                    continue
                duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", line)
                if duration_match:
                    hours, minutes, seconds = duration_match.groups()
                    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                    continue
                time_match = re.match(r"out_time_(?:ms|us)=(\d+)", line)
                if time_match and duration > 0:
                    elapsed = int(time_match.group(1)) / 1_000_000
                    self._update_progress(
                        min(elapsed / duration, 0.99),
                        status,
                        "",
                        "",
                        stage="audio",
                    )
            self._close_process(proc)
            if handle is not None and handle.cancel_event.is_set():
                self._log("[音频提取] 已取消", "warn")
                return False
            succeeded = proc.returncode == 0 and os.path.isfile(audio_path)
            if succeeded:
                self._log(f"[音频提取] 已生成: {os.path.basename(audio_path)}", "success")
            else:
                self._log(f"[音频提取] 失败，退出码: {proc.returncode}", "warn")
        except Exception as exc:
            self._log(f"[音频提取] 异常: {exc}", "warn")
            self.kill_process_tree(proc)
        finally:
            if handle is not None and proc is not None:
                self._download_manager.clear_process(handle, proc)
            if not succeeded and os.path.isfile(audio_path):
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass
        return succeeded

    def fetch_bili_playlist(self, url):
        """获取 Bilibili 视频的分P列表。

        通过 yt-dlp --flat-playlist --dump-json 获取播放列表元数据，不实际下载视频。

        Args:
            url: Bilibili 视频链接。

        Returns:
            dict: 成功时返回 {"parts": [...], "total": N}，失败时返回 {"error": "..."}。
        """
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

    def _run_subtitle_sidecar(self, handle, cmd, prefix=""):
        if handle.cancel_event.is_set():
            return False
        proc = None
        captured_lines = []
        self._log(f"{prefix}[字幕] 开始下载字幕（失败不影响视频）", "info")
        try:
            self._remember_ytdlp_command(cmd)
            proc = self._spawn(cmd)
            if not self._download_manager.publish_process(handle, proc):
                self.kill_process_tree(proc)
                return False
            line_q, read_done = self._start_reader(proc)
            while not read_done.is_set() or not line_q.empty():
                if handle.cancel_event.is_set():
                    self.kill_process_tree(proc)
                    break
                try:
                    line = line_q.get(timeout=0.5).strip()
                except queue.Empty:
                    continue
                if not line:
                    continue
                captured_lines.append(line)
                if "ERROR" in line or "WARNING" in line:
                    self._log(f"{prefix}[字幕] {line}", "warn")
                elif any(value in line for value in ["Destination:", "Writing video subtitles", "Downloading subtitles"]):
                    self._log(f"{prefix}[字幕] {line}", "info")
            self._close_process(proc)
            returncode = proc.returncode if proc.returncode is not None else -1
            if handle.cancel_event.is_set():
                return False
            result = classify_subtitle_result(returncode, "\n".join(captured_lines))
            if result == "success":
                self._log(f"{prefix}[字幕] 字幕下载完成", "success")
                return True
            if returncode != 0 and self._should_retry_recommended_subtitles(cmd, captured_lines):
                self._download_manager.clear_process(handle, proc)
                proc = None
                retry_cmd = self._replace_subtitle_langs(cmd, RECOMMENDED_SUBTITLE_LANGS)
                self._log(f"{prefix}[字幕] 全量字幕请求被限流，改用常用字幕重试", "warn")
                return self._run_subtitle_sidecar(handle, retry_cmd, prefix=prefix)
            if result == "missing":
                self._log(f"{prefix}[字幕] 未找到匹配字幕，已跳过（不影响视频）", "warn")
            else:
                self._log(f"{prefix}[字幕] 字幕下载失败，已跳过（不影响视频）", "warn")
            return False
        except Exception as exc:
            self._log(f"{prefix}[字幕] 字幕下载异常，已跳过（不影响视频）: {exc}", "warn")
            if proc is not None:
                self.kill_process_tree(proc)
            return False
        finally:
            if proc is not None:
                self._download_manager.clear_process(handle, proc)

    @staticmethod
    def _subtitle_langs_index(cmd):
        try:
            index = cmd.index("--sub-langs") + 1
        except ValueError:
            return None
        return index if index < len(cmd) else None

    @classmethod
    def _replace_subtitle_langs(cls, cmd, langs):
        index = cls._subtitle_langs_index(cmd)
        retry_cmd = list(cmd)
        if index is not None:
            retry_cmd[index] = langs
        return retry_cmd

    @classmethod
    def _should_retry_recommended_subtitles(cls, cmd, lines):
        index = cls._subtitle_langs_index(cmd)
        if index is None or cmd[index] != LEGACY_ALL_SUBTITLE_LANGS:
            return False
        output = "\n".join(lines)
        return "HTTP Error 429" in output or "Too Many Requests" in output

    def _run_single(self, handle, cmd, url, effective_platform, is_live_download, audio_mode="0", audio_fmt="mp3", verbose=False, subtitle_cmd=None):
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
        current_stage = "audio" if audio_mode == "3" else "video"
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
            self._remember_ytdlp_command(cmd)
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
            init_fragment_error = False

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
                        self._update_progress(-1, status_text, speed=speed, eta="", stage=current_stage)
                    continue
                line = line.strip()
                if not line:
                    continue

                if is_live_download and not live_connected and ("Connecting to WebSocket" in line or "Downloading m3u8" in line):
                    live_connected = True
                    live_start_time = time.time()
                    self._update_progress(-1, "直播录制中...", stage=current_stage)

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
                # TwitCasting fMP4 播放列表含多个初始化片段时原生下载器会失败，
                # 标记后改用 FFmpeg 下载 m3u8 重试。
                if is_error and "Initialization fragment found after media fragments" in line and effective_platform == "TwitCasting":
                    init_fragment_error = True
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
                    current_stage = self._media_stage_from_line(line, current_stage)
                    speed, eta = self._progress_metrics_from_line(line)
                    self._update_progress(
                        float(progress_match.group(1)) / 100,
                        speed=speed,
                        eta=eta,
                        stage=current_stage,
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
                    self._update_progress(-1, status_text, speed=speed, eta="", stage=current_stage)

            self._close_process(proc)
            rc = proc.returncode if proc.returncode is not None else -1
            if handle.cancel_event.is_set():
                self._log("[停止] 下载已取消", "warn")
                self._update_progress(0, "已停止", "", "")
            elif rc == 0:
                # 模式 2（同时输出音频）：下载完成后用 ffmpeg 从合并文件提取音频
                if audio_mode == "2" and output_path and os.path.isfile(output_path):
                    self._extract_audio_from_video(output_path, audio_fmt, handle=handle)
                if handle.cancel_event.is_set():
                    self._log("[停止] 下载已取消", "warn")
                    self._update_progress(0, "已停止", "", "", stage="audio" if audio_mode == "2" else current_stage)
                    return
                if subtitle_cmd:
                    self._update_progress(1, "视频完成，正在下载字幕...", "", "", stage="subtitle")
                    self._run_subtitle_sidecar(handle, subtitle_cmd)
                    if handle.cancel_event.is_set():
                        self._log("[停止] 下载已取消", "warn")
                        self._update_progress(0, "已停止", "", "", stage="subtitle")
                        update_stats()
                        return
                stats["ok"] = 1
                self._log("[完成] 下载成功！", "success")
                self._update_progress(1, "下载完成", "", "")
                self._add_history(url, video_title, effective_platform, "success", output_path)
                update_stats()
            else:
                # TwitCasting 多初始化片段：原生下载器失败，改用 FFmpeg 重试一次。
                if init_fragment_error and effective_platform == "TwitCasting" and "--downloader" not in cmd:
                    self._log(f"[{effective_platform}] 检测到多初始化片段，改用 FFmpeg 下载器重试", "warn")
                    self._run_single(
                        handle,
                        self._with_ffmpeg_downloader(cmd),
                        url,
                        effective_platform,
                        is_live_download,
                        audio_mode,
                        audio_fmt,
                        verbose,
                        subtitle_cmd,
                    )
                    return
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
        # 只在本次批量任务的内存中保存最近一次有效的 TwitCasting 密码。
        # 不写回配置，也不会跨任务保留。
        last_tc_password = None

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
                current_stage = "audio" if audio_mode == "3" else "video"
                self._update_progress(
                    0,
                    f"批量下载 {index}/{len(urls)}",
                    stage=current_stage,
                )
                bili_parts_for_url = (bili_parts_map or {}).get(url)

                # 密码重试循环（最多 2 次额外尝试）
                tc_password = last_tc_password if effective_platform == "TwitCasting" else None
                if tc_password:
                    self._log(f"[{effective_platform}] 自动尝试上一个已输入的密码", "info")
                max_password_attempts = 3  # 初始 + 2 次重试
                pw_attempt = 0
                url_done = False
                # TwitCasting fMP4 多初始化片段时切换到 FFmpeg 下载 m3u8 的标记。
                use_ffmpeg_for_hls = False

                while pw_attempt < max_password_attempts and not url_done:
                    if handle.cancel_event.is_set():
                        stopped = True
                        break
                    proc = None
                    output_path = ""
                    password_required = False
                    password_retry = False
                    init_fragment_error = False
                    try:
                        cmd_config = dict(config_snapshot)
                        # 避免基础配置中的旧密码绕过本次任务的失效处理。
                        cmd_config.pop("TC_PASSWORD", None)
                        if effective_platform == "TwitCasting" and tc_password:
                            cmd_config["TC_PASSWORD"] = tc_password
                        cmd = self._build_command(
                            url,
                            is_live=is_live_url(url, detected),
                            platform_override=effective_platform,
                            config_override=cmd_config,
                            bili_parts=bili_parts_for_url,
                            use_ffmpeg_for_hls=use_ffmpeg_for_hls,
                            include_subtitles=False,
                        )
                        subtitle_cmd = None
                        if cmd_config.get("DOWNLOAD_SUBTITLES", 0):
                            subtitle_cmd = self._build_command(
                                url,
                                is_live=is_live_url(url, detected),
                                platform_override=effective_platform,
                                config_override=cmd_config,
                                bili_parts=bili_parts_for_url,
                                subtitle_only=True,
                            )
                        self._remember_ytdlp_command(cmd)
                        proc = self._spawn(cmd)
                        if not self._download_manager.publish_process(handle, proc):
                            stopped = True
                            self.kill_process_tree(proc)
                            break
                        line_q, read_done = self._start_reader(proc)
                        # Niconico 直播超时控制：正在直播的链接不加 --live-from-start 时
                        # yt-dlp 会无限等待新分片。通过 LIVE_DOWNLOAD_TIMEOUT 限制单链接
                        # 最长下载时间，超时后自动终止并跳到下一个链接。
                        nico_live_dl = (effective_platform == "Niconico"
                                        and is_live_url(url, detected))
                        live_timeout_min = int(config_snapshot.get("LIVE_DOWNLOAD_TIMEOUT", 0))
                        download_start = time.time()
                        download_timed_out = False
                        # 直播进度跟踪（用于非百分比输出的场景）
                        batch_live_size = ""
                        batch_live_speed = ""
                        batch_live_frag = ""
                        batch_live_start = time.time()
                        while not read_done.is_set() or not line_q.empty():
                            if handle.cancel_event.is_set():
                                break
                            # 超时检查：仅对 Niconico 直播生效，0 表示不限时
                            if nico_live_dl and live_timeout_min > 0:
                                elapsed = (time.time() - download_start) / 60
                                if elapsed >= live_timeout_min:
                                    self._log(f"  ⏱ 下载超时（{live_timeout_min}分钟），已跳过", "warn")
                                    self.kill_process_tree(proc)
                                    download_timed_out = True
                                    break
                            try:
                                line = line_q.get(timeout=0.5).strip()
                            except queue.Empty:
                                # 心跳日志：没有新输出时，对 Niconico 直播显示录制时长
                                if nico_live_dl:
                                    elapsed = int(time.time() - batch_live_start)
                                    if elapsed > 0 and elapsed % 30 == 0:
                                        frag_info = f" | {batch_live_frag}" if batch_live_frag else ""
                                        size_info = f" | {batch_live_size}" if batch_live_size else ""
                                        spd_info = f" | {batch_live_speed}" if batch_live_speed else ""
                                        self._update_progress(-1, f"[{index}/{len(urls)}] 录制中 {elapsed//60}m{elapsed%60:02d}s{frag_info}{size_info}{spd_info}", stage=current_stage)
                                continue
                            if not line:
                                continue
                            # === 日志输出（保持用户可见） ===
                            is_error = "ERROR" in line
                            if is_error:
                                self._log(f"  {line}", "error")
                                if "--video-password" in line and effective_platform == "TwitCasting":
                                    password_required = True
                                if "format is not available" in line.lower() and effective_platform == "TwitCasting":
                                    password_retry = True
                                if "Initialization fragment found after media fragments" in line and effective_platform == "TwitCasting":
                                    init_fragment_error = True
                            elif "WARNING" in line:
                                self._log(f"  {line}", "warn")
                            else:
                                # 友好的信息日志：关键词行 + 分片/进度信息
                                is_keyword = any(kw in line for kw in [
                                    "Destination:", "Downloading webpage", "Extracting URL",
                                    "Connecting to WebSocket", "Downloading m3u8",
                                    "has already been recorded",
                                ])
                                is_fragment = "fragment" in line.lower()
                                has_size = re.search(r"\d+\.?\d*\s*[KMG]iB", line)
                                if is_keyword and len(line) < 200:
                                    self._log(f"  {line}", "info")
                                elif is_fragment:
                                    # 分片下载进度：每 10 个分片或首个分片记录一次
                                    frag_match = re.search(r"fragment\s+(\d+)", line, re.IGNORECASE)
                                    if frag_match:
                                        frag_num = int(frag_match.group(1))
                                        batch_live_frag = f"分片 {frag_num}"
                                        if frag_num <= 1 or frag_num % 10 == 0:
                                            self._log(f"  {line}", "info")
                                elif has_size and not line.startswith("[download] "):
                                    # 字节量进度（如 "123.45MiB at 2.34MiB/s"）
                                    size_match = re.search(r"(\d+\.?\d*\s*[KMG]iB)", line)
                                    speed_match = re.search(r"(\d+\.?\d*\s*[KMG]iB/s)", line)
                                    if size_match:
                                        batch_live_size = "已下载 " + size_match.group(1).replace(" ", "")
                                    if speed_match:
                                        batch_live_speed = speed_match.group(1).replace(" ", "")
                                    # 每 30 秒记一次数据量日志
                                    elapsed = int(time.time() - batch_live_start)
                                    if elapsed > 0 and elapsed % 30 == 0:
                                        self._log(f"  {batch_live_size} | {batch_live_speed}", "info")
                            # === 进度更新 ===
                            path_match = re.search(r"\[download\] Destination: (.+)", line) \
                                or re.search(r'\[Merger\] Merging formats into "(.+)"', line)
                            if path_match:
                                output_path = path_match.group(1).replace('"', "").replace("'", "").strip()
                                self._log(f"  → {os.path.basename(output_path)}", "info")
                            progress_match = re.search(r"(\d+(?:\.\d+)?)%", line)
                            if progress_match:
                                # 批量统计由下方计数器单独展示；主进度条只反映
                                # 当前这一条视频/音频流，切到下一条时从 0 重新开始。
                                current_progress = float(progress_match.group(1)) / 100
                                current_stage = self._media_stage_from_line(line, current_stage)
                                speed, eta = self._progress_metrics_from_line(line)
                                self._update_progress(current_progress, f"批量下载 {index}/{len(urls)}",
                                    speed=speed,
                                    eta=eta,
                                    stage=current_stage)
                            elif nico_live_dl and (batch_live_frag or batch_live_size):
                                # Niconico 直播无百分比输出：用数据量/分片数显示活动状态
                                frag_info = f" | {batch_live_frag}" if batch_live_frag else ""
                                size_info = f" | {batch_live_size}" if batch_live_size else ""
                                spd_info = f" | {batch_live_speed}" if batch_live_speed else ""
                                elapsed = int(time.time() - batch_live_start)
                                self._update_progress(-1, f"[{index}/{len(urls)}] 录制中 {elapsed//60}m{elapsed%60:02d}s{frag_info}{size_info}{spd_info}", stage=current_stage)
                        self._close_process(proc)
                        self._download_manager.clear_process(handle, proc)
                        if download_timed_out:
                            # 下载超时：不视为失败，已下载的部分保留，继续下一个链接
                            self._log(f"[{index}/{len(urls)}] ⏱ 超时跳过（已下载部分保留）", "warn")
                            self._add_history(url, "", effective_platform, "timeout", output_path)
                            url_done = True
                            update_stats()
                            continue
                        if handle.cancel_event.is_set():
                            stopped = True
                            self._log(f"[{index}/{len(urls)}] ✗ 已取消", "warn")
                            update_stats()
                            break
                        rc = proc.returncode if proc.returncode is not None else -1
                        if rc == 0:
                            if audio_mode == "2" and output_path and os.path.isfile(output_path):
                                self._extract_audio_from_video(
                                    output_path,
                                    audio_fmt,
                                    handle=handle,
                                    status=f"批量下载 {index}/{len(urls)} · 正在提取音频",
                                )
                            if handle.cancel_event.is_set():
                                stopped = True
                                self._log(f"[{index}/{len(urls)}] ✗ 已取消", "warn")
                                break
                            if subtitle_cmd:
                                self._update_progress(1, f"批量下载 {index}/{len(urls)} · 正在下载字幕", stage="subtitle")
                                self._run_subtitle_sidecar(handle, subtitle_cmd, prefix=f"[{index}/{len(urls)}] ")
                                if handle.cancel_event.is_set():
                                    stopped = True
                                    self._log(f"[{index}/{len(urls)}] ✗ 已取消", "warn")
                                    break
                            stats["ok"] += 1
                            self._log(f"[{index}/{len(urls)}] ✓ 完成", "success")
                            self._add_history(url, "", effective_platform, "success", output_path)
                            url_done = True
                        else:
                            # TwitCasting fMP4 播放列表含多个初始化片段：原生下载器
                            # 失败，切换 FFmpeg 下载 m3u8 后重试一次（不消耗密码重试次数）。
                            if init_fragment_error and effective_platform == "TwitCasting" and not use_ffmpeg_for_hls:
                                use_ffmpeg_for_hls = True
                                self._log(f"[{effective_platform}] 检测到多初始化片段，改用 FFmpeg 下载器重试", "warn")
                                continue
                            # TwitCasting 密码保护：阻塞等待密码后重试
                            if (password_required or password_retry) and effective_platform == "TwitCasting":
                                pw_attempt += 1
                                if pw_attempt < max_password_attempts:
                                    reused_password_failed = bool(tc_password)
                                    if reused_password_failed:
                                        # 上一个链接的密码不适用于当前链接，失效后不得继续传播。
                                        last_tc_password = None
                                        tc_password = None
                                        self._log(
                                            f"[{effective_platform}] 上一个密码不适用于此链接，等待输入新密码... "
                                            f"({pw_attempt}/{max_password_attempts - 1})",
                                            "warn",
                                        )
                                    else:
                                        self._log(
                                            f"[{effective_platform}] 需要密码，等待用户输入... "
                                            f"({pw_attempt}/{max_password_attempts - 1})",
                                            "warn",
                                        )
                                    reason = "retry" if password_retry or reused_password_failed else "missing"
                                    pw = self._wait_for_password(
                                        url,
                                        effective_platform,
                                        reason=reason,
                                    )
                                    if pw:
                                        tc_password = pw
                                        last_tc_password = pw
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
        # 密码输入等待没有子进程可杀，必须主动唤醒，否则批量线程会卡到 120 秒超时。
        with self._password_lock:
            if self._waiting_for_password:
                self._password_value = None
                self._password_event.set()
        self._update_progress(0, "正在停止...", "", "")
        if ticket.process is not None:
            self.kill_process_tree(ticket.process)
            self._log("[停止] 下载进程已终止", "warn")
        else:
            self._log("[停止] 下载任务已取消", "warn")
        # 进程终止后立即释放任务槽位。旧线程仍会在后台做极短的清理，
        # 但代际检查会阻止它覆盖随后启动的新任务。
        stopped = self._download_manager.complete_stop(ticket.generation)
        if stopped:
            self._update_progress(0, "已停止", "", "")
        self._broadcast_download_state()
        return {"ok": True, "stopping": not stopped, "stopped": stopped}

    def kill_process_tree(self, process):
        if process is None:
            return True
        try:
            if process.poll() is None:
                if os.name == "nt":
                    startupinfo, creationflags = _win_startup_info()
                    try:
                        # 下载器没有需要保存的交互状态，直接强制结束整棵进程树。
                        # 原先先温和等待再强制终止，最坏会额外阻塞十余秒。
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                            capture_output=True,
                            timeout=1,
                            startupinfo=startupinfo,
                            creationflags=creationflags,
                        )
                    except Exception:
                        pass
                    try:
                        process.wait(timeout=0.25)
                    except Exception:
                        pass
                if process.poll() is None:
                    try:
                        process.kill()
                        process.wait(timeout=0.25)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            if process.stdout:
                process.stdout.close()
        except Exception:
            pass
        try:
            return process.poll() is not None
        except Exception:
            return False

    def _missing_dependency(self, platform=None, config=None, is_live=False):
        """检查必需的依赖可执行文件是否存在。

        基础依赖（yt-dlp、ffmpeg、ffprobe）始终检查。
        """
        for dependency in ["yt-dlp", "ffmpeg", "ffprobe"]:
            filename = f"{dependency}{self._exe_suffix}"
            if not (self._tool_dir / filename).exists():
                return filename
        return None

    def _spawn(self, cmd, cwd=None):
        env = os.environ.copy()
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"})
        startupinfo, creationflags = _win_startup_info()
        return subprocess.Popen(
            cmd,
            cwd=cwd or self._tool_dir,
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
