import base64
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

from video_downloader.core.constants import DEFAULT_SUBTITLE_LANGS, LEGACY_ALL_SUBTITLE_LANGS, RECOMMENDED_SUBTITLE_LANGS, SUBTITLE_TYPE_OPTIONS
from video_downloader.core.paths import AppPaths
from video_downloader.core.platform import clean_url, detect_platform
from video_downloader.core.subtitles import classify_subtitle_result
from video_downloader.core.thumbnails import classify_thumbnail_result, thumbnail_written_path
from video_downloader.services.audio_tools import AudioToolService, resolve_directory
from video_downloader.services.download_manager import DownloadManager


class ToolService:
    def __init__(self, tool_dir, exe_suffix, app_state, save_config, log,
                 build_subtitle_command: Callable[..., list[str]] | None = None,
                 build_cover_command: Callable[..., list[str]] | None = None,
                 download_manager=None, broadcast_download_state=None,
                 cancel_idle_timer=None, start_idle_timer=None, has_active_downloads=None):
        self._tool_dir = Path(tool_dir).resolve()
        self._paths = AppPaths(self._tool_dir)
        self._exe_suffix = exe_suffix
        self._app_state = app_state
        self._save_config = save_config
        self._log = log
        self._download_dir = self._paths.download_dir
        self._log_dir = self._paths.log_dir
        self._build_subtitle_command = build_subtitle_command
        self._build_cover_command = build_cover_command
        self._download_manager = download_manager or DownloadManager()
        self._broadcast_download_state = broadcast_download_state or (lambda: None)
        self._cancel_idle_timer = cancel_idle_timer or (lambda: None)
        self._start_idle_timer = start_idle_timer or (lambda: None)
        self._has_active_downloads = has_active_downloads or (lambda: False)
        self._audio = AudioToolService(
            self._paths, exe_suffix, self._download_manager, log,
            self._broadcast_download_state, self._cancel_idle_timer,
            self._start_idle_timer, getattr(app_state, 'publish', None),
        )

    def _begin_maintenance(self):
        if self._download_manager is not None and not self._download_manager.suspend():
            return {"error": "请先停止当前下载任务"}
        if self._has_active_downloads():
            self._end_maintenance()
            return {"error": "请先完成或取消任务队列"}
        self._cancel_idle_timer()
        self._broadcast_download_state()
        return None

    def _end_maintenance(self):
        if self._download_manager is not None:
            self._download_manager.resume()
        self._broadcast_download_state()
        self._start_idle_timer()

    @staticmethod
    def _should_retry_recommended_subtitles(langs, output):
        if langs != LEGACY_ALL_SUBTITLE_LANGS:
            return False
        return "HTTP Error 429" in output or "Too Many Requests" in output

    def check_deps(self):
        deps = {}
        for dep in ["yt-dlp", "ffmpeg", "ffprobe"]:
            deps[dep] = self._paths.executable(dep, self._exe_suffix).exists()
        deps["fantiadl"] = self._paths.executable("fantiadl", self._exe_suffix).exists()
        deps["withny_dl"] = self._paths.executable("withny-dl-windows-amd64", self._exe_suffix).exists()
        from video_downloader.live.engines.withnydl import managed_binary
        deps['withny_live_chat'] = managed_binary(self._paths.dependency_dir) is not None
        deps['withny_dl'] = deps['withny_dl'] or deps['withny_live_chat']
        deps["nicochannel_plugin"] = self._paths.dependency("nicochannel.zip").exists()
        deps["youtube_po_token"] = all(path.exists() for path in (
            self._paths.executable("deno", self._exe_suffix),
            self._paths.dependency("yt-dlp-plugins/bgutil-ytdlp-pot-provider.zip"),
            self._paths.dependency("bgutil-ytdlp-pot-provider/server/src/main.ts"),
            self._paths.dependency("bgutil-ytdlp-pot-provider/server/node_modules"),
        ))
        from video_downloader.live.danmaku.dependencies import health
        deps.update(health())
        return deps

    def pick_withny_archive(self):
        try:
            har_path = self._pick_windows_file(
                initialdir=str(self._tool_dir),
                title="选择包含内容的 Withny HAR 文件",
                filter="HAR 文件 (*.har)|*.har|所有文件 (*.*)|*.*",
                filetypes=[("HAR 文件", "*.har"), ("所有文件", "*.*")],
            )
            if not har_path:
                return {"ok": True, "cancelled": True}
            output_path = self._save_windows_file(
                initialdir=str(self._download_dir / "Withny"),
                title="保存 Withny 历史存档",
                default_ext="mp4",
                filter="MP4 视频 (*.mp4)|*.mp4|MKV 视频 (*.mkv)|*.mkv|TS 视频 (*.ts)|*.ts",
            )
            if not output_path:
                return {"ok": True, "cancelled": True}
            return {"ok": True, "har_path": har_path, "output_path": output_path}
        except Exception as exc:
            return {"error": f"打开文件选择失败: {exc}"}

    def pick_withny_live_config(self):
        try:
            config_path = self._pick_windows_file(
                initialdir=str(self._tool_dir),
                title="选择 withny-dl 直播录制配置",
                filter="YAML 配置 (*.yaml;*.yml)|*.yaml;*.yml|所有文件 (*.*)|*.*",
                filetypes=[("YAML 配置", "*.yaml *.yml"), ("所有文件", "*.*")],
            )
            if not config_path:
                return {"ok": True, "cancelled": True}
            return {"ok": True, "config_path": config_path}
        except Exception as exc:
            return {"error": f"打开文件选择失败: {exc}"}

    @staticmethod
    def _powershell_literal(value):
        return "'" + str(value).replace("'", "''") + "'"

    def _run_windows_file_dialog(self, dialog_type, initialdir, title, filter_text, default_ext=""):
        script = f"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.{dialog_type}
