"""Receive-only AWS IVS comments with RPlay's own token provider."""

import json
import re
import time
from urllib.parse import urlsplit

from .models import CommentEvent
from .timeline import epoch
from ..urls import classify_target
from video_downloader.platforms.rplay import auth_support, command_auth_options


def events(payload, room, received):
    if not isinstance(payload, dict):
        return
    event_type = payload.get('Type')
    stamp = epoch(payload.get('SendTime'))
    sender = payload.get('Sender') if isinstance(payload.get('Sender'), dict) else {}
    attributes = payload.get('Attributes') if isinstance(payload.get('Attributes'), dict) else {}
    sender_attributes = sender.get('Attributes') if isinstance(sender.get('Attributes'), dict) else {}
    if event_type == 'MESSAGE':
        body = payload.get('Content')
        if not isinstance(body, str):
            return
        try:
            value = json.loads(body)
            if isinstance(value, dict):
                body = value.get('m', '')
        except ValueError:
            pass
        kind = 'chat'
    elif event_type == 'EVENT' and payload.get('EventName') in {'donation', 'mission'}:
        body = attributes.get('content')
        kind = 'gift'
    else:
        return
    if not isinstance(body, str) or not body.strip() or len(body) > 10000:
        return
    # Keep nicknames only when they actually arrived in the source event.
    yield CommentEvent('Rplay', room, '_timeline', 0, body,
                       str(sender.get('UserId') or attributes.get('userId') or ''),
                       str(sender_attributes.get('nickname') or sender_attributes.get('DisplayName') or ''),
                       kind=kind, placement='top' if kind == 'gift' else 'scroll',
                       utc_ts=stamp, recv_ts=received, message_id=str(payload.get('Id') or ''),
                       source='rplay_ivs', time_source='server' if stamp is not None else 'receive')


def collect(context, transport, stop, emit, stats):
    options = command_auth_options(context['command'])
    if options.get('auth') != 'firefox' or not options.get('auth_dir'):
        raise PermissionError('rplay_comment_login_required')
    support = auth_support()
    room = classify_target(context['url'], 'Rplay').stable_id
    headers = {'Origin': 'https://rplay.live', 'Referer': 'https://rplay.live/', 'platform-type': 'rplay'}
    def refresh(oid, refresh_token):
        return transport.json('https://api.rplay.live/rplay/account/refresh-token', method='POST',
                              headers={**headers, 'refresh-token': refresh_token}, json={'requestorOid': oid}, follow_redirects=False)
    auth = support.AuthContext(options['auth_dir'], refresh, profile=options.get('profile', ''))
    def request(path):
        rejected = None
        for attempt in range(2):
            try:
                credential = auth.credential(rejected_token=rejected)
            except support.AuthError:
                raise PermissionError('rplay_comment_login_required') from None
            try:
                return transport.json('https://api.rplay.live/' + path, headers={**headers, 'Authorization': credential['access_token']},
                                      params={'creatorOid': room, 'key': '', 'requestorOid': credential['user_oid'],
                                              'loginType': credential['login_type'], 'platformType': 'rplay'}, follow_redirects=False)
            except Exception as exc:
                if attempt == 0 and getattr(getattr(exc, 'response', None), 'status_code', None) == 401:
                    rejected = credential['access_token']
                    continue
                raise
    live = request('live/play')
    if live.get('accessible') is not True:
        raise PermissionError('rplay_comment_access_denied')
    socket_url = live.get('chatUrl')
    socket_url = socket_url.strip() if isinstance(socket_url, str) else ''
    if any(character.isspace() or ord(character) < 32 for character in socket_url):
        raise PermissionError('rplay_unknown_comment_endpoint')
    parts = urlsplit(socket_url or '')
    if (parts.scheme != 'wss' or parts.username or parts.password or parts.port not in (None, 443)
            or not re.fullmatch(r'edge\.ivschat\.[a-z0-9-]+\.amazonaws\.com', parts.hostname or '')
            or parts.path not in ('', '/') or parts.query or parts.fragment):
        raise PermissionError('rplay_unknown_comment_endpoint')
    token_data = request('live/chattoken')
    token = token_data.get('token')
    if not isinstance(token, str) or not token:
        raise PermissionError('rplay_comment_token_unavailable')
    # AWS IVS tokens are single-use. Each worker reconnect calls this provider
    # again; never cache the chat token or attempt to replay it.
    ws = transport.socket(socket_url, origin='https://rplay.live', subprotocols=[token])
    stats['connected_at'] = time.time()
    try:
        while not stop.is_set():
            try:
                raw = ws.recv()
            except Exception as exc:
                if 'timeout' in type(exc).__name__.lower():
                    continue
                stats['possible_gap'] = True
                raise
            if not raw:
                stats['possible_gap'] = True
                raise ConnectionError('rplay_comment_disconnected')
            if len(raw) > 1024 * 1024:
                stats['rejected_count'] += 1
                continue
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict) and payload.get('Type') == 'DISCONNECT':
                    stats['possible_gap'] = True
                    raise ConnectionError('rplay_comment_disconnected')
                for event in events(payload, room, time.time()):
                    emit(event)
            except (ValueError, TypeError, KeyError):
                stats['rejected_count'] += 1
    finally:
        ws.close()
