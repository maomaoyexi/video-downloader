import configparser
import json
import os
import tempfile
import threading
from datetime import datetime

from .constants import DEFAULT_CONFIG


class StorageService:
    def __init__(self, tool_dir, app_state, validate_config, log, emit_event):
        self._config_file = tool_dir / "settings.ini"
        self._preset_file = tool_dir / "presets.json"
        self._history_file = tool_dir / "download_history.json"
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
                    parser = configparser.ConfigParser()
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
            parser = configparser.ConfigParser()
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
            if self._history_file.exists():
                try:
                    with open(self._history_file, "r", encoding="utf-8") as file:
                        history = json.load(file)
                    return history if isinstance(history, list) else []
                except Exception:
                    pass
            return []

    def add_history(self, url, title, platform, status="success"):
        with self._history_lock:
            history = self.load_history()
            history.insert(0, {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "url": url,
                "title": title or "未知标题",
                "platform": platform,
                "status": status,
            })
            history = history[:500]
            try:
                with open(self._history_file, "w", encoding="utf-8") as file:
                    json.dump(history, file, ensure_ascii=False, indent=2)
            except Exception:
                pass
            self._emit_event("history", history[:50])
            return history

    def clear_history(self):
        with self._history_lock:
            try:
                with open(self._history_file, "w", encoding="utf-8") as file:
                    json.dump([], file)
                self._log("[历史] 已清空下载历史", "warn")
                self._emit_event("history", [])
                return {"ok": True}
            except Exception as exc:
                return {"error": str(exc)}