$dialog.Title = {self._powershell_literal(title)}
$dialog.Filter = {self._powershell_literal(filter_text)}
$dialog.InitialDirectory = {self._powershell_literal(initialdir)}
"""
        if default_ext:
            script += f"$dialog.DefaultExt = {self._powershell_literal(default_ext)}\n$dialog.AddExtension = $true\n"
        script += """
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$dialog.FileName))
}
$dialog.Dispose()
"""
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "PowerShell 文件对话框启动失败").strip()
            raise RuntimeError(detail)
        encoded_path = (result.stdout or "").strip().splitlines()
        if not encoded_path:
            return ""
        return base64.b64decode(encoded_path[-1]).decode("utf-8")

    def _pick_windows_file(self, initialdir, title, filter, filetypes):
        root = None
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            return filedialog.askopenfilename(
                initialdir=initialdir,
                title=title,
                filetypes=filetypes,
            )
        except Exception:
            return self._run_windows_file_dialog(
                "OpenFileDialog", initialdir, title, filter
            )
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def _save_windows_file(self, initialdir, title, default_ext, filter):
        root = None
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            return filedialog.asksaveasfilename(
                initialdir=initialdir,
                title=title,
                defaultextension="." + default_ext,
                filetypes=[("视频文件", "*.mp4 *.mkv *.ts")],
            )
        except Exception:
            return self._run_windows_file_dialog(
                "SaveFileDialog", initialdir, title, filter, default_ext
            )
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def update_ytdlp(self):
        ytdlp = self._paths.executable("yt-dlp", self._exe_suffix)
        if not ytdlp.exists():
            return {"error": "未找到yt-dlp.exe"}
        error = self._begin_maintenance()
        if error:
            return error

        def run():
            try:
                env = self._paths.subprocess_env()
                env["PYTHONUTF8"] = "1"
                proc = subprocess.run([str(ytdlp), "-U"], cwd=self._tool_dir, env=env,
                                      capture_output=True, text=True, encoding='utf-8',
                                      errors='replace', timeout=120)
                for line in (proc.stdout or "").split("\n"):
                    if line.strip():
                        self._log(f"[yt-dlp] {line.strip()}", "info")
                if proc.returncode == 0:
                    self._log("[yt-dlp] 更新完成", "success")
                else:
                    self._log(f"[yt-dlp] 更新失败: {proc.stderr}", "error")
            except Exception as exc:
                self._log(f"[yt-dlp] 更新异常: {exc}", "error")
            finally:
                self._end_maintenance()
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self._end_maintenance()
            raise
        return {"ok": True}

    def download_subtitles(self, urls, subtitle_type, subtitle_langs):
        if self._has_active_downloads():
            return {"error": "请先完成或取消任务队列，再单独下载字幕"}
        ytdlp = self._paths.executable("yt-dlp", self._exe_suffix)
        if not ytdlp.exists():
            return {"error": "未找到yt-dlp.exe"}
        if self._build_subtitle_command is None:
            return {"error": "字幕下载命令未配置"}
        cleaned_urls = []
        for url in urls:
            if isinstance(url, str):
                cleaned = clean_url(url)
                if cleaned:
                    cleaned_urls.append(cleaned)
        if not cleaned_urls:
            return {"error": "请输入至少一个视频链接"}
        if subtitle_type not in SUBTITLE_TYPE_OPTIONS:
            return {"error": "字幕类型无效"}
        langs = (subtitle_langs or DEFAULT_SUBTITLE_LANGS).strip()
        if not langs:
            langs = DEFAULT_SUBTITLE_LANGS
        if len(langs) > 200:
            return {"error": "字幕语言设置长度不能超过 200 字符"}
        if self._download_manager is None:
            return {"error": "字幕下载任务管理器未配置"}
        handle = self._download_manager.begin("subtitles")
        if handle is None:
            return {"error": "已有下载任务正在运行"}
        if self._has_active_downloads():
            self._download_manager.finish(handle)
            return {"error": "请先完成或取消任务队列，再单独下载字幕"}
        self._cancel_idle_timer()
        self._broadcast_download_state()

        def run():
            success = missing = fail = 0
            try:
                self._log(f"[字幕下载] 开始处理 {len(cleaned_urls)} 个链接", "info")
                env = self._paths.subprocess_env()
                env["PYTHONUTF8"] = "1"
                for index, url in enumerate(cleaned_urls, 1):
                    if handle.cancel_event.is_set():
                        break
                    self._log(f"[{index}/{len(cleaned_urls)}] 字幕下载: {url}", "info")
                    try:
                        def run_command(language_value):
                            cmd = self._build_subtitle_command(
                                url,
                                subtitle_type=subtitle_type,
                                subtitle_langs=language_value,
                            )
                            proc = subprocess.Popen(
                                cmd, cwd=self._tool_dir, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace",
                            )
                            if not self._download_manager.publish_process(handle, proc):
                                proc.kill()
                                proc.wait()
                                return None, ""
                            try:
                                try:
                                    stdout, stderr = proc.communicate(timeout=600)
                                except subprocess.TimeoutExpired:
                                    proc.kill()
                                    proc.communicate()
                                    raise
                                output = "\n".join(part for part in (stdout, stderr) if part).strip()
                                if detect_platform(url) == 'Rplay':
                                    from video_downloader.platforms.rplay import sanitize_output
                                    output = sanitize_output(output)
                                return proc.returncode, output
                            finally:
                                self._download_manager.clear_process(handle, proc)

                        returncode, output = run_command(langs)
                        if returncode is None:
                            break
                        if returncode != 0 and self._should_retry_recommended_subtitles(langs, output):
                            self._log("  -> 全量字幕请求被限流，改用常用字幕重试", "warn")
                            returncode, output = run_command(RECOMMENDED_SUBTITLE_LANGS)
                            if returncode is None:
                                break
                        result = classify_subtitle_result(returncode, output)
                        if result == "success":
                            self._log("  -> 字幕处理完成", "success")
                            success += 1
                        elif result == "missing":
                            detail = output.splitlines()[-1][:300] if output else "yt-dlp 未写出字幕文件"
                            self._log(f"  -> 未找到匹配字幕: {detail}", "warn")
                            missing += 1
                        else:
                            detail = output.splitlines()[-1][:300] if output else ""
                            suffix = f": {detail}" if detail else ""
                            self._log(f"  -> 字幕下载失败或无可用字幕{suffix}", "warn")
                            fail += 1
                    except subprocess.TimeoutExpired:
                        self._log("  -> 字幕下载超时", "warn")
                        fail += 1
                    except Exception as exc:
                        if not handle.cancel_event.is_set():
                            self._log(f"  -> 字幕下载异常: {exc}", "warn")
                            fail += 1
                if handle.cancel_event.is_set():
                    self._log("[字幕下载] 已停止", "warn")
                else:
                    level = "success" if fail == 0 and missing == 0 else "warn"
                    self._log(f"[字幕下载] 完成: 成功{success} 未找到{missing} 失败{fail}", level)
            finally:
                self._download_manager.finish(handle)
                self._broadcast_download_state()
                self._start_idle_timer()

        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self._download_manager.finish(handle)
            self._broadcast_download_state()
            self._start_idle_timer()
            return {"error": "字幕下载任务启动失败"}
        return {"ok": True, "total": len(cleaned_urls)}

    def download_covers(self, urls):
        """批量下载封面：逐条识别平台，封面文件名与对应视频完全一致。"""
        if self._has_active_downloads():
            return {"error": "请先完成或取消任务队列，再单独下载封面"}
        ytdlp = self._paths.executable("yt-dlp", self._exe_suffix)
        if not ytdlp.exists():
            return {"error": "未找到yt-dlp.exe"}
        if self._build_cover_command is None:
            return {"error": "封面下载命令未配置"}
        cleaned_urls = []
        for url in urls:
            if isinstance(url, str):
                cleaned = clean_url(url)
                if cleaned:
                    cleaned_urls.append(cleaned)
        if not cleaned_urls:
            return {"error": "请输入至少一个视频链接"}
        if self._download_manager is None:
            return {"error": "封面下载任务管理器未配置"}
        handle = self._download_manager.begin("covers")
        if handle is None:
            return {"error": "已有下载任务正在运行"}
        if self._has_active_downloads():
            self._download_manager.finish(handle)
            return {"error": "请先完成或取消任务队列，再单独下载封面"}
        self._cancel_idle_timer()
        self._broadcast_download_state()

        def run():
            success = missing = skipped = fail = 0
            try:
                self._log(f"[封面下载] 开始处理 {len(cleaned_urls)} 个链接", "info")
                env = self._paths.subprocess_env()
                env["PYTHONUTF8"] = "1"
                for index, url in enumerate(cleaned_urls, 1):
                    if handle.cancel_event.is_set():
                        break
                    detected = detect_platform(url)
                    if detected is None:
                        # 未识别的域名既确定不了落盘目录，也确定不了用哪个平台参数，
                        # 宁可明确跳过，也不要把封面写进错误的平台目录。
                        self._log(
                            f"[{index}/{len(cleaned_urls)}] 未识别的平台，已跳过: {url}", "warn"
                        )
                        skipped += 1
                        continue
                    # Fantia 由 fantiadl 处理、Withny 走自建 HLS 流程，都不经过 yt-dlp，
                    # 因此没有可复用的封面命令。
                    if detected == "Fantia":
                        self._log(
                            f"[{index}/{len(cleaned_urls)}] Fantia 暂不支持单独下载封面，已跳过",
                            "warn",
                        )
                        skipped += 1
                        continue
                    self._log(f"[{index}/{len(cleaned_urls)}] 封面下载: {url}", "info")
                    try:
                        cmd = self._build_cover_command(url, platform_override=detected)
                        proc = subprocess.Popen(
                            cmd, cwd=self._tool_dir, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                        )
                        if not self._download_manager.publish_process(handle, proc):
                            proc.kill()
                            proc.wait()
                            break
                        try:
                            try:
                                output, _ = proc.communicate(timeout=600)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.communicate()
                                raise
                            returncode = proc.returncode
                        finally:
                            self._download_manager.clear_process(handle, proc)

                        if detected == 'Rplay':
                            from video_downloader.platforms.rplay import sanitize_output
                            output = sanitize_output(output or '')
                        result = classify_thumbnail_result(returncode, output)
                        if result == "success":
                            self._log(
                                f"  -> 已保存: {Path(thumbnail_written_path(output)).name}",
                                "success",
                            )
                            success += 1
                        elif result == "missing":
                            self._log("  -> 未找到可用封面", "warn")
                            missing += 1
                        else:
                            detail = (output or "").strip().splitlines()[-1][:300] \
                                if (output or "").strip() else ""
                            suffix = f": {detail}" if detail else ""
                            self._log(f"  -> 封面下载失败{suffix}", "warn")
                            fail += 1
                    except subprocess.TimeoutExpired:
                        self._log("  -> 封面下载超时", "warn")
                        fail += 1
                    except Exception as exc:
                        if not handle.cancel_event.is_set():
                            self._log(f"  -> 封面下载异常: {exc}", "warn")
                            fail += 1
                if handle.cancel_event.is_set():
                    self._log("[封面下载] 已停止", "warn")
                else:
                    level = "success" if fail == 0 and missing == 0 and skipped == 0 else "warn"
                    self._log(
                        f"[封面下载] 完成: 成功{success} 未找到{missing} 跳过{skipped} 失败{fail}",
                        level,
                    )
            finally:
                self._download_manager.finish(handle)
                self._broadcast_download_state()
                self._start_idle_timer()

        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self._download_manager.finish(handle)
            self._broadcast_download_state()
            self._start_idle_timer()
            return {"error": "封面下载任务启动失败"}
        return {"ok": True, "total": len(cleaned_urls)}

    def clean_temp(self):
        error = self._begin_maintenance()
        if error:
            return error
        try:
            return self._clean_temp_files()
        finally:
            self._end_maintenance()

    def _clean_temp_files(self):
        count = 0
        temp_ext = [".part", ".ytdl", ".temp", ".tmp"]
        for file in self._download_dir.rglob("*"):
            if (file.is_file() and file.suffix.lower() in temp_ext
                    and '.live-jobs' not in file.relative_to(self._download_dir).parts
                    and file.resolve().is_relative_to(self._download_dir.resolve())):
                try:
                    file.unlink()
                    count += 1
                except Exception:
                    pass
        for directory in sorted(self._download_dir.rglob("*"), reverse=True):
            if (directory.is_dir()
                    and '.live-jobs' not in directory.relative_to(self._download_dir).parts
                    and directory.resolve().is_relative_to(self._download_dir.resolve())):
                try:
                    if not any(directory.iterdir()):
                        directory.rmdir()
                except Exception:
                    pass
        self._log(f"[清理] 完成，删除 {count} 个临时文件", "success")
        return {"ok": True, "count": count}

    def gen_url_template(self):
        template = self._tool_dir / "urls.txt"
        content = """# ============================================
