import configparser
import json
import os
import tempfile
import threading
from datetime import datetime

from video_downloader.core.constants import DEFAULT_CONFIG, PLATFORM_INFO
from video_downloader.core.paths import AppPaths


class StorageService:
    def __init__(self, tool_dir, app_state, validate_config, log, emit_event):
        self._tool_dir = tool_dir
        self._paths = AppPaths(tool_dir)
        self._config_file = tool_dir / "settings.ini"
        self._preset_file = tool_dir / "presets.json"
        self._history_file = self._paths.download_dir / "download_history.json"
        self._legacy_history_file = tool_dir / "download_history.json"
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        self._app_state = app_state
        self._validate_config = validate_config
        self._log = log
        self._emit_event = emit_event
        # 多锁路径统一先取状态锁、再取对应文件锁，避免反向等待。
        self._config_lock = threading.RLock()
        self._preset_lock = threading.RLock()
        self._history_lock = threading.RLock()

    def load_config(self):
        with self._app_state.config_lock, self._config_lock:
            config = dict(DEFAULT_CONFIG)
            if self._config_file.exists():
                try:
                    # yt-dlp output templates commonly contain ``%(field)s``;
                    # configuration values must be stored literally, without INI interpolation.
                    parser = configparser.ConfigParser(interpolation=None)
                    with open(self._config_file, "r", encoding="utf-8") as file:
                        parser.read_file(file)
                    if parser.has_section("settings"):
                        for key, value in parser["settings"].items():
                            name = key.upper()
                            if name not in DEFAULT_CONFIG:
                                continue
                            default_value = DEFAULT_CONFIG[name]
                            if isinstance(default_value, int):
                                try:
                                    config[name] = int(value)
                                except ValueError:
                                    config[name] = default_value
                            else:
                                config[name] = value
                except Exception as exc:
                    config = dict(DEFAULT_CONFIG)
                    self._log(f"[配置] settings.ini 无法解析，已回退默认设置: {exc}", "warn")
            validated, _ = self._validate_config(config)
            self._app_state.replace_config(validated)
            return self._app_state.config_snapshot()

    def save_config(self):
        with self._app_state.config_lock, self._config_lock:
            snapshot = self._app_state.config_snapshot()
            parser = configparser.ConfigParser(interpolation=None)
            parser["settings"] = {key: str(value) for key, value in snapshot.items()}
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f"{self._config_file.name}.",
                suffix=".tmp",
                dir=self._config_file.parent,
            )
            temp_file = os.fdopen(descriptor, "w", encoding="utf-8")
            try:
                # 先同步同目录临时文件，再原子替换，避免留下半写配置。
                with temp_file as file:
                    parser.write(file)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temp_name, self._config_file)
            except Exception:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
                raise

    def load_presets(self):
        with self._preset_lock:
            if self._preset_file.exists():
                try:
                    with open(self._preset_file, "r", encoding="utf-8") as file:
                        presets = json.load(file)
                    return presets if isinstance(presets, dict) else {}
                except Exception:
                    pass
            return {}

    def _write_presets(self, presets):
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f"{self._preset_file.name}.",
            suffix=".tmp",
            dir=self._preset_file.parent,
        )
        temp_file = os.fdopen(descriptor, "w", encoding="utf-8")
        try:
            # 先同步同目录临时文件，再原子替换，避免留下半写预设。
            with temp_file as file:
                json.dump(presets, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, self._preset_file)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def save_preset(self, name):
        with self._preset_lock:
            presets = self.load_presets()
            presets[name] = self._app_state.config_snapshot()
            try:
                self._write_presets(presets)
                self._log(f"[预设] 已保存: {name}", "success")
                return {"ok": True, "presets": list(presets.keys())}
            except Exception as exc:
                self._log(f"[预设] 保存失败: {exc}", "error")
                return {"error": str(exc)}

    def load_preset(self, name):
        with self._preset_lock:
            presets = self.load_presets()
            if name not in presets:
                return {"error": f"预设不存在: {name}"}
            try:
                with self._app_state.config_lock:
                    previous = self._app_state.config_snapshot()
                    validated, errors = self._validate_config(presets[name], previous)
                    if errors:
                        return {"error": f"预设包含无效设置: {', '.join(errors)}"}
                    self._app_state.replace_config(validated)
                    try:
                        self.save_config()
                    except Exception:
                        self._app_state.replace_config(previous)
                        raise
                self._log(f"[预设] 已加载: {name}", "success")
                return {
                    "ok": True,
                    "config": self._app_state.config_snapshot(),
                    "presets": list(presets.keys()),
                }
            except Exception as exc:
                self._log(f"[预设] 加载失败: {exc}", "error")
                return {"error": str(exc)}

    def delete_preset(self, name):
        with self._preset_lock:
            presets = self.load_presets()
            if name in presets:
                del presets[name]
                try:
                    self._write_presets(presets)
                    self._log(f"[预设] 已删除: {name}", "warn")
                except Exception as exc:
                    return {"error": str(exc)}
            return {"ok": True, "presets": list(presets.keys())}

    def load_history(self):
        with self._history_lock:
            if not self._history_file.exists() and self._legacy_history_file.exists():
                try:
                    self._history_file.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(self._legacy_history_file, self._history_file)
                except OSError:
                    # A read-only legacy installation can still display its history.
                    self._history_file = self._legacy_history_file
            if self._history_file.exists():
                try:
                    with open(self._history_file, "r", encoding="utf-8") as file:
                        history = json.load(file)
                    if not isinstance(history, list):
                        return []
                    if self._migrate_history_paths(history):
                        try:
                            self._write_history(history)
                        except OSError:
                            # Migration persistence is best-effort; history remains usable.
                            pass
                    return history
                except Exception:
                    pass
            return []

    def _migrate_history_paths(self, history):
        """Retarget history entries whose platform folders moved into download/."""
        changed = False
        platform_names = {item["name"] for item in PLATFORM_INFO} | {"Withny"}
        root = os.path.normcase(os.path.abspath(self._tool_dir))
        for entry in history:
            if not isinstance(entry, dict) or not isinstance(entry.get("filepath"), str):
                continue
            filepath = os.path.abspath(entry["filepath"])
            try:
                relative = os.path.relpath(filepath, root)
            except (OSError, ValueError):
                continue
            parts = relative.split(os.sep)
            if relative == os.pardir or relative.startswith(os.pardir + os.sep):
                continue
            if not parts or parts[0] not in platform_names:
                continue
            entry["filepath"] = str(self._paths.download_dir.joinpath(*parts))
            changed = True
        return changed

    def _write_history(self, history):
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f"{self._history_file.name}.",
            suffix=".tmp",
            dir=self._history_file.parent,
        )
        temp_file = os.fdopen(descriptor, "w", encoding="utf-8")
        try:
            with temp_file as file:
                json.dump(history, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, self._history_file)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def add_history(self, url, title, platform, status="success", filepath=None):
        with self._history_lock:
            history = self.load_history()
            entry = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "url": url,
                "title": title or "未知标题",
                "platform": platform,
                "status": status,
            }
            # 记录下载文件的绝对路径，供历史界面按需查找同名封面图。
            if filepath:
                entry["filepath"] = filepath
            history.insert(0, entry)
            history = history[:500]
            try:
                self._write_history(history)
            except Exception:
                pass
            self._emit_event("history", history[:50])
            return history

    def clear_history(self):
        with self._history_lock:
            try:
                self._write_history([])
                self._log("[历史] 已清空下载历史", "warn")
                self._emit_event("history", [])
                return {"ok": True}
            except Exception as exc:
                return {"error": str(exc)}

    # yt-dlp 将封面写在视频同目录、同基名的图片文件（--convert-thumbnails jpg）。
    _COVER_EXTS = ((".jpg", "image/jpeg"), (".jpeg", "image/jpeg"),
                   (".png", "image/png"), (".webp", "image/webp"))

    def find_cover(self, filepath):
        """给定历史记录中的视频路径，返回同基名封面图。

        仅接受工具目录内的路径，防止请求方通过构造路径读取任意文件。

        Args:
            filepath: 视频文件的绝对路径。

        Returns:
            tuple[bytes | None, str | None]: (封面图字节数据, MIME 类型)，
            找不到封面时返回 (None, None)。
        """
        if not filepath or not isinstance(filepath, str):
            return None, None
        base = os.path.splitext(filepath)[0]
        root = os.path.realpath(self._tool_dir)
        for ext, mime in self._COVER_EXTS:
            candidate = os.path.realpath(base + ext)
            if candidate != root and not candidate.startswith(root + os.sep):
                continue
            if not os.path.isfile(candidate):
                continue
            try:
                with open(candidate, "rb") as file:
                    return file.read(), mime
            except OSError:
                continue
        return None, None
