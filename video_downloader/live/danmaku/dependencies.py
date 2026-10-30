"""Source portable installs and frozen builds use the same pinned libraries."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


class MissingDependency(RuntimeError):
    pass


def library(name):
    if not getattr(sys, "frozen", False):
        vendor = Path(__file__).resolve().parents[3] / "dependency" / "live-python"
        if vendor.is_dir() and str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise MissingDependency("直播弹幕依赖缺失，请运行 python scripts/install_live_dependencies.py") from exc


def health():
    groups = {"live_comment_export": ("pysubs2", "defusedxml.ElementTree"),
              "live_comment_transport": ("websocket", "python_socks", "httpx", "h2", "socksio", "ruamel.yaml"),
              "live_comment_niconico": ("ndgr_client.proto.dwango.nicolive.chat.service.edge.payload_pb2",)}
    result = {}
    for key, names in groups.items():
        try:
            for name in names:
                library(name)
            result[key] = True
        except (RuntimeError, ImportError, ValueError):
            result[key] = False
    return result


def self_check():
    """Source/frozen release smoke: exercise native protocol and serializer APIs."""
    result = health()
    if not all(result.values()):
        return result
    proto = library("ndgr_client.proto.dwango.nicolive.chat.service.edge.payload_pb2")
    message = proto.ChunkedMessage()
    message.meta.id = "release-check"
    message.message.chat.content = "发布检查"
    restored = proto.ChunkedMessage.FromString(message.SerializeToString())
    subs = library("pysubs2")
    subtitles = subs.SSAFile()
    subtitles.append(subs.SSAEvent(start=0, end=1000, text=restored.message.chat.content))
    result["subtitle_roundtrip"] = all(subs.SSAFile.from_string(subtitles.to_string(fmt), fmt)[0].text == "发布检查"
                                       for fmt in ("srt", "ass"))
    yaml = library("ruamel.yaml").YAML(typ="safe", pure=True)
    result["managed_yaml"] = yaml.load("writeChat: true")["writeChat"] is True
    result["tls_certificates"] = Path(library("certifi").where()).is_file()
    from video_downloader.platforms.rplay import auth_support
    support = auth_support()
    result['rplay_session_decoder'] = support.decompress_session(b'\x03\x08xyz') == b'xyz'
    import os
    if os.name == 'nt':
        plain = b'rplay-release-self-check'
        encrypted = support.protect(plain)
        result['rplay_credential_protection'] = plain not in encrypted and support.protect(encrypted, decrypt=True) == plain
    return result