# 混合平台批量下载链接模板
# 每行一个链接，# 开头为注释行
# ============================================

# YouTube
# https://www.youtube.com/watch?v=xxxxxxxxxxx
# https://www.youtube.com/playlist?list=xxxxxxxxxxx

# Twitch
# https://www.twitch.tv/videos/xxxxxxxxxx

# Niconico
# https://www.nicovideo.jp/watch/smxxxxxxxx

# NicoChannel
# https://nicochannel.jp/channelname/video/xxxxx

# Fantia
# https://fantia.jp/posts/xxxxxxx
"""
        if template.exists():
            self._log("urls.txt 已存在", "warn")
            return {"ok": True, "existed": True}
        try:
            template.write_text(content, encoding="utf-8")
        except OSError as exc:
            return {"error": f"生成 urls.txt 失败: {exc}"}
        self._log("已生成 urls.txt 模板", "success")
        return {"ok": True}

    def stop_audio_tool(self):
        return self._audio.stop()

    def audio_convert(self, target_dir, recursive=False, output_format='mp3',
                      del_src=False, **options):
        result = self._audio.start('convert', target_dir, recursive, output_format,
                                   delete_source=del_src, **options)
        if result.get('ok'):
            self._app_state.update_config({
                'AUDIO_OUTPUT_FORMAT': output_format,
                'AUDIO_RECURSIVE': int(recursive),
            })
            try:
                self._save_config()
            except OSError as exc:
                self._log(f'音频任务已启动，偏好保存失败: {exc}', 'warn')
        return result

    def wav_to_mp3(self, target_dir, recursive, bitrate, del_src):
        # Keep the legacy API available for portable releases using cached UI.
        return self.audio_convert(target_dir, recursive, 'mp3', del_src,
                                  bitrate=bitrate, wav_only=True)

    def audio_loudnorm(self, target_dir, recursive, mode, i_target, lra_target,
                       tp_target, output_dir, output_format):
        return self._audio.start('loudnorm', target_dir, recursive, output_format,
                                 output_dir, mode=mode, i_target=i_target,
                                 lra_target=lra_target, tp_target=tp_target)

    def audio_volume(self, target_dir, recursive, gain_db, limiter_enabled,
                     output_dir, output_format):
        return self._audio.start('volume', target_dir, recursive, output_format,
                                 output_dir, gain_db=gain_db,
                                 limiter_enabled=limiter_enabled)

    def browse_folder(self):
        root = None
        try:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                folder = filedialog.askdirectory(initialdir=str(self._download_dir))
            except Exception:
                script = f"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择音频文件所在文件夹'
$dialog.SelectedPath = {self._powershell_literal(self._download_dir)}
try {{
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
        [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$dialog.SelectedPath))
    }}
}} finally {{ $dialog.Dispose() }}
"""
                result = subprocess.run(
                    ['powershell', '-NoProfile', '-STA', '-Command', script],
                    capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=300,
                )
                if result.returncode:
                    raise RuntimeError((result.stderr or '文件夹对话框启动失败').strip())
                lines = (result.stdout or '').strip().splitlines()
                folder = base64.b64decode(lines[-1], validate=True).decode('utf-8') if lines else ''
            if folder:
                folder = str(resolve_directory(folder, self._tool_dir))
                self._log(f'[浏览文件夹] 已选择: {folder}', 'info')
            return {'ok': True, 'path': folder}
        except Exception as exc:
            return {'error': f'打开文件夹选择失败: {exc}'}
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def open_folder(self, folder_path):
        try:
            path = resolve_directory(folder_path, self._tool_dir, must_exist=False)
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
            return {"ok": True, "message": f"已打开: {path}"}
        except Exception as exc:
            return {"error": f"打开文件夹失败: {exc}"}

    def gen_cookie_template(self):
        cookie_file = self._tool_dir / "cookies.txt"
        if cookie_file.exists():
            self._log("[Cookie模板] cookies.txt 已存在，跳过生成", "warn")
            return {"ok": True, "existed": True}

        content = """# Netscape HTTP Cookie File
# =====================================================
# 这是空白格式模板，不含真实登录 Cookie。
# 请在已登录的浏览器中使用「Get cookies.txt LOCALLY」等扩展，
# 导出 Netscape 格式 Cookie 后，用导出的文件替换本文件。
# =====================================================
#
# 使用说明：
# 1. 第一行必须保留 Netscape 格式标识，不要翻译或在它前面添加文字。
# 2. 文件使用 UTF-8 无 BOM 编码；说明文字均以 # 开头，作为注释。
# 3. 每条 Cookie 包含 7 个字段，字段之间必须使用实际 TAB 制表符。
#    字段顺序：域名、是否包含子域、路径、是否仅 HTTPS、过期时间、名称、值。
#
# 安全提示：Cookie 可能包含账号登录凭证，请勿分享或提交到公开仓库。
# Fantia 需要使用 Cookie 文件模式，不能使用浏览器提取模式。
#
# 以下仅为注释形式的格式示例，不是有效登录凭证；请使用实际导出的内容：
# .youtube.com	TRUE	/	TRUE	0	LOGIN_INFO	xxxxxxxxxxxxxxxxxxxx
# .twitch.tv	TRUE	/	TRUE	0	auth-token	xxxxxxxxxxxxxxxxxxxx
"""
        try:
            cookie_file.write_text(content, encoding="utf-8")
            self._log("[Cookie模板] 已生成空白 Netscape 格式模板；登录 Cookie 请从浏览器导出后替换", "success")
            return {"ok": True}
        except Exception as exc:
            self._log(f"[Cookie模板] 生成失败: {exc}", "error")
            return {"error": str(exc)}

    def read_urls_file(self):
        url_file = self._tool_dir / "urls.txt"
        if not url_file.exists():
            return None, "未找到 urls.txt 文件，请先生成模板"

        urls = []
        try:
            with open(url_file, "r", encoding="utf-8-sig") as file:
                for line in file:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        urls.append(line)
        except Exception as exc:
            return None, f"读取 urls.txt 失败: {exc}"

        if not urls:
            return None, "urls.txt 中没有有效链接"
        return urls, None

    def handle_tool_action(self, action):
        actions = {
            "gen-template": self.gen_url_template,
            "gen-cookie-template": self.gen_cookie_template,
            "update-ytdlp": self.update_ytdlp,
            "clean-temp": self.clean_temp,
            "open-downloads": lambda: self.open_folder(self._download_dir),
            "open-logs": lambda: self.open_folder(self._log_dir),
        }
        handler = actions.get(action)
        if handler is None:
            return {"error": f"未知工具操作: {action}"}
        return handler()
