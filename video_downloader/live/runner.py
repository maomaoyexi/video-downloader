"""Shared live lifecycle: isolation, bounded recovery, graceful stop and evidence."""
from __future__ import annotations

import io
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import traceback
from pathlib import Path

from . import process
from .engines.bililive import BililiveEngine, EngineUnavailable, cookie_from_file, validate_install
from .engines.ytdlp import YtDlpEngine
from .engines.withnydl import WithnyEngine
from .engines.rplay import RplayEngine
from .engines import EngineFeatures
from .probe import ProbeError
from .integrity import IntegrityChecker
from .session import LiveSession, media_files, redact_command
from .urls import classify_target
from .catchup import BackfillJob, CatchUpEvidence, CatchUpPlanner, at_live_edge
from .danmaku.service import process_comments
from .danmaku.preferences import enabled as comments_enabled
from .danmaku.capture import CommentCapture
from .splice import reconcile
from .clock import MediaClock


class LiveRunner:
    def __init__(self, paths, suffix, *, log, progress, publish_process, clear_process,
                 force_kill, emit_event, clock=time.monotonic):
        self.paths, self.suffix = paths, suffix
        self.log, self.progress = log, progress
        self.publish_process, self.clear_process = publish_process, clear_process
        self.force_kill, self.emit_event, self.clock = force_kill, emit_event, clock
        self.session = None

    def _engine(self, command, platform, url, config):
        if platform == "Withny":
            return WithnyEngine(command, self.session, config["_withny_config_path"],
                                bool(config.get("LIVE_DANMAKU_ENABLED", 0)))
        if platform == 'Rplay':
            return RplayEngine(command, url)
        if platform != "Bilibili" or config.get("LIVE_STREAM_METHOD", "auto") == "yt-dlp":
            return YtDlpEngine(command)
        try:
            # Unsupported settings are never silently ignored by the specialist engine.
            unsupported = []
            if config.get("PROXY_ENABLED", 0):
                unsupported.append("代理")
            if str(config.get("AUDIO_MODE", "0")) != "0":
                unsupported.append("音频处理")
            if config.get("RESOLUTION", "best") != "best" or config.get("CODEC", "best") != "best":
                unsupported.append("画质/编码筛选")
            if config.get("YTDLP_DEFAULT_ARGS") or config.get("_custom_live_args"):
                unsupported.append("自定义 yt-dlp 参数")
            if unsupported:
                raise EngineUnavailable("设置需要 yt-dlp: " + "、".join(unsupported))
            cookie = ""
            if config.get("USE_COOKIES", 0):
                if int(config.get("COOKIE_MODE", 1)) != 1:
                    raise EngineUnavailable("录播姬使用 cookies.txt；浏览器 Cookie 模式由 yt-dlp 处理")
                cookie = cookie_from_file(self.paths.app_dir / "cookies.txt")
            room = classify_target(url, platform).stable_id
            if not room.isdigit() or int(room) <= 0:
                raise EngineUnavailable("未取得数字直播间 ID")
            binary = validate_install(self.paths.dependency_dir / "BililiveRecorder")
            return BililiveEngine(binary, self.session, room, cookie=cookie,
                                  danmaku=bool(config.get("LIVE_DANMAKU_ENABLED", 0)))
        except (EngineUnavailable, OSError, ValueError) as exc:
            self.log(f"[直播] 已降级为 yt-dlp LIVE_EDGE：{exc}", "warn")
            self.session.event("engine_fallback", reason=str(exc))
            self.emit_event("live_recording", {"job_id": self.session.root.name, "engine": "yt-dlp", "degraded": True})
            return YtDlpEngine(command)

    @staticmethod
    def _reader(proc):
        lines, done = queue.Queue(maxsize=512), threading.Event()
        def read():
            try:
                pending = b""
                while True:
                    try:
                        raw = os.read(proc.stdout.fileno(), 4096)
                    except (AttributeError, io.UnsupportedOperation):
                        raw = proc.stdout.read(4096)
                    chunks = re.split(b"[\r\n]", pending + raw)
                    pending = chunks.pop()[-16384:] if raw else b""
                    for chunk in chunks:
                        line = chunk.decode("utf-8", "replace").strip()
                        try:
                            lines.put_nowait(line)
                        except queue.Full:
                            try:
                                lines.get_nowait()
                                lines.put_nowait(line)
                            except queue.Empty:
                                pass
                    if not raw:
                        break
            finally:
                done.set()
        thread = threading.Thread(target=read, name="live-output", daemon=True)
        thread.start()
        return lines, done, thread

    def run(self, command, *, url, platform, mode, config, cancel):
        config = dict(config, LIVE_DANMAKU_ENABLED=int(comments_enabled(config, platform)))
        session = self.session = LiveSession(self.paths.download_dir / ".live-jobs", platform, mode, url)
        checker = IntegrityChecker(self.paths.executable("ffprobe", self.suffix), self.paths.executable("ffmpeg", self.suffix))
        reason, forced, warnings, webhook_complete = "error", False, [], True
        engine, proc, title = None, None, "直播录制"
        features = EngineFeatures()
        backfill, catch_up_evidence = None, None
        comments = None
        clocks = []
        original_command = list(command)
        error_lines = []
        max_retries = int(config.get("LIVE_MAX_RETRIES", 5))
        timeout = int(config.get("LIVE_DOWNLOAD_TIMEOUT", 0)) * 60
        # Installation checks, authentication and connecting are not recording time.
        # Anchor the limit to the first observed media growth, once for all parts.
        deadline = None
        minimum = int(config.get("LIVE_MIN_FREE_MB", 256)) * 1024 ** 2
        bitrate = int(config.get("LIVE_ESTIMATED_BITRATE_KBPS", 8000))
        required = max(minimum, int(bitrate * 1000 / 8 * (timeout or 900) * 1.3))
        expected = {"3": "a", "1": "separate"}.get(str(config.get("AUDIO_MODE", "0")), "av")
        self.log(f"[直播] 会话与完整性报告目录：{session.root}", "info")
        try:
            free = shutil.disk_usage(session.media).free
            session.data["disk_preflight"] = {"free_bytes": free, "required_bytes": required,
                                               "estimated_bitrate_kbps": bitrate,
                                               "estimated_seconds": timeout or 900}
            session.save()
            if free < required:
                reason = "disk_full"
                raise OSError(f"磁盘预检未通过：可用 {free // 1024**2} MiB，预计需要 {required // 1024**2} MiB")
            if not cancel.is_set() and mode == "catch_up" and platform in {"YouTube", "Twitch"}:
                self.progress(-1, "正在验证本场直播的追播能力...")
                catch_up_evidence = CatchUpPlanner(cancel=cancel, force_kill=self.force_kill).probe(command, url, platform)
                if (catch_up_evidence.strategy == "tail_and_backfill"
                        and str(config.get("AUDIO_MODE", "0")) != "0"):
                    catch_up_evidence = CatchUpEvidence(False, "Twitch 双路追播暂仅验证音视频合并模式；本次按音频设置从当前录制")
                if catch_up_evidence.strategy == "tail_and_backfill":
                    backfill_bytes = int(max(0, time.time() - catch_up_evidence.started_at) * bitrate * 1000 / 8 * 1.3)
                    session.data["disk_preflight"]["backfill_required_bytes"] = backfill_bytes
                    if free < required + backfill_bytes:
                        catch_up_evidence = CatchUpEvidence(False, "磁盘不足以同时保存本场回填与实时尾部；只录当前时刻")
                session.data["catch_up"] = catch_up_evidence.to_dict()
                session.data["requested_mode"] = mode
                if not catch_up_evidence.available:
                    mode, command = "live_edge", at_live_edge(command)
                    session.data["mode"] = mode
                    session.event("mode_downgrade", reason=catch_up_evidence.reason)
                    self.log("[直播] 已降级为从当前时刻：" + catch_up_evidence.reason, "warn")
                    self.emit_event("live_recording", {"job_id": session.root.name, "degraded": True,
                                                        "reason": catch_up_evidence.reason})
                elif catch_up_evidence.strategy == "tail_and_backfill":
                    command = at_live_edge(command)
                    self.log("[直播] 已验证本场 VOD；先录实时尾部，独立回填，结束后核对重叠", "info")
                session.save()
            engine = self._engine(command, platform, url, config)
            declared = getattr(engine, "features", None)
            features = declared if isinstance(declared, EngineFeatures) else EngineFeatures()
            if features.per_file_tracks:
                expected = engine.expected_tracks
            session.data["comment_settings"] = {key: config.get(key, default) for key, default in
                {"LIVE_DANMAKU_ENABLED":0, "LIVE_DANMAKU_FORMATS":"srt,ass", "LIVE_DANMAKU_ANONYMIZE":0,
                 "LIVE_DANMAKU_OFFSET_MS":0}.items()}
            try:
                comments = CommentCapture(session, command, config, force_kill=self.force_kill, url=url)
                comments.start()
            except Exception as exc:
                session.data["comment_capture"] = {"status":"failed", "errors":[{"type":type(exc).__name__}]}
                self.log("[弹幕] 采集启动失败，媒体继续录制", "warn")
            attempt, next_reason = 0, "initial"
            while not cancel.is_set():
                directory, part = session.part(engine.name, [], next_reason)
                try:
                    cmd = engine.command(directory)
                except ProbeError as exc:
                    if platform != 'Rplay' or not exc.retryable or attempt >= max_retries:
                        raise
                    attempt += 1
                    next_reason = 'source_probe_error'
                    session.event(next_reason, attempt=attempt)
                    if cancel.wait(min(10 * 2 ** (attempt - 1), 30)):
                        reason = 'user'
                        break
                    continue
                media_clock = MediaClock(directory, command, checker.ffprobe) if config.get('LIVE_DANMAKU_ENABLED') else None
                if media_clock:
                    clocks.append((media_clock, part))
                part["process_cmd"] = redact_command(cmd)
                session.save()
                self.emit_event("live_recording", {"job_id": session.root.name, "engine": engine.name,
                                                     "part": len(session.data["parts"]), "report_dir": str(session.root)})
                env = self.paths.subprocess_env()
                if any(value == "--proxy" and cmd[index + 1] == "" for index, value in enumerate(cmd[:-1])):
                    for key in list(env):
                        if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "ftp_proxy"}:
                            env.pop(key, None)
                if engine.name == "bililive-recorder":
                    # CLI startup logging includes its raw arguments regardless of --flog.
                    env["BILILIVERECORDER_LOG_FILE_PATH"] = str(session.root / ".engine-logs" / "recorder.txt")
                    env["NO_PROXY"] = "127.0.0.1,localhost,::1"
                proc = process.spawn(cmd, cwd=str(engine.cwd if features.original_working_directory else session.root), env=env)
                if not self.publish_process(proc):
                    cancel.set()
                if (not cancel.is_set() and backfill is None and catch_up_evidence
                        and catch_up_evidence.available and catch_up_evidence.strategy == "tail_and_backfill"):
                    try:
                        backfill = BackfillJob(original_command, catch_up_evidence, session, env, self.force_kill)
                        backfill.start()
                    except Exception as exc:
                        warnings.append("backfill_start_failed_live_tail_retained")
                        session.event("backfill_start_failed", error=type(exc).__name__)
                        catch_up_evidence = CatchUpEvidence(False, "回填无法启动，实时尾部继续录制")
                lines, read_done, reader = self._reader(proc)
                started, last_activity, last_size = self.clock(), self.clock(), 0
                last_check, warned, stop_requested = 0, False, None
                fatal_error = False
                stream_failure = False
                events = getattr(engine, "events", None)
                while proc.poll() is None or not read_done.is_set() or not lines.empty():
                    now = self.clock()
                    if cancel.is_set():
                        stop_requested = "user"
                    elif deadline is not None and now >= deadline:
                        stop_requested = "timeout"
                    events = getattr(engine, "events", None)
                    if events and events.failed.is_set():
                        stop_requested = "error"
                    if events and events.stream_ended.is_set():
                        stop_requested = stop_requested or "ended"
                    if now - last_check >= 1:
                        paths = media_files(directory)
                        anchors = part.setdefault("media_anchors", {})
                        discovered = False
                        for path in paths if features.managed_outputs else ():
                            if path.stat().st_size:
                                key = str(path.with_suffix(""))
                                if key not in anchors:
                                    anchors[key] = time.time()
                                    discovered = True
                        if discovered:
                            session.save()
                        size = sum(p.stat().st_size for p in paths if p.exists())
                        if size > last_size:
                            last_activity, warned = now, False
                            if "media_started_at" not in part:
                                part["media_started_at"] = time.time()
                                part["anchor_source"] = "first_media_growth_estimate"
                                session.save()
                                if media_clock and features.clock_source:
                                    media_clock.start(lambda engine=engine, directory=directory:engine.clock_metadata(directory))
                            if timeout and deadline is None:
                                deadline = now + timeout
                        last_size, last_check = size, now
                        if shutil.disk_usage(session.media).free < minimum:
                            stop_requested = "disk_full"
                        stall = int(config.get("LIVE_WATCHDOG_SECONDS", 60))
                        if features.native_waiting and engine.waiting:
                            last_activity = now
                        if now - last_activity >= stall and not warned:
                            warned = True
                            session.event("watchdog_warning", idle_seconds=now - last_activity)
                            self.log("[直播] 输出与媒体文件均未增长，正在监测断流", "warn")
                        if now - last_activity >= stall * 2:
                            stop_requested = stop_requested or "watchdog"
                        elapsed = int(now - started)
                        self.progress(-1, f"直播录制中 · {engine.name} · {elapsed // 60}:{elapsed % 60:02d} · {size // 1024**2} MiB")
                    if stop_requested and proc.poll() is None:
                        self.progress(-1, "正在停止直播并收尾文件...")
                        try:
                            engine.stop_recording()
                        except (OSError, ValueError, EngineUnavailable):
                            session.event("control_api_stop_unavailable")
                        graceful = process.stop(proc, self.force_kill)
                        forced = forced or not graceful
                        # Drain queued final output before checking files. Webhooks can be reordered.
                    try:
                        line = lines.get(timeout=0.2)
                    except queue.Empty:
                        if proc.poll() is not None and read_done.is_set():
                            break
                        continue
                    if not line:
                        continue
                    if line.startswith('LIVE_CLOCK:'):
                        if media_clock:
                            try:
                                media_clock.start(json.loads(line[len('LIVE_CLOCK:'):]))
                            except (ValueError, TypeError):
                                session.event('clock_metadata_unavailable')
                        continue  # Never retain signed URLs/headers as raw logs.
                    # Only media growth/progress counts; repeated error logs cannot feed the watchdog.
                    if "[download]" in line and ("%" in line or "fragment" in line.lower()):
                        last_activity = now
                    if hasattr(engine, "line"):
                        engine.line(line)
                    if line.startswith("LIVE_META:"):
                        try:
                            metadata = json.loads(line[len("LIVE_META:"):])
                            if isinstance(metadata, dict):
                                if hasattr(engine, 'observe_metadata'):
                                    engine.observe_metadata(metadata)
                                title = metadata.get("title") or title
                                session.data["probe"] = metadata
                                session.save()
                                if metadata.get('live_status') in {'was_live', 'post_live', 'not_live'}:
                                    warnings.append('source_no_longer_live')
                                    stop_requested = 'error'
                                    session.event('source_no_longer_live')
                        except ValueError:
                            pass
                    if (any(value in line.lower() for value in ("login required", "drm", "private video", "unsupported url", "rplay private"))
                            or (platform != 'Rplay' and '403 forbidden' in line.lower())):
                        fatal_error = True
                    if any(value in line.lower() for value in (
                            'failed to reload playlist', 'failed to open segment', 'error when loading first segment',
                            'unable to download fragment', 'unable to download video data')):
                        stream_failure = True
                        warnings.append('stream_transport_interrupted')
                    if "ERROR" in line or "ERR]" in line or "FTL]" in line:
                        if platform == 'Rplay':
                            from video_downloader.platforms.rplay import sanitize_output
                            line = sanitize_output(line)
                        error_lines.append(line[:2000])
                        error_lines = error_lines[-16:]
                        if platform == "TwitCasting" and any(value in line for value in (
                                "--video-password", "format is not available", "Initialization fragment found")):
                            fatal_error = True
                        # Raw engine logs may contain signed URLs and cookies; retain only a marker.
                        session.event("engine_error", engine=engine.name)
                        self.log(f"[直播] {engine.name} 报告录制错误，结束后检查文件", "warn")
                        warnings.append("engine_reported_error")
                proc.wait(timeout=5)
                reader.join(timeout=2)
                proc.stdout.close()
                self.clear_process(proc)
                part.update(ended_at=time.time(), exit_code=proc.returncode)
                session.data["exit_codes"].append(proc.returncode)
                session.save()
                if events:
                    # Waiting is bounded and occurs on this recording's worker, never the HTTP thread.
                    if stop_requested:
                        events.session_ended.wait(timeout=2)
                    webhook_complete = (events.session_ended.is_set() and bool(events.closed)
                                        and events.opened.issubset(events.closed))
                    if events.timeline_has_gap():
                        warnings.append("native_recording_timeline_gap")
                has_media = bool(media_files(directory))
                if stop_requested in {"user", "timeout", "disk_full", "ended", "error"}:
                    reason = stop_requested
                    break
                if cancel.is_set():
                    reason = "user"
                    break
                if proc.returncode == 0 and not stop_requested and not stream_failure:
                    if hasattr(engine, 'source_ended') and not engine.source_ended():
                        warnings.append('source_still_live_after_eof')
                        stream_failure = True
                        session.event('source_still_live_after_eof')
                    else:
                        reason = "crash" if engine.name == "withny-dl" else "ended"
                        break
                # Startup-only BR failures may fall back; never append yt-dlp to a BR session with media.
                if engine.name == "withny-dl":
                    reason = "crash"
                    break
                if engine.name == "bililive-recorder":
                    engine.close()
                    if not has_media and attempt == 0 and not fatal_error:
                        self.log("[直播] 录播姬启动失败，已降级为 yt-dlp LIVE_EDGE", "warn")
                        session.event("engine_fallback", reason="startup_failed")
                        engine = YtDlpEngine(command)
                        webhook_complete = True
                    else:
                        reason = "crash"
                        break
                elif (mode == "catch_up" and catch_up_evidence and catch_up_evidence.strategy == "single_from_start"
                      and "--live-from-start" in engine.original):
                    # A successful probe can go stale. Failures in the catch-up
                    # path do not consume the only chance to record the live edge.
                    engine.original = at_live_edge(engine.original)
                    warnings.append("catch_up_failed_live_edge_retained")
                    session.event("catch_up_failed_fallback_to_edge")
                    self.log("[直播] 追播失败，转为从当前时刻录制；已下载分段保留", "warn")
                elif fatal_error or attempt >= max_retries:
                    reason = "watchdog" if stop_requested == "watchdog" else "crash"
                    break
                attempt += 1
                next_reason = stop_requested or "process_error"
                # A fresh part intentionally starts at live edge after a retry.
                if isinstance(engine, YtDlpEngine):
                    engine.original = [v for v in engine.original if v not in {"--live-from-start", "--no-live-from-start"}]
                    engine.original += ["--no-live-from-start"]
                if cancel.wait(min(10 * 2 ** (attempt - 1), 30)):
                    reason = "user"
                    break
            else:
                reason = "user"
        except Exception as exc:
            session.event("exception", error=type(exc).__name__, frames=[
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(exc.__traceback__)[-4:]])
            self.log(f"[直播] 录制异常：{type(exc).__name__}；详情请检查会话报告", "error")
            if proc and proc.poll() is None:
                forced = not process.stop(proc, self.force_kill)
        finally:
            for media_clock, _ in clocks:
                media_clock.stop()
            if proc:
                self.clear_process(proc)
            if engine:
                engine.close()
            if comments:
                try:
                    result = comments.finish()
                    if result:
                        session.data["comment_capture"] = result
                except Exception as exc:
                    session.data["comment_capture"] = {"status":"failed", "errors":[{"type":type(exc).__name__}]}
            try:
                backfill_result = backfill.finish() if backfill else None
            except Exception as exc:
                backfill_result = {"error": type(exc).__name__}
                warnings.append("backfill_stop_failed_live_tail_retained")
            # Raw CLI startup logs include credentials. Keep only our redacted journal.
            log_dir = session.root / ".engine-logs"
            if log_dir.is_dir():
                try:
                    for log_file in log_dir.iterdir():
                        if log_file.is_file():
                            log_file.unlink(missing_ok=True)
                    log_dir.rmdir()
                except OSError:
                    warnings.append("engine_log_cleanup_failed")
            self.progress(-1, "正在验证直播文件并生成完整性报告...")
            outputs = engine.output_files(session.media) if features.managed_outputs else media_files(session.media)
            report = checker.report(outputs, reason=reason,
                                    exit_codes=session.data["exit_codes"], mode=mode,
                                    expected=expected, retries=len(session.data["retries"]),
                                    forced=forced, warnings=list(dict.fromkeys(warnings)),
                                    webhook_complete=webhook_complete)
            if features.annotate_report:
                engine.annotate(report)
            for media_clock, part in clocks:
                media_clock.annotate(report, part)
            for file in report["files"]:
                anchor = next((p.get("media_anchors", {}).get(str(Path(file["path"]).with_suffix("")))
                               for p in session.data["parts"]
                               if str(Path(file["path"]).with_suffix("")) in p.get("media_anchors", {})), None)
                if features.managed_outputs and anchor is not None and "anchor_utc" not in file:
                    file.update(anchor_utc=anchor, anchor_source="first_media_growth_estimate")
            if backfill:
                report["backfill"] = backfill_result
                report["catch_up"] = catch_up_evidence.to_dict()
                joined = reconcile(session, checker, media_files(backfill.directory), report)
                if joined["status"] != "joined" and report["conclusion"] != "failed":
                    report["conclusion"] = "gaps"
                    report["warnings"].append("backfill_join_unverified_live_tail_retained")
            elif features.concatenate:
                checker.concatenate(session, report)
            if catch_up_evidence:
                report["catch_up"] = catch_up_evidence.to_dict()
            if str(config.get("AUDIO_MODE", "0")) == "2" and report["files"] and report["conclusion"] != "failed":
                self.progress(-1, "正在导出直播音频...")
                audio_format = config.get("AUDIO_FORMAT", "mp3")
                codec = {"mp3": ["-c:a", "libmp3lame", "-b:a", "320k"],
                         "m4a": ["-c:a", "aac", "-b:a", "256k"], "wav": ["-c:a", "pcm_s16le"]}.get(audio_format)
                if codec:
                    source = report.get("joined", report["files"][0])["path"]
                    audio = session.root / ("audio." + audio_format)
                    try:
                        exported = subprocess.run([checker.ffmpeg, "-v", "error", "-nostdin", "-y", "-i", source,
                                                   "-vn", *codec, str(audio)], capture_output=True, timeout=120,
                                                  **process.hidden_options())
                        checked = checker.inspect(audio, "a")
                        if exported.returncode or not checked["valid"]:
                            raise OSError("audio export failed")
                        report["audio_exports"] = [checked]
                    except (OSError, subprocess.TimeoutExpired):
                        report["warnings"].append("audio_export_failed_media_retained")
                        report["conclusion"] = "gaps"
            try:
                report["comments"] = process_comments(session, report, config)
            except Exception as exc:
                report["comments"] = {"status": "failed", "error": type(exc).__name__}
            session.data["comments"] = report["comments"]
            if report["comments"]["status"] in {"failed", "partial", "unavailable"}:
                self.log("[弹幕] 导出未完全完成，媒体录制结果保留；请查看 comments-report.json", "warn")
            session.finish(reason, report)
            title = (session.data.get("probe") or {}).get("title") or title
        report_path = str(session.root / "integrity-report.json")
        self.emit_event("live_recording", {"job_id": session.root.name, "engine": getattr(engine, "name", ""),
                                             "conclusion": report["conclusion"], "stop_reason": reason,
                                             "comments": report.get("comments", {}),
                                             "report": report_path})
        if report["conclusion"] == "failed":
            status = "fail"
        elif reason == "user":
            status = "stopped" if report["conclusion"] in {"complete", "from_earliest_available", "cancelled_before_recording"} else "gaps"
        elif reason == "timeout":
            status = "timeout"
        elif report["conclusion"] == "gaps":
            status = "gaps"
        elif report["conclusion"] == "from_earliest_available":
            status = "earliest"
        else:
            status = "success"
        paths = report["files"]
        return {"status": status, "title": title, "report": report_path,
                "output": report.get("joined", {}).get("path", paths[0]["path"] if paths else ""),
                "conclusion": report["conclusion"], "stop_reason": reason,
                "error_lines": error_lines}
