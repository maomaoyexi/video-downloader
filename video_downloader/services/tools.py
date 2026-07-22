import os
import subprocess
import threading
from pathlib import Path


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
        return deps

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
