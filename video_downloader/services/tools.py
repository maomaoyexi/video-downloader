import json
import os
import re
import subprocess
import threading
from pathlib import Path

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wma', '.ac3', '.aiff', '.aif', '.wv', '.ape'}

AUDIO_CODEC_CONFIG = {
    'mp3':  {'codec': 'libmp3lame', 'bitrate': '320k'},
    'm4a':  {'codec': 'aac',        'bitrate': '256k'},
    'aac':  {'codec': 'aac',        'bitrate': '256k'},
    'wav':  {'codec': 'pcm_s16le',  'bitrate': None},
    'flac': {'codec': 'flac',       'bitrate': None, 'compression': '5'},
    'ogg':  {'codec': 'libvorbis',  'bitrate': None, 'qscale': '7'},
    'opus': {'codec': 'libopus',    'bitrate': '192k'},
    'ac3':  {'codec': 'ac3',        'bitrate': '448k'},
}


class ToolService:
    def __init__(self, tool_dir, exe_suffix, app_state, save_config, log):
        self._tool_dir = tool_dir
        self._exe_suffix = exe_suffix
        self._app_state = app_state
        self._save_config = save_config
        self._log = log
        self._log_dir = tool_dir / "logs"

    def check_deps(self):
        deps = {}
        for dep in ["yt-dlp", "ffmpeg", "ffprobe"]:
            deps[dep] = (self._tool_dir / f"{dep}{self._exe_suffix}").exists()
        deps["fantiadl"] = (self._tool_dir / f"fantiadl{self._exe_suffix}").exists()
        deps["withny_dl"] = (self._tool_dir / f"withny-dl-windows-amd64{self._exe_suffix}").exists()
        deps["nicochannel_plugin"] = (self._tool_dir / "nicochannel.zip").exists()
        return deps

    def pick_withny_archive(self):
        root = None
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            har_path = filedialog.askopenfilename(
                initialdir=str(self._tool_dir),
                title="选择包含内容的 Withny HAR 文件",
                filetypes=[("HAR 文件", "*.har"), ("所有文件", "*.*")],
            )
            if not har_path:
                return {"ok": True, "cancelled": True}
            output_path = filedialog.asksaveasfilename(
                initialdir=str(self._tool_dir / "Withny"),
                title="保存 Withny 历史存档",
                defaultextension=".mp4",
                filetypes=[("MP4 视频", "*.mp4"), ("MKV 视频", "*.mkv"), ("TS 视频", "*.ts")],
            )
            if not output_path:
                return {"ok": True, "cancelled": True}
            return {"ok": True, "har_path": har_path, "output_path": output_path}
        except Exception as exc:
            return {"error": f"打开文件选择失败: {exc}"}
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def pick_withny_live_config(self):
        root = None
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            config_path = filedialog.askopenfilename(
                initialdir=str(self._tool_dir),
                title="选择 withny-dl 直播录制配置",
                filetypes=[("YAML 配置", "*.yaml *.yml"), ("所有文件", "*.*")],
            )
            if not config_path:
                return {"ok": True, "cancelled": True}
            return {"ok": True, "config_path": config_path}
        except Exception as exc:
            return {"error": f"打开文件选择失败: {exc}"}
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def update_ytdlp(self):
        ytdlp = self._tool_dir / f"yt-dlp{self._exe_suffix}"
        if not ytdlp.exists():
            return {"error": "未找到yt-dlp.exe"}

        def run():
            try:
                env = os.environ.copy()
                env["PYTHONUTF8"] = "1"
                proc = subprocess.run([str(ytdlp), "-U"], cwd=self._tool_dir, env=env, capture_output=True, text=True, timeout=120)
                for line in (proc.stdout or "").split("\n"):
                    if line.strip():
                        self._log(f"[yt-dlp] {line.strip()}", "info")
                if proc.returncode == 0:
                    self._log("[yt-dlp] 更新完成", "success")
                else:
                    self._log(f"[yt-dlp] 更新失败: {proc.stderr}", "error")
            except Exception as exc:
                self._log(f"[yt-dlp] 更新异常: {exc}", "error")
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def clean_temp(self):
        count = 0
        temp_ext = [".part", ".ytdl", ".temp", ".tmp"]
        for file in self._tool_dir.rglob("*"):
            if file.is_file() and file.suffix.lower() in temp_ext:
                try:
                    file.unlink()
                    count += 1
                except Exception:
                    pass
        for directory in sorted(self._tool_dir.rglob("*"), reverse=True):
            if directory.is_dir():
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
        template.write_text(content, encoding="utf-8")
        self._log("已生成 urls.txt 模板", "success")
        return {"ok": True}

    def wav_to_mp3(self, target_dir, recursive, bitrate, del_src):
        ffmpeg = self._tool_dir / f"ffmpeg{self._exe_suffix}"
        if not ffmpeg.exists():
            return {"error": "ffmpeg.exe未找到"}
        target = Path(target_dir)
        if not target.exists():
            return {"error": "目录不存在"}

        # 主线程扫描一次 WAV 文件列表，避免后台线程二次 glob 的 TOCTOU 问题
        pattern = "**/*.wav" if recursive else "*.wav"
        wav_files = sorted([file for file in target.glob(pattern) if file.is_file()])

        self._app_state.update_config({
            "MP3_BITRATE": bitrate,
            "DEL_WAV_AFTER_CONVERT": 1 if del_src else 0,
        })
        self._save_config()

        def run():
            if not wav_files:
                self._log("[WAV转MP3] 未找到WAV文件", "warn")
                return
            self._log(f"[WAV转MP3] 找到 {len(wav_files)} 个WAV文件", "info")
            success = skip = fail = 0
            for index, wav in enumerate(wav_files, 1):
                mp3 = wav.with_suffix(".mp3")
                self._log(f"[{index}/{len(wav_files)}] 转换: {wav.name}", "info")
                if mp3.exists():
                    self._log("  → 已存在，跳过", "warn")
                    skip += 1
                    continue
                cmd = [str(ffmpeg), "-y", "-i", str(wav), "-codec:a", "libmp3lame",
                       "-b:a", f"{bitrate}k", "-ac", "2", "-ar", "44100", str(mp3)]
                env = os.environ.copy()
                env["PYTHONUTF8"] = "1"
                try:
                    proc = subprocess.run(cmd, cwd=self._tool_dir, env=env, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, timeout=600)
                    if proc.returncode == 0 and mp3.exists():
                        self._log("  → 完成", "success")
                        success += 1
                        if del_src:
                            try:
                                wav.unlink()
                            except Exception:
                                pass
                    else:
                        self._log("  → 失败", "error")
                        fail += 1
                        if mp3.exists():
                            try:
                                mp3.unlink()
                            except Exception:
                                pass
                except Exception as exc:
                    self._log(f"  → 错误: {exc}", "error")
                    fail += 1
            self._log(f"[WAV转MP3] 完成: 成功{success} 跳过{skip} 失败{fail}", "success")
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "total": len(wav_files)}

    # ========== 音频处理辅助方法 ==========

    def _scan_audio_files(self, target_dir, recursive):
        """扫描目录中的音频文件。

        Args:
            target_dir: 目标目录路径。
            recursive: 是否递归扫描子目录。

        Returns:
            list[Path]: 按路径排序的音频文件 Path 对象列表。
        """
        target = Path(target_dir)
        if not target.exists():
            return []
        pattern = "**/*" if recursive else "*"
        return sorted([
            f for f in target.glob(pattern)
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ])

    def _build_audio_codec_args(self, fmt, ext):
        """根据输出格式构建 ffmpeg 编码器参数。

        'same' 或 None 表示从扩展名自动检测编码器。

        Args:
            fmt: 目标音频格式标识符（如 'mp3', 'flac'）或 'same'/None。
            ext: 输出文件扩展名（如 '.mp3', '.wav'），用于自动检测。

        Returns:
            list[str]: 追加到 ffmpeg 命令的编码器参数列表。
        """
        if fmt in (None, 'same', ''):
            ext_clean = ext.lstrip('.').lower()
            cfg = AUDIO_CODEC_CONFIG.get(ext_clean, AUDIO_CODEC_CONFIG['m4a'])
        else:
            cfg = AUDIO_CODEC_CONFIG.get(fmt, AUDIO_CODEC_CONFIG['m4a'])

        args = ['-c:a', cfg['codec']]
        if cfg.get('bitrate'):
            args += ['-b:a', cfg['bitrate']]
        if cfg.get('qscale'):
            args += ['-q:a', cfg['qscale']]
        if cfg.get('compression'):
            args += ['-compression_level', cfg['compression']]
        return args

    def _parse_loudnorm_json(self, stderr_text):
        """从 ffmpeg stderr 中提取并解析 loudnorm 的 JSON 输出。

        Args:
            stderr_text: ffmpeg 的 stderr 文本输出。

        Returns:
            dict | None: 包含 measured_I, measured_LRA, measured_TP, measured_thresh
            的字典，解析失败返回 None。
        """
        # Find the JSON object in stderr — it's the first { ... } block
        # that contains "input_i"
        try:
            # Try to find a JSON object containing input_i
            start = stderr_text.find('{')
            while start != -1:
                # Find matching closing brace
                depth = 0
                end = start
                for i, ch in enumerate(stderr_text[start:], start):
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end > start:
                    candidate = stderr_text[start:end]
                    try:
                        data = json.loads(candidate)
                        if 'input_i' in data:
                            return {
                                'measured_I': data['input_i'],
                                'measured_LRA': data['input_lra'],
                                'measured_TP': data['input_tp'],
                                'measured_thresh': data['input_thresh'],
                            }
                    except json.JSONDecodeError:
                        pass
                start = stderr_text.find('{', start + 1)
        except Exception:
            pass
        return None

    # ========== Audio Loudness Normalization (EBU R128) ==========

    def audio_loudnorm(self, target_dir, recursive, mode, i_target, lra_target,
                       tp_target, output_dir, output_format):
        """音频响度归一化处理（EBU R128 loudnorm 滤镜）。

        支持单次标准处理和双次精准处理两种模式。

        Args:
            target_dir: 包含音频文件的目录路径。
            recursive: 是否递归扫描子目录。
            mode: 处理模式，'single' 为单次标准处理，'double' 为双次精准处理。
            i_target: 目标综合响度，单位 LUFS（默认 -24）。
            lra_target: 目标响度范围，单位 LU（默认 7）。
            tp_target: 目标真峰值上限，单位 dBTP（默认 -2）。
            output_dir: 输出目录路径（留空则在源目录下创建 loudnorm_output/）。
            output_format: 输出音频格式（留空则保持原格式）。

        Returns:
            dict: 包含 ok, total, output_dir 的结果字典。
        """
        ffmpeg = self._tool_dir / f"ffmpeg{self._exe_suffix}"
        if not ffmpeg.exists():
            return {"error": "ffmpeg.exe未找到"}

        target = Path(target_dir)
        if not target.exists():
            return {"error": "目录不存在"}

        audio_files = self._scan_audio_files(target_dir, recursive)
        if not audio_files:
            return {"error": f"目录中未找到支持的音频文件（支持: {', '.join(sorted(AUDIO_EXTENSIONS))}）"}

        # Determine output directory
        out_base = Path(output_dir) if output_dir else (target / "loudnorm_output")
        out_base.mkdir(parents=True, exist_ok=True)

        i_val = float(i_target)
        lra_val = float(lra_target)
        tp_val = float(tp_target)
        fmt = output_format or 'same'

        def run():
            self._log(f"[响度统一] 找到 {len(audio_files)} 个音频文件 (模式: {'双次精准' if mode == 'double' else '单次标准'})", "info")
            success = skip = fail = 0

            for index, src in enumerate(audio_files, 1):
                ext = src.suffix.lower()
                out_ext = ext if fmt == 'same' else f".{fmt}"
                dst = out_base / f"{src.stem}_norm{out_ext}"

                self._log(f"[{index}/{len(audio_files)}] 处理: {src.name}", "info")

                if dst.exists():
                    self._log("  → 已存在，跳过", "warn")
                    skip += 1
                    continue

                codec_args = self._build_audio_codec_args(fmt, ext)

                if mode == 'single':
                    # Single pass: apply loudnorm with specified targets
                    loudnorm_filter = (
                        f"loudnorm=I={i_val}:LRA={lra_val}:TP={tp_val}"
                    )
                    cmd = [str(ffmpeg), '-y', '-i', str(src),
                           '-af', loudnorm_filter] + codec_args + [str(dst)]
                else:
                    # Double pass: analyze first, then apply with measured values
                    # Pass 1 — analyze
                    analyze_filter = (
                        f"loudnorm=I={i_val}:LRA={lra_val}:TP={tp_val}:print_format=json"
                    )
                    cmd_analyze = [str(ffmpeg), '-y', '-i', str(src),
                                   '-af', analyze_filter, '-f', 'null', '-']
                    env = os.environ.copy()
                    env["PYTHONUTF8"] = "1"
                    try:
                        proc = subprocess.run(cmd_analyze, cwd=self._tool_dir, env=env,
                                              capture_output=True, text=True, timeout=300)
                        stderr_output = proc.stderr or ''
                        measured = self._parse_loudnorm_json(stderr_output)
                    except Exception as exc:
                        self._log(f"  → 分析失败: {exc}", "error")
                        fail += 1
                        continue

                    if measured is None:
                        self._log("  → 未能解析响度分析结果，回退为单次处理", "warn")
                        loudnorm_filter = (
                            f"loudnorm=I={i_val}:LRA={lra_val}:TP={tp_val}"
                        )
                    else:
                        loudnorm_filter = (
                            f"loudnorm=I={i_val}:LRA={lra_val}:TP={tp_val}:"
                            f"measured_I={measured['measured_I']}:"
                            f"measured_LRA={measured['measured_LRA']}:"
                            f"measured_TP={measured['measured_TP']}:"
                            f"measured_thresh={measured['measured_thresh']}:"
                            f"linear=true:print_format=summary"
                        )
                        self._log(f"  → 分析完成: I={measured['measured_I']}, "
                                  f"LRA={measured['measured_LRA']}, "
                                  f"TP={measured['measured_TP']}", "info")

                    cmd = [str(ffmpeg), '-y', '-i', str(src),
                           '-af', loudnorm_filter] + codec_args + [str(dst)]

                env = os.environ.copy()
                env["PYTHONUTF8"] = "1"
                try:
                    proc = subprocess.run(cmd, cwd=self._tool_dir, env=env,
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, timeout=600)
                    if proc.returncode == 0 and dst.exists():
                        self._log("  → 完成", "success")
                        success += 1
                    else:
                        self._log("  → 失败", "error")
                        fail += 1
                        if dst.exists():
                            try:
                                dst.unlink()
                            except Exception:
                                pass
                except Exception as exc:
                    self._log(f"  → 错误: {exc}", "error")
                    fail += 1

            self._log(f"[响度统一] 完成: 成功{success} 跳过{skip} 失败{fail}", "success")

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "total": len(audio_files), "output_dir": str(out_base)}

    # ========== Audio Volume Adjustment with Anti-Clipping ==========

    def audio_volume(self, target_dir, recursive, gain_db, limiter_enabled,
                     output_dir, output_format):
        """调整音频音量，可选削波保护限幅器。

        提升音量时使用前瞻限幅器（alimiter）防止削波失真，
        降低音量时无需限幅器。

        Args:
            target_dir: 包含音频文件的目录路径。
            recursive: 是否递归扫描子目录。
            gain_db: 音量增益，单位 dB（正值提升，负值降低）。
            limiter_enabled: 是否启用限幅器防止削波。
            output_dir: 输出目录路径（留空则在源目录下创建 volume_output/）。
            output_format: 输出音频格式（留空则保持原格式）。

        Returns:
            dict: 包含 ok, total, output_dir 的结果字典。
        """
        ffmpeg = self._tool_dir / f"ffmpeg{self._exe_suffix}"
        if not ffmpeg.exists():
            return {"error": "ffmpeg.exe未找到"}

        target = Path(target_dir)
        if not target.exists():
            return {"error": "目录不存在"}

        audio_files = self._scan_audio_files(target_dir, recursive)
        if not audio_files:
            return {"error": f"目录中未找到支持的音频文件（支持: {', '.join(sorted(AUDIO_EXTENSIONS))}）"}

        # Determine output directory
        out_base = Path(output_dir) if output_dir else (target / "volume_output")
        out_base.mkdir(parents=True, exist_ok=True)

        gain = float(gain_db)
        use_limiter = bool(limiter_enabled)
        fmt = output_format or 'same'

        def run():
            self._log(f"[音量调整] 找到 {len(audio_files)} 个音频文件 "
                      f"(增益: {gain:+.1f}dB{', 限幅器: 开启' if use_limiter else ''})", "info")
            success = skip = fail = 0

            for index, src in enumerate(audio_files, 1):
                ext = src.suffix.lower()
                out_ext = ext if fmt == 'same' else f".{fmt}"
                dst = out_base / f"{src.stem}_vol{out_ext}"

                self._log(f"[{index}/{len(audio_files)}] 处理: {src.name}", "info")

                if dst.exists():
                    self._log("  → 已存在，跳过", "warn")
                    skip += 1
                    continue

                # Build audio filter chain
                if gain == 0:
                    # No gain change, skip
                    self._log("  → 增益为0，跳过", "warn")
                    skip += 1
                    continue

                if gain > 0 and use_limiter:
                    # Boost with look-ahead limiter to prevent clipping
                    # alimiter: limit=0.98 (~-0.1dBTP headroom), level=disabled (no input scaling)
                    filter_chain = f"volume={gain}dB,alimiter=limit=0.98:level=disabled:attack=5:release=50"
                elif gain > 0:
                    # Boost without limiter (user explicitly disabled it)
                    self._log("  → 警告: 正增益未开启限幅器，可能存在削波失真", "warn")
                    filter_chain = f"volume={gain}dB"
                else:
                    # Reduce volume: simple and safe, no limiter needed
                    filter_chain = f"volume={gain}dB"

                codec_args = self._build_audio_codec_args(fmt, ext)
                cmd = [str(ffmpeg), '-y', '-i', str(src),
                       '-af', filter_chain] + codec_args + [str(dst)]

                env = os.environ.copy()
                env["PYTHONUTF8"] = "1"
                try:
                    proc = subprocess.run(cmd, cwd=self._tool_dir, env=env,
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, timeout=600)
                    if proc.returncode == 0 and dst.exists():
                        self._log("  → 完成", "success")
                        success += 1
                    else:
                        self._log("  → 失败", "error")
                        fail += 1
                        if dst.exists():
                            try:
                                dst.unlink()
                            except Exception:
                                pass
                except Exception as exc:
                    self._log(f"  → 错误: {exc}", "error")
                    fail += 1

            self._log(f"[音量调整] 完成: 成功{success} 跳过{skip} 失败{fail}", "success")

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "total": len(audio_files), "output_dir": str(out_base)}

    def browse_folder(self):
        folder = ""
        try:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                folder = filedialog.askdirectory(initialdir=str(self._tool_dir))
                root.destroy()
            except Exception:
                ps_cmd = '''
                Add-Type -AssemblyName System.Windows.Forms
                $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
                $dialog.Description = "选择包含WAV文件的文件夹"
                $dialog.ShowNewFolderButton = $true
                if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
                    $dialog.SelectedPath
                }
                '''
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True, text=True, encoding="utf-8", timeout=60
                )
                folder = result.stdout.strip()

            if folder:
                self._log(f"[浏览文件夹] 已选择: {folder}", "info")
                return {"ok": True, "path": folder}
            return {"ok": True, "path": ""}
        except Exception as exc:
            return {"error": f"打开文件夹选择失败: {exc}"}

    def open_folder(self, folder_path):
        try:
            path = Path(folder_path)
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

        content = """# =====================================================
# Netscape HTTP Cookie File
# 请使用浏览器扩展「Get cookies.txt LOCALLY」导出Cookie
# =====================================================
#
# 使用说明：
# 1. 请勿手动编辑此文件内容，格式错误会导致Cookie失效
# 2. 推荐使用浏览器扩展「Get cookies.txt LOCALLY」导出
# 3. 导出时选择对应平台域名，导出后直接替换本文件
# 4. 文件必须保持 Netscape 格式，编码为 UTF-8 无BOM
#
# 安全提示：
# 1. Cookie包含账号登录凭证，请勿分享给他人
# 2. 平台登出、修改密码后Cookie会自动失效
# 3. Fantia仅支持文件模式Cookie，浏览器提取模式无效
# 4. 建议每月重新导出一次，保证凭证有效性
#
# =====================================================

# 下面是示例格式（请替换为实际导出的内容）：
# .youtube.com	TRUE	/	TRUE	1735689600	LOGIN_INFO	xxxxxxxxxxxxxxxxxxxx
# .twitch.tv	TRUE	/	TRUE	1735689600	auth-token	xxxxxxxxxxxxxxxxxxxx
"""
        try:
            cookie_file.write_text(content, encoding="utf-8")
            self._log("[Cookie模板] 已生成 cookies.txt 模板文件", "success")
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
            with open(url_file, "r", encoding="utf-8") as file:
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
            "open-downloads": lambda: self.open_folder(self._tool_dir),
            "open-logs": lambda: self.open_folder(self._log_dir),
        }
        handler = actions.get(action)
        if handler is None:
            return {"error": f"未知工具操作: {action}"}
        return handler()
