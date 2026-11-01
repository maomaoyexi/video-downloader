"""P1 scan command: metadata/content manifest only, no attachment downloads."""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
from pathlib import Path
import threading

from .auth import load_credentials
from .client import FanboxClient
from .errors import FanboxError
from .options import normalize_options
from .service import ScanService, write_json
from .transport import CurlTransport, HttpTransport, RequestGate


def read_config(root):
    from video_downloader.core.validation import validate_config
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(Path(root) / "settings.ini", encoding="utf-8")
        raw = {key.upper(): value for key, value in parser["settings"].items()} if parser.has_section("settings") else {}
        config, errors = validate_config(raw)
    except (OSError, ValueError, configparser.Error):
        raise FanboxError("invalid_config", "无法读取工具配置") from None
    if errors:
        raise FanboxError("invalid_config", "工具配置校验失败")
    return config


def proxy_from_config(config, options):
    if options["network"]["proxy_policy"] == "direct" or not int(config.get("PROXY_ENABLED", 0)):
        return None
    return f"{config['PROXY_TYPE']}://{config['PROXY_ADDR']}:{config['PROXY_PORT']}"


def credential_scope(credentials):
    sessions = sorted((c.domain, c.path, c.name, c.value) for c in credentials.jar if c.name == "FANBOXSESSID")
    if not sessions:
        return "anonymous"
    # Not an authentication token; binds a private checkpoint to this login snapshot.
    return hashlib.sha256(("fanbox-checkpoint-v1:" + json.dumps(sessions)).encode()).hexdigest()


def main(argv=None, *, root=None):
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="FANBOX 帖子抓取清单（不下载附件）")
    parser.add_argument("url")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cookies", type=Path)
    parser.add_argument("--anonymous", action="store_true")
    parser.add_argument("--max-posts", type=int)
    parser.add_argument("--comments", action="store_true", default=None)
    parser.add_argument("--options", type=Path)
    parser.add_argument("--import-plugin-settings", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    root = Path(root or Path(__file__).resolve().parents[3])
    cancel = threading.Event()
    try:
        config = read_config(root)
        options = normalize_options(config.get("FANBOX_OPTIONS", "{}"))
        migration_report = None
        if args.options:
            options = normalize_options(_read_json(args.options, 65536))
        if args.import_plugin_settings:
            from .options import import_plugin_settings
            options, migration_report = import_plugin_settings(_read_json(args.import_plugin_settings, 65536))
        if args.max_posts is not None: options["filters"]["max_posts"] = args.max_posts
        if args.comments is not None: options["content"]["comments"] = args.comments
        options = normalize_options(options)
        cookie_file = args.cookies if args.cookies else root / "cookies.txt"
        if args.anonymous and args.cookies:
            raise FanboxError("invalid_config", "匿名模式不能同时指定 Cookie")
        use_cookies = not args.anonymous and (args.cookies is not None or
            (int(config.get("USE_COOKIES", 1)) and cookie_file.exists()))
        credentials = load_credentials(cookie_file if use_cookies else None)
        checkpoint_path = args.checkpoint or args.output.with_suffix(args.output.suffix + ".checkpoint.json")
        if (args.output.resolve() == checkpoint_path.resolve()
                or (not args.anonymous and cookie_file.resolve() in {args.output.resolve(), checkpoint_path.resolve()})):
            raise FanboxError("invalid_config", "输出、检查点与凭据文件必须使用不同路径")
        checkpoint = _read_json(checkpoint_path, 64 * 1024 * 1024) if args.resume else None
        engine = CurlTransport if options["network"]["engine"] == "curl" else HttpTransport
        with engine(credentials, proxy=proxy_from_config(config, options),
                    gate=RequestGate(options["network"]["api_interval_seconds"], cancel)) as transport:
            service = ScanService(FanboxClient(transport))
            result = service.scan(args.url, options, checkpoint=checkpoint,
                auth_scope=credential_scope(credentials), save_checkpoint=lambda value: write_json(checkpoint_path, value))
        manifest = dict(result)
        manifest.pop("checkpoint")
        if migration_report is not None:
            manifest["settings_migration"] = migration_report
        write_json(args.output, manifest)
        print(json.dumps({"status":result["status"], "counts":result["counts"],
                          "coverage":result["coverage"], "errors":result["errors"]}, ensure_ascii=False))
        return 0 if result["status"] == "completed" else 2
    except (FanboxError, OSError) as error:
        safe = error.to_dict() if isinstance(error, FanboxError) else {"code":"file_error","message":"无法读取或保存本地文件"}
        print(json.dumps({"status":"failed", "error":safe}, ensure_ascii=False))
        return 2
    except KeyboardInterrupt:
        cancel.set()
        print(json.dumps({"status":"interrupted"}))
        return 130


def _read_json(path, limit):
    if path.stat().st_size > limit:
        raise FanboxError("file_too_large", "输入 JSON 超过大小限制")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        raise FanboxError("invalid_json", "输入不是有效 JSON") from None
