"""Small source adapters; common lifecycle/retry/storage lives in the worker."""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from .. import process
from ..catchup import context_arguments
from ..urls import classify_target
from ..session import public_url
from .dependencies import library
from .transport import remote_url, option
from .twitch import parse_line
from .youtube import messages


def twitch(context, transport, stop, emit, stats):
    room = urlsplit(context["url"]).path.strip("/").split("/")[0].lower()
    if not re.fullmatch(r"[a-z0-9_]{1,40}", room):
        raise ValueError("invalid_twitch_channel")
    ws = transport.socket("wss://irc-ws.chat.twitch.tv:443", origin="https://www.twitch.tv")
    try:
        for line in ("PASS SCHMOOPIIE", "NICK justinfan" + str(secrets.randbelow(900000) + 100000),
                     "CAP REQ :twitch.tv/tags twitch.tv/commands", "JOIN #" + room):
            ws.send(line + "\r\n")
        pending = ""
        while not stop.is_set():
            try:
                frame = ws.recv()
            except library("websocket").WebSocketTimeoutException:
                continue
            if not frame:
                raise ConnectionError("irc_disconnected")
            pending += frame.decode("utf-8", "replace") if isinstance(frame, bytes) else frame
            if len(pending) > 1024 * 1024:
                raise ValueError("oversized_irc_frame")
            while "\r\n" in pending:
                line, pending = pending.split("\r\n", 1)
                if line.startswith("PING "):
                    ws.send("PONG " + line[5:] + "\r\n")
                elif " RECONNECT" in line:
                    raise ConnectionError("irc_reconnect")
                elif "Login authentication failed" in line:
                    raise PermissionError("irc_auth_required")
                else:
                    try:
                        event = parse_line(line, room, time.time())
                        if event:
                            emit(event)
                    except (ValueError, TypeError):
                        stats["rejected_count"] += 1
    finally:
        ws.close()


def youtube(context, transport, stop, emit, stats):
    root = Path(context["root"]) / ".source"
    root.mkdir(exist_ok=True)
    command = [context["command"][0], "--ignore-config", *context_arguments(context["command"]),
               "--skip-download", "--no-simulate", "--write-subs", "--sub-langs", "live_chat",
               "--sub-format", "json", "--no-write-auto-subs", "--no-write-thumbnail", "--no-playlist",
               "--socket-timeout", "10", "--retries", "2", "--fragment-retries", "2",
               "-P", str(root), "-o", "chat.%(ext)s", context["url"]]
    child = subprocess.Popen(command, cwd=context["root"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             **process.hidden_options(console=True))
    positions, pending = {}, {}
    room = classify_target(context["url"], "YouTube").stable_id or public_url(context["url"])
    def read():
        for file in root.glob("*.live_chat.json*"):
            if not (file.name.endswith(".live_chat.json") or file.name.endswith(".live_chat.json.part")):
                continue
            key = str(file)
            with file.open("rb") as source:
                source.seek(positions.get(key, 0))
                chunk = source.read(4 * 1024 * 1024)
                positions[key] = source.tell()
            value = pending.get(key, b"") + chunk
            lines = value.split(b"\n")
            pending[key] = lines.pop()
            if len(pending[key]) > 4 * 1024 * 1024:
                raise ValueError("oversized_youtube_chat_action")
            for line in lines:
                if not line.strip():
                    continue
                try:
                    for event in messages(json.loads(line), room, time.time()):
                        emit(event)
                except (ValueError, KeyError, TypeError, OverflowError):
                    stats["rejected_count"] += 1
    try:
        while not stop.wait(0.25):
            read()
            if child.poll() is not None:
                if child.returncode:
                    raise RuntimeError("youtube_chat_process_failed")
                break
    finally:
        if child.poll() is None:
            process.stop(child, lambda p: p.kill(), timeout=3)
        read()
        stats["truncated"] = any(p.strip() for p in pending.values())
    if not positions:
        raise PermissionError("youtube_live_chat_track_unavailable")


def twitcasting(context, transport, stop, emit, stats):
    from .twitcasting import events
    user = urlsplit(context["url"]).path.strip("/").split("/")[0]
    if not re.fullmatch(r"[A-Za-z0-9_:]{1,100}", user):
        raise ValueError("invalid_twitcasting_user")
    page = transport.json("https://frontendapi.twitcasting.tv/watch/user/" + user, method="POST", content=b"")
    movie = page.get("movie") or {}
    room = str(movie.get("id") or page.get("movie_id") or "")
    if not room or page.get('is_live') is False:
        history = transport.text("https://twitcasting.tv/" + user + "/show/")
        if page.get('is_live') is False and not re.search(r'data-status=["\']live["\']', history):
            raise PermissionError('twitcasting_not_live')
        match = re.search(r'(?s)<a\s+class="tw-movie-thumbnail2"\s+href="/[^/"]+/movie/(?P<id>\d+)"', history)
        if match:
            room = match["id"]
    if not room.isdigit():
        raise ValueError("twitcasting_movie_unavailable")
    specified = re.search(r'/(?:movie|twplayer)/(\d+)', urlsplit(context['url']).path)
    if specified and specified[1] != room:
        raise PermissionError('twitcasting_broadcast_changed')
    password = option(context.get('command', []), '--video-password')
    if password:
        # Reuse the official extractor's form authentication in this isolated
        # cookie jar before requesting a private comment subscription.
        from yt_dlp.extractor.common import InfoExtractor
        movie_url = f'https://twitcasting.tv/{user}/movie/{room}'
        hidden = InfoExtractor._hidden_inputs(transport.text(movie_url))
        unlocked = transport.response(movie_url, method='POST', data=dict(hidden, password=password),
                                      headers={'Origin':'https://twitcasting.tv', 'Referer':movie_url}).decode('utf-8', 'replace')
        if re.search(r'<form\s+method="POST">\s*<input\s+[^>]+?name="password"', unlocked):
            raise PermissionError('twitcasting_password_rejected')
    endpoint = transport.json("https://twitcasting.tv/eventpubsuburl.php", method="POST", data={"movie_id": room})["url"]
    ws = transport.socket(remote_url(endpoint, ["twitcasting.tv"], websocket=True), origin="https://twitcasting.tv")
    try:
        while not stop.is_set():
            try:
                raw = ws.recv()
            except library("websocket").WebSocketTimeoutException:
                continue
            if not raw:
                raise ConnectionError("twitcasting_disconnected")
            try:
                for event in events(json.loads(raw), room, time.time()):
                    emit(event)
            except (ValueError, TypeError, KeyError):
                stats["rejected_count"] += 1
    finally:
        ws.close()


def nicochannel(context, transport, stop, emit, stats):
    from .nicochannel import collect
    collect(context, transport, stop, emit, stats)


def niconico(context, transport, stop, emit, stats):
    from .niconico import collect
    collect(context, transport, stop, emit, stats)


SOURCES = {"YouTube": youtube, "Twitch": twitch, "TwitCasting": twitcasting,
           "NicoChannel": nicochannel, "Niconico": niconico}


def rplay(context, transport, stop, emit, stats):
    from .rplay import collect
    return collect(context, transport, stop, emit, stats)


SOURCES['Rplay'] = rplay
