import configparser
import csv
import json
import os
import tempfile
import threading
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from video_downloader.core.constants import DEFAULT_CONFIG, PLATFORM_INFO
from video_downloader.core.paths import AppPaths
from video_downloader.core.platform import clean_url


class StorageService:
    # The password table is a portable plaintext credential store.  Keep this
    # notice inside the workbook so it is visible when the file is opened directly.
    _TC_PASSWORD_WARNING = (
        "警告：本表包含敏感密码信息，除非获得明确授权，请勿发送给其他人。"
    )
    _TC_PASSWORD_FILE_NAME = "twitcasting_passwords.xlsx"
    _TC_PASSWORD_LEGACY_CSV_NAME = "twitcasting_passwords.csv"
    _XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    _XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    _XLSX_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
    _XLSX_XML_NS = "http://www.w3.org/XML/1998/namespace"

    @staticmethod
    def _migrate_task_limits(config):
        config = dict(config)
        for key, low in (("TASK_MAX_PARALLEL", 1), ("TASK_LIVE_PARALLEL", 2)):
            try:
                value = int(config[key])
                if 1 <= value <= 8:
                    config[key] = max(low, min(5, value))
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
        return config

    def __init__(self, tool_dir, app_state, validate_config, log, emit_event):
        self._tool_dir = tool_dir
        self._paths = AppPaths(tool_dir)
        self._config_file = tool_dir / "settings.ini"
        self._preset_file = tool_dir / "presets.json"
        self._history_file = self._paths.download_dir / "download_history.json"
        # Keep the password workbook beside the executable so it is easy to
        # find and remains separate from generated downloads.  Read/migrate
        # the CSV and workbook locations used by older installations.
        self._tc_password_file = tool_dir / self._TC_PASSWORD_FILE_NAME
        self._legacy_tc_password_files = (
            tool_dir / self._TC_PASSWORD_LEGACY_CSV_NAME,
            self._paths.download_dir / self._TC_PASSWORD_LEGACY_CSV_NAME,
            self._paths.download_dir / self._TC_PASSWORD_FILE_NAME,
        )
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
        self._tc_password_lock = threading.RLock()
        self._tc_password_memory = {}

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
                        section = parser["settings"]
                        if "live_mode" not in section and "live_record_mode" in section:
                            migrated, _ = self._validate_config({"LIVE_RECORD_MODE": section["live_record_mode"]})
                            config["LIVE_MODE"] = migrated["LIVE_MODE"]
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
            validated, _ = self._validate_config(self._migrate_task_limits(config))
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
                    validated, errors = self._validate_config(self._migrate_task_limits(presets[name]), previous)
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
            if platform=='Fanbox':
                history=[item for item in history if not (item.get('platform')=='Fanbox' and item.get('url')==url)]
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

    @staticmethod
    def _xlsx_column_index(cell_ref):
        letters = "".join(char for char in str(cell_ref) if char.isalpha())
        value = 0
        for char in letters.upper():
            value = value * 26 + ord(char) - ord("A") + 1
        return value - 1

    @classmethod
    def _xlsx_inline_text(cls, cell, shared_strings):
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            text_node = cell.find(f".//{{{cls._XLSX_NS}}}t")
            return text_node.text if text_node is not None and text_node.text is not None else ""
        value_node = cell.find(f"{{{cls._XLSX_NS}}}v")
        value = value_node.text if value_node is not None and value_node.text is not None else ""
        if cell_type == "s":
            try:
                return shared_strings[int(value)]
            except (ValueError, IndexError):
                return ""
        return value

    @staticmethod
    def _xlsx_serial_to_time(value):
        try:
            serial = float(value)
        except (TypeError, ValueError):
            return str(value or "")
        moment = datetime(1899, 12, 30) + timedelta(seconds=round(serial * 86400))
        return moment.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _time_to_xlsx_serial(value):
        if not value:
            return None
        if isinstance(value, datetime):
            moment = value
        else:
            text = str(value).strip()
            moment = None
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M",
            ):
                try:
                    moment = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if moment is None:
                return None
        return (moment - datetime(1899, 12, 30)).total_seconds() / 86400

    @classmethod
    def _read_tc_password_xlsx(cls, password_file):
        rows = {}
        warning_present = False
        header_row = None
        duplicate_header = False
        warning_merge = None
        widths = {}
        has_table = False
        frozen_header = False
        with zipfile.ZipFile(password_file, "r") as archive:
            sheet_names = sorted(
                name for name in archive.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            )
            if not sheet_names:
                raise ValueError("工作簿缺少工作表")
            sheet_root = ET.fromstring(archive.read(sheet_names[0]))
            has_table = sheet_root.find(f"{{{cls._XLSX_NS}}}tableParts") is not None
            shared_strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                for string_item in shared_root.findall(f"{{{cls._XLSX_NS}}}si"):
                    shared_strings.append("".join(
                        node.text or "" for node in string_item.iter(f"{{{cls._XLSX_NS}}}t")
                    ))

            columns = sheet_root.find(f"{{{cls._XLSX_NS}}}cols")
            if columns is not None:
                for column in columns.findall(f"{{{cls._XLSX_NS}}}col"):
                    try:
                        first = int(column.attrib.get("min", "0"))
                        last = int(column.attrib.get("max", first))
                        width = float(column.attrib.get("width", "0"))
                    except ValueError:
                        continue
                    for index in range(first, last + 1):
                        widths[index] = width
            sheet_views = sheet_root.find(f"{{{cls._XLSX_NS}}}sheetViews")
            if sheet_views is not None:
                sheet_view = sheet_views.find(f"{{{cls._XLSX_NS}}}sheetView")
                if sheet_view is not None:
                    frozen_header = sheet_view.find(f"{{{cls._XLSX_NS}}}pane") is not None
            has_filter = sheet_root.find(f"{{{cls._XLSX_NS}}}autoFilter") is not None
            merges = sheet_root.find(f"{{{cls._XLSX_NS}}}mergeCells")
            if merges is not None:
                merge_refs = [item.attrib.get("ref") for item in merges]
                warning_merge = next((ref for ref in merge_refs if ref), None)

            sheet_data = sheet_root.find(f"{{{cls._XLSX_NS}}}sheetData")
            if sheet_data is None:
                raise ValueError("工作簿缺少数据区域")
            for row_node in sheet_data.findall(f"{{{cls._XLSX_NS}}}row"):
                try:
                    row_number = int(row_node.attrib.get("r", "0"))
                except ValueError:
                    continue
                values = {}
                for cell in row_node.findall(f"{{{cls._XLSX_NS}}}c"):
                    values[cls._xlsx_column_index(cell.attrib.get("r", ""))] = cls._xlsx_inline_text(
                        cell, shared_strings
                    )
                raw_url = str(values.get(0, "") or "").strip()
                if raw_url == cls._TC_PASSWORD_WARNING:
                    warning_present = True
                    continue
                if raw_url in {"链接", "url"} and str(values.get(1, "") or "").strip() in {"密码", "password"}:
                    if header_row is None:
                        header_row = row_number
                    else:
                        duplicate_header = True
                    continue
                url = clean_url(raw_url)
                password = str(values.get(1, "") or "")
                recorded_at = values.get(2, "")
                if row_number > (header_row or 0) and isinstance(recorded_at, str):
                    recorded_at = cls._xlsx_serial_to_time(recorded_at) if recorded_at.replace(".", "", 1).isdigit() else recorded_at
                if url and password:
                    rows[url] = {
                        "url": url,
                        "password": password,
                        "time": recorded_at,
                    }

        normalized = (
            warning_present
            and header_row == 2
            and not duplicate_header
            and warning_merge in {"A1:C1", "A1:C2"}
            and abs(widths.get(1, 0) - 60) < 0.01
            and abs(widths.get(2, 0) - 15) < 0.01
            and abs(widths.get(3, 0) - 20) < 0.01
            and frozen_header
            and has_filter
            and has_table
        )
        return rows, normalized

    def _read_tc_password_csv(self, password_file):
        rows = {}
        warning_present = False
        read_encoding = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp932"):
            try:
                with password_file.open("r", encoding=encoding, newline="") as file:
                    for row in csv.DictReader(file):
                        raw_url = str(row.get("链接", row.get("url", "")) or "").strip()
                        if raw_url == self._TC_PASSWORD_WARNING:
                            warning_present = True
                            continue
                        url = clean_url(raw_url)
                        password = row.get("密码", row.get("password", ""))
                        recorded_at = row.get("时间", row.get("time", ""))
                        if url and password:
                            rows[url] = {
                                "url": url,
                                "password": password,
                                "time": recorded_at,
                            }
                read_encoding = encoding
                break
            except UnicodeError:
                continue
            except (OSError, csv.Error):
                break
        if read_encoding is None:
            raise ValueError("CSV 密码表无法读取")
        return rows, warning_present, read_encoding

    def _locate_tc_password_source(self):
        if self._tc_password_file.exists():
            return self._tc_password_file
        for candidate in self._legacy_tc_password_files:
            if not candidate.exists():
                continue
            if candidate.suffix.lower() == ".xlsx":
                try:
                    self._tc_password_file.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(candidate, self._tc_password_file)
                    return self._tc_password_file
                except OSError:
                    pass
            return candidate
        return self._tc_password_file

    def _load_tc_password_rows(self):
        """读取本机 TwitCasting 密码表，并兼容旧 CSV/旧工作簿。"""
        password_file = self._locate_tc_password_source()
        if not password_file.exists():
            return {}
        try:
            if password_file.suffix.lower() == ".xlsx":
                rows, normalized = self._read_tc_password_xlsx(password_file)
                if password_file != self._tc_password_file or not normalized:
                    self._write_tc_password_rows(rows)
                    if password_file != self._tc_password_file:
                        try:
                            password_file.unlink()
                        except OSError:
                            pass
            else:
                rows, warning_present, read_encoding = self._read_tc_password_csv(password_file)
                if not warning_present or read_encoding != "utf-8-sig" or password_file != self._tc_password_file:
                    self._write_tc_password_rows(rows)
                    if password_file != self._tc_password_file:
                        try:
                            password_file.unlink()
                        except OSError:
                            pass
            return rows
        except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile, csv.Error):
            self._log("[TwitCasting] 密码表无法读取，已忽略旧记录", "warn")
            return {}

    @classmethod
    def _xlsx_inline_cell(cls, parent, reference, value, style=None):
        attributes = {"r": reference, "t": "inlineStr"}
        if style is not None:
            attributes["s"] = str(style)
        cell = ET.SubElement(parent, f"{{{cls._XLSX_NS}}}c", attributes)
        inline = ET.SubElement(cell, f"{{{cls._XLSX_NS}}}is")
        text_node = ET.SubElement(inline, f"{{{cls._XLSX_NS}}}t")
        if value and (value[0].isspace() or value[-1].isspace()):
            text_node.set(f"{{{cls._XLSX_XML_NS}}}space", "preserve")
        text_node.text = str(value or "")
        return cell

    @classmethod
    def _xlsx_number_cell(cls, parent, reference, value, style):
        cell = ET.SubElement(parent, f"{{{cls._XLSX_NS}}}c", {"r": reference, "s": str(style)})
        value_node = ET.SubElement(cell, f"{{{cls._XLSX_NS}}}v")
        value_node.text = f"{float(value):.10f}".rstrip("0").rstrip(".")
        return cell

    @classmethod
    def _xlsx_xml(cls, root):
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    @classmethod
    def _xlsx_table_xml(cls, last_row):
        table_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        table = ET.Element(f"{{{table_ns}}}table", {
            "id": "1",
            "name": "TwitCastingPasswords",
            "displayName": "TwitCastingPasswords",
            "ref": f"A2:C{last_row}",
            "headerRowCount": "1",
            "totalsRowShown": "0",
        })
        ET.SubElement(table, f"{{{table_ns}}}autoFilter", {"ref": f"A2:C{last_row}"})
        columns = ET.SubElement(table, f"{{{table_ns}}}tableColumns", {"count": "3"})
        for index, name in enumerate(("链接", "密码", "时间"), start=1):
            ET.SubElement(columns, f"{{{table_ns}}}tableColumn", {"id": str(index), "name": name})
        ET.SubElement(table, f"{{{table_ns}}}tableStyleInfo", {
            "name": "TableStyleMedium2",
            "showFirstColumn": "0",
            "showLastColumn": "0",
            "showRowStripes": "1",
            "showColumnStripes": "0",
        })
        return cls._xlsx_xml(table)

    @classmethod
    def _xlsx_sheet_relationships(cls):
        relationships = ET.Element(f"{{{cls._XLSX_PACKAGE_REL_NS}}}Relationships")
        ET.SubElement(relationships, f"{{{cls._XLSX_PACKAGE_REL_NS}}}Relationship", {
            "Id": "rId2",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/table",
            "Target": "../tables/table1.xml",
        })
        return relationships

    @classmethod
    def _password_workbook_parts(cls, rows):
        ET.register_namespace("", cls._XLSX_NS)
        ET.register_namespace("r", cls._XLSX_REL_NS)
        ET.register_namespace("x", cls._XLSX_PACKAGE_REL_NS)
        last_row = 2 + len(rows)
        table_last_row = max(102, last_row)

        content_types = ET.Element("{http://schemas.openxmlformats.org/package/2006/content-types}Types")
        ET.register_namespace("", "http://schemas.openxmlformats.org/package/2006/content-types")
        for extension, content_type in (
            ("rels", "application/vnd.openxmlformats-package.relationships+xml"),
            ("xml", "application/xml"),
        ):
            ET.SubElement(content_types, "{http://schemas.openxmlformats.org/package/2006/content-types}Default", {
                "Extension": extension, "ContentType": content_type,
            })
        for part_name, content_type in (
            ("/xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
            ("/xl/worksheets/sheet1.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
            ("/xl/styles.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"),
            ("/xl/tables/table1.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"),
        ):
            ET.SubElement(content_types, "{http://schemas.openxmlformats.org/package/2006/content-types}Override", {
                "PartName": part_name, "ContentType": content_type,
            })

        package_rels = ET.Element(f"{{{cls._XLSX_PACKAGE_REL_NS}}}Relationships")
        ET.SubElement(package_rels, f"{{{cls._XLSX_PACKAGE_REL_NS}}}Relationship", {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
            "Target": "xl/workbook.xml",
        })

        workbook = ET.Element(f"{{{cls._XLSX_NS}}}workbook", {f"{{{cls._XLSX_REL_NS}}}id": "rId1"})
        sheets = ET.SubElement(workbook, f"{{{cls._XLSX_NS}}}sheets")
        ET.SubElement(sheets, f"{{{cls._XLSX_NS}}}sheet", {
            "name": "twitcasting_passwords", "sheetId": "1", f"{{{cls._XLSX_REL_NS}}}id": "rId1",
        })
        workbook_rels = ET.Element(f"{{{cls._XLSX_PACKAGE_REL_NS}}}Relationships")
        for rel_id, rel_type, target in (
            ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet", "worksheets/sheet1.xml"),
            ("rId2", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "styles.xml"),
        ):
            ET.SubElement(workbook_rels, f"{{{cls._XLSX_PACKAGE_REL_NS}}}Relationship", {
                "Id": rel_id, "Type": rel_type, "Target": target,
            })

        sheet = ET.Element(f"{{{cls._XLSX_NS}}}worksheet")
        ET.SubElement(sheet, f"{{{cls._XLSX_NS}}}dimension", {"ref": f"A1:C{table_last_row}"})
        views = ET.SubElement(sheet, f"{{{cls._XLSX_NS}}}sheetViews")
        view = ET.SubElement(views, f"{{{cls._XLSX_NS}}}sheetView", {"showGridLines": "0", "workbookViewId": "0"})
        ET.SubElement(view, f"{{{cls._XLSX_NS}}}pane", {"ySplit": "2", "topLeftCell": "A3", "activePane": "bottomLeft", "state": "frozen"})
        ET.SubElement(view, f"{{{cls._XLSX_NS}}}selection", {"pane": "bottomLeft", "activeCell": "A3", "sqref": "A3"})
        ET.SubElement(sheet, f"{{{cls._XLSX_NS}}}sheetFormatPr", {"defaultRowHeight": "18"})
        cols = ET.SubElement(sheet, f"{{{cls._XLSX_NS}}}cols")
        for index, width in ((1, "60"), (2, "15"), (3, "20")):
            ET.SubElement(cols, f"{{{cls._XLSX_NS}}}col", {"min": str(index), "max": str(index), "width": width, "customWidth": "1"})
        sheet_data = ET.SubElement(sheet, f"{{{cls._XLSX_NS}}}sheetData")
        row = ET.SubElement(sheet_data, f"{{{cls._XLSX_NS}}}row", {"r": "1", "ht": "30", "customHeight": "1"})
        cls._xlsx_inline_cell(row, "A1", cls._TC_PASSWORD_WARNING, 1)
        row = ET.SubElement(sheet_data, f"{{{cls._XLSX_NS}}}row", {"r": "2", "ht": "22", "customHeight": "1"})
        for column, value in (("A", "链接"), ("B", "密码"), ("C", "时间")):
            cls._xlsx_inline_cell(row, f"{column}2", value, 2)
        for offset, item in enumerate(rows, start=3):
            row = ET.SubElement(sheet_data, f"{{{cls._XLSX_NS}}}row", {"r": str(offset), "ht": "20", "customHeight": "1"})
            stripe_style = 5 if (offset - 3) % 2 == 0 else 3
            date_style = 6 if (offset - 3) % 2 == 0 else 4
            cls._xlsx_inline_cell(row, f"A{offset}", item["url"], stripe_style)
            cls._xlsx_inline_cell(row, f"B{offset}", item["password"], stripe_style)
            serial = cls._time_to_xlsx_serial(item.get("time"))
            if serial is None:
                cls._xlsx_inline_cell(row, f"C{offset}", item.get("time", ""), stripe_style)
            else:
                cls._xlsx_number_cell(row, f"C{offset}", serial, date_style)
        for offset in range(3 + len(rows), table_last_row + 1):
            row = ET.SubElement(sheet_data, f"{{{cls._XLSX_NS}}}row", {"r": str(offset), "ht": "20", "customHeight": "1"})
            stripe_style = 5 if (offset - 3) % 2 == 0 else 3
            for column in ("A", "B", "C"):
                cls._xlsx_inline_cell(row, f"{column}{offset}", "", stripe_style)
        ET.SubElement(sheet, f"{{{cls._XLSX_NS}}}autoFilter", {"ref": f"A2:C{table_last_row}"})
        merges = ET.SubElement(sheet, f"{{{cls._XLSX_NS}}}mergeCells", {"count": "1"})
        ET.SubElement(merges, f"{{{cls._XLSX_NS}}}mergeCell", {"ref": "A1:C1"})
        table_parts = ET.SubElement(sheet, f"{{{cls._XLSX_NS}}}tableParts", {"count": "1"})
        ET.SubElement(table_parts, f"{{{cls._XLSX_NS}}}tablePart", {f"{{{cls._XLSX_REL_NS}}}id": "rId2"})
        ET.SubElement(sheet, f"{{{cls._XLSX_NS}}}pageMargins", {"left": "0.7", "right": "0.7", "top": "0.75", "bottom": "0.75", "header": "0.3", "footer": "0.3"})

        styles = ET.Element(f"{{{cls._XLSX_NS}}}styleSheet")
        num_fmts = ET.SubElement(styles, f"{{{cls._XLSX_NS}}}numFmts", {"count": "1"})
        ET.SubElement(num_fmts, f"{{{cls._XLSX_NS}}}numFmt", {"numFmtId": "164", "formatCode": "yyyy/mm/dd hh:mm:ss"})
        fonts = ET.SubElement(styles, f"{{{cls._XLSX_NS}}}fonts", {"count": "4"})
        for bold, color, name, size in (
            (False, "FF222222", "Microsoft YaHei", "11"),
            (True, "FF7F6000", "Microsoft YaHei", "11"),
            (True, "FFFFFFFF", "Microsoft YaHei", "11"),
            (False, "FF222222", "Consolas", "10"),
        ):
            font = ET.SubElement(fonts, f"{{{cls._XLSX_NS}}}font")
            if bold:
                ET.SubElement(font, f"{{{cls._XLSX_NS}}}b")
            ET.SubElement(font, f"{{{cls._XLSX_NS}}}sz", {"val": size})
            ET.SubElement(font, f"{{{cls._XLSX_NS}}}color", {"rgb": color})
            ET.SubElement(font, f"{{{cls._XLSX_NS}}}name", {"val": name})
        fills = ET.SubElement(styles, f"{{{cls._XLSX_NS}}}fills", {"count": "5"})
        ET.SubElement(fills, f"{{{cls._XLSX_NS}}}fill").append(ET.Element(f"{{{cls._XLSX_NS}}}patternFill", {"patternType": "none"}))
        ET.SubElement(fills, f"{{{cls._XLSX_NS}}}fill").append(ET.Element(f"{{{cls._XLSX_NS}}}patternFill", {"patternType": "gray125"}))
        for color in ("FFFFF2CC", "FF1F4E78"):
            fill = ET.SubElement(fills, f"{{{cls._XLSX_NS}}}fill")
            pattern = ET.SubElement(fill, f"{{{cls._XLSX_NS}}}patternFill", {"patternType": "solid"})
            ET.SubElement(pattern, f"{{{cls._XLSX_NS}}}fgColor", {"rgb": color})
            ET.SubElement(pattern, f"{{{cls._XLSX_NS}}}bgColor", {"indexed": "64"})
        fill = ET.SubElement(fills, f"{{{cls._XLSX_NS}}}fill")
        pattern = ET.SubElement(fill, f"{{{cls._XLSX_NS}}}patternFill", {"patternType": "solid"})
        ET.SubElement(pattern, f"{{{cls._XLSX_NS}}}fgColor", {"rgb": "FFDDEBF7"})
        ET.SubElement(pattern, f"{{{cls._XLSX_NS}}}bgColor", {"indexed": "64"})
        borders = ET.SubElement(styles, f"{{{cls._XLSX_NS}}}borders", {"count": "2"})
        ET.SubElement(borders, f"{{{cls._XLSX_NS}}}border").extend([
            ET.Element(f"{{{cls._XLSX_NS}}}left"), ET.Element(f"{{{cls._XLSX_NS}}}right"),
            ET.Element(f"{{{cls._XLSX_NS}}}top"), ET.Element(f"{{{cls._XLSX_NS}}}bottom"),
            ET.Element(f"{{{cls._XLSX_NS}}}diagonal"),
        ])
        border = ET.SubElement(borders, f"{{{cls._XLSX_NS}}}border")
        for edge in ("left", "right", "top", "bottom"):
            vertical = edge in {"left", "right"}
            edge_node = ET.SubElement(border, f"{{{cls._XLSX_NS}}}{edge}", {
                "style": "medium" if vertical else "thin",
            })
            ET.SubElement(edge_node, f"{{{cls._XLSX_NS}}}color", {
                "rgb": "FF8FA7B5" if vertical else "FFD9E2F3",
            })
        ET.SubElement(border, f"{{{cls._XLSX_NS}}}diagonal")
        cell_xfs = ET.SubElement(styles, f"{{{cls._XLSX_NS}}}cellXfs", {"count": "7"})
        for font_id, fill_id, border_id, number_format, horizontal, wrap in (
            (0, 0, 0, None, None, None),
            (1, 2, 0, None, "left", "1"),
            (2, 3, 1, None, "center", None),
            (3, 0, 1, None, "left", None),
            (3, 0, 1, "164", "left", None),
            (3, 4, 1, None, "left", None),
            (3, 4, 1, "164", "left", None),
        ):
            xf_attrs = {"numFmtId": number_format or "0", "fontId": str(font_id), "fillId": str(fill_id), "borderId": str(border_id), "xfId": "0"}
            if number_format:
                xf_attrs["applyNumberFormat"] = "1"
            xf = ET.SubElement(cell_xfs, f"{{{cls._XLSX_NS}}}xf", xf_attrs)
            alignment = {"vertical": "center"}
            if horizontal:
                alignment["horizontal"] = horizontal
            if wrap:
                alignment["wrapText"] = wrap
            ET.SubElement(xf, f"{{{cls._XLSX_NS}}}alignment", alignment)

        return {
            "[Content_Types].xml": cls._xlsx_xml(content_types),
            "_rels/.rels": cls._xlsx_xml(package_rels),
            "xl/workbook.xml": cls._xlsx_xml(workbook),
            "xl/_rels/workbook.xml.rels": cls._xlsx_xml(workbook_rels),
            "xl/worksheets/sheet1.xml": cls._xlsx_xml(sheet),
            "xl/worksheets/_rels/sheet1.xml.rels": cls._xlsx_xml(
                cls._xlsx_sheet_relationships()
            ),
            "xl/tables/table1.xml": cls._xlsx_table_xml(table_last_row),
            "xl/styles.xml": cls._xlsx_xml(styles),
        }

    def _write_tc_password_rows(self, rows):
        self._tc_password_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f"{self._tc_password_file.name}.",
            suffix=".tmp",
            dir=self._tc_password_file.parent,
        )
        os.close(descriptor)
        try:
            parts = self._password_workbook_parts(list(rows.values()))
            with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, content in parts.items():
                    archive.writestr(name, content)
            os.replace(temp_name, self._tc_password_file)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def get_twitcasting_password(self, url, *, persist=True):
        """按链接读取已验证的 TwitCasting 密码。"""
        key = clean_url(url)
        if not key:
            return None
        with self._tc_password_lock:
            if key in self._tc_password_memory:
                return self._tc_password_memory[key]
            if not persist:
                return None
            row = self._load_tc_password_rows().get(key)
            if row:
                self._tc_password_memory[key] = row["password"]
            return row["password"] if row else None

    def save_twitcasting_password(self, url, password, *, persist=True):
        """保存已验证密码及时间；同一链接只保留最新一条。"""
        key = clean_url(url)
        password = str(password or "")
        if not key or not password:
            return {"error": "TwitCasting 链接或密码为空"}
        with self._tc_password_lock:
            self._tc_password_memory[key] = password
            if not persist:
                return {"ok": True}
            rows = self._load_tc_password_rows()
            rows[key] = {
                "url": key,
                "password": password,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            try:
                self._write_tc_password_rows(rows)
                return {"ok": True}
            except OSError as exc:
                self._log(f"[TwitCasting] 密码保存失败: {exc}", "warn")
                return {"error": str(exc)}

    def forget_twitcasting_password(self, url, *, persist=True):
        """删除链接对应的失效密码。"""
        key = clean_url(url)
        if not key:
            return {"ok": True}
        with self._tc_password_lock:
            self._tc_password_memory.pop(key, None)
            if not persist:
                return {"ok": True}
            rows = self._load_tc_password_rows()
            if key not in rows:
                return {"ok": True}
            del rows[key]
            try:
                self._write_tc_password_rows(rows)
                return {"ok": True}
            except OSError as exc:
                self._log(f"[TwitCasting] 失效密码清理失败: {exc}", "warn")
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
