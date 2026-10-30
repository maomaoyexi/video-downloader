"""Read only RPlay's Firefox session; keep credentials out of argv and logs.

RPlay moved its account session to IndexedDB in 2026. The bounded structured
clone subset follows Mozilla's format and Google's dfindexeddb documentation.
Unsupported values fail closed; this is not a general browser data reader.
"""

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import struct
import time
import hashlib
import os
import tempfile
import threading
import urllib.parse


class AuthError(ValueError):
    pass


def decompress_session(raw):
    """Bounded raw Snappy reader, per google/snappy format_description.txt.

    The standalone yt-dlp executable has no cramjam extension. Keep this small
    protocol reader pure Python so source and portable application paths agree.
    """
    length = 0
    for index, value in enumerate(raw[:5]):
        length |= (value & 127) << (index * 7)
        if value < 128:
            break
    else:
        raise AuthError('invalid_firefox_session_size')
    if length > 8 * 1024 * 1024:
        raise AuthError('oversized_firefox_session')
    position = index + 1
    output = bytearray()
    def take(size):
        nonlocal position
        if size < 0 or position + size > len(raw):
            raise AuthError('truncated_firefox_compression')
        value = raw[position:position + size]
        position += size
        return value
    while position < len(raw):
        tag = take(1)[0]
        kind = tag & 3
        if kind == 0:
            size = tag >> 2
            size = size + 1 if size < 60 else int.from_bytes(take(size - 59), 'little') + 1
            if len(output) + size > length:
                raise AuthError('invalid_firefox_compression_length')
            output.extend(take(size))
        else:
            size = 4 + ((tag >> 2) & 7) if kind == 1 else 1 + (tag >> 2)
            offset = (((tag & 0xE0) << 3) | take(1)[0]) if kind == 1 else int.from_bytes(take(2 if kind == 2 else 4), 'little')
            if offset == 0 or offset > len(output) or len(output) + size > length:
                raise AuthError('invalid_firefox_compression_offset')
            for _ in range(size):
                output.append(output[-offset])
    if len(output) != length:
        raise AuthError('invalid_firefox_compression_length')
    return bytes(output)


def decode_clone(raw):
    """Decode only the JSON-shaped subset used by RPlay's account session."""
    data = decompress_session(raw)
    if len(data) < 16 or struct.unpack_from('<I', data, 4)[0] != 0xFFF10000:
        raise AuthError('unsupported_firefox_session_header')
    stream = io.BytesIO(data)
    stream.seek(8)
    objects, count = [], 0

    def take(size):
        result = stream.read(size)
        if len(result) != size:
            raise AuthError('truncated_firefox_session')
        return result

    def read(depth=0):
        nonlocal count
        count += 1
        if depth > 64 or count > 100000:
            raise AuthError('complex_firefox_session')
        raw_value = take(8)
        value, tag = struct.unpack('<II', raw_value)
        if tag in {0xFFFF0000, 0xFFFF0001}:
            result = None
        elif tag == 0xFFFF0002:
            result = bool(value)
        elif tag == 0xFFFF0003:
            result = struct.unpack('<i', raw_value[:4])[0]
        elif tag == 0xFFFF0004:
            size = value & 0x7FFFFFFF
            if size > 8 * 1024 * 1024:
                raise AuthError('oversized_firefox_string')
            result = take(size if value & 0x80000000 else size * 2).decode(
                'latin-1' if value & 0x80000000 else 'utf-16le')
        elif tag in {0xFFFF0007, 0xFFFF0008}:
            # Sparse arrays are represented as indexed dictionaries. Session
            # credential extraction only consumes named object properties.
            result = {}
            objects.append(result)
            while True:
                pair = take(8)
                next_tag = struct.unpack('<II', pair)[1]
                stream.seek(-8, 1)
                if next_tag in {0xFFFF0013, 0xFFFF0000}:
                    take(8)
                    break
                key = read(depth + 1)
                if not isinstance(key, (str, int)):
                    raise AuthError('invalid_firefox_session_key')
                result[key] = read(depth + 1)
        elif tag == 0xFFFF000D and value < len(objects):
            result = objects[value]
        elif tag == 0xFFFF0005:
            result = struct.unpack('<d', take(8))[0]
            objects.append(result)
        elif tag <= 0xFFF00000:
            result = struct.unpack('<d', raw_value)[0]
        else:
            raise AuthError('unsupported_firefox_session_type')
        take((-stream.tell()) % 8)
        return result

    result = read()
    if stream.tell() != len(data) or not isinstance(result, dict):
        raise AuthError('invalid_firefox_session_record')
    return result


def read_firefox_session(profile=''):
    """Snapshot only https://rplay.live's account-session record into memory."""
    from yt_dlp.cookies import _firefox_browser_dirs
    roots = [Path(root) for root in _firefox_browser_dirs() if Path(root).is_dir()]
    if profile:
        explicit = Path(profile).expanduser()
        profiles = [explicit] if explicit.is_absolute() else [root / profile for root in roots]
    else:
        profiles = [path for root in roots for path in root.iterdir() if path.is_dir()] if roots else []
    candidates = [path for folder in profiles
                  for path in (folder / 'storage/default/https+++rplay.live/idb').glob('*.sqlite')]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)) as source:
                with contextlib.closing(sqlite3.connect(':memory:')) as snapshot:
                    deadline = time.monotonic() + 3
                    def progress(*_):
                        if time.monotonic() > deadline:
                            raise AuthError('firefox_session_snapshot_timeout')
                    source.backup(snapshot, pages=128, progress=progress, sleep=0.05)
                    name = snapshot.execute('SELECT name FROM database').fetchone()
                    if name != ('rplay-account-session',):
                        continue
                    row = snapshot.execute(
                        'SELECT data FROM object_data WHERE object_store_id IN '
                        '(SELECT id FROM object_store WHERE name=?) AND key=?',
                        ('records', bytes.fromhex('30746674746a706f'))).fetchone()
                    if not row or not isinstance(row[0], bytes):
                        continue
                    record = decode_clone(row[0])
                    session = record.get('session')
                    if isinstance(session, dict) and isinstance(session.get('token'), str):
                        user = session.get('user')
                        oid = user.get('oid') or user.get('_id') if isinstance(user, dict) else None
                        return {'user_oid': oid, 'access_token': session['token'],
                                'refresh_token': session.get('refreshToken'),
                                'login_type': session.get('loginType', 'rplay')}
        except (sqlite3.Error, OSError):
            continue
    raise AuthError('firefox_rplay_login_required')


def token_expiry(token):
    import base64
    import math
    try:
        value = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
        expiry = claims['exp']
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry):
            raise ValueError
        return expiry
    except (ValueError, KeyError, IndexError, TypeError):
        raise AuthError('invalid_rplay_access_token') from None


def protect(value, *, decrypt=False):
    """Windows DPAPI, scoped to the current OS user and this application."""
    if os.name != 'nt':
        raise AuthError('rplay_auth_requires_windows_dpapi')
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    def blob(data):
        buffer = ctypes.create_string_buffer(data)
        return Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer
    source, source_buffer = blob(value)
    entropy, entropy_buffer = blob(b'video-downloader:rplay:session:v1')
    output = Blob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    api.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    api.restype = wintypes.BOOL
    if not api(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
        raise AuthError('rplay_credential_protection_failed')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(output.data)


@contextlib.contextmanager
def account_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'session.lock').open('a+b') as handle:
        deadline = time.monotonic() + 30
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise AuthError('rplay_auth_lock_timeout') from None
                time.sleep(0.05)
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class AuthContext:
    def __init__(self, directory, refresh, *, profile='', reader=read_firefox_session,
                 clock=time.time, protection=protect):
        self.directory = Path(directory)
        self.refresh, self.profile, self.reader = refresh, profile, reader
        self.clock, self.protection = clock, protection
        self._lock = threading.Lock()

    def credential(self, *, rejected_token=None):
        with self._lock, account_lock(self.directory):
            browser = self.reader(self.profile)
            oid = browser.get('user_oid')
            import re
            if not isinstance(oid, str) or not re.fullmatch(r'[a-f0-9]{24}', oid):
                raise AuthError('invalid_rplay_account_identity')
            if browser.get('login_type') not in {'rplay', 'plax'}:
                raise AuthError('unsupported_rplay_login_type')
            fingerprint = hashlib.sha256((oid + ':' + str(browser.get('refresh_token'))).encode()).hexdigest()
            cache = self.directory / (hashlib.sha256(oid.encode()).hexdigest() + '.dpapi')
            current = browser
            try:
                saved = json.loads(self.protection(cache.read_bytes(), decrypt=True))
                if (saved.get('source') == fingerprint and saved.get('user_oid') == oid
                        and token_expiry(saved['access_token']) > token_expiry(browser['access_token'])):
                    current = saved
            except (OSError, AuthError, ValueError, KeyError, TypeError):
                pass
            if token_expiry(current['access_token']) > self.clock() + 60 and current['access_token'] != rejected_token:
                return current
            refresh_token = current.get('refresh_token')
            if not isinstance(refresh_token, str) or not refresh_token or any(c.isspace() for c in refresh_token):
                raise AuthError('rplay_login_expired')
            response = self.refresh(oid, refresh_token)
            access = response.get('accessToken') if isinstance(response, dict) else None
            if not isinstance(access, str) or token_expiry(access) <= self.clock() + 30:
                raise AuthError('rplay_refresh_failed')
            updated = dict(browser, access_token=access, refresh_token=response.get('refreshToken') or refresh_token,
                           source=fingerprint)
            payload = self.protection(json.dumps(updated).encode())
            descriptor, name = tempfile.mkstemp(prefix='.auth-', dir=self.directory)
            try:
                with os.fdopen(descriptor, 'wb') as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(name, cache)
            finally:
                Path(name).unlink(missing_ok=True)
            return updated


def protected_json(downloader, endpoint, *, query=None, headers=None, data=None):
    """Use yt-dlp's proxy/TLS stack, with redirects disabled for credentials."""
    from urllib.request import HTTPRedirectHandler
    from yt_dlp.networking import Request
    from yt_dlp.networking._urllib import UrllibRH
    from yt_dlp.networking.exceptions import HTTPError, RequestError
    from yt_dlp.utils import ExtractorError
    parts = urllib.parse.urlsplit(endpoint)
    if parts.scheme != 'https' or parts.netloc != 'api.rplay.live':
        raise AuthError('invalid_rplay_account_endpoint')
    class RplayUrllibRH(UrllibRH):
        def _create_instance(self, *args, **kwargs):
            opener = super()._create_instance(*args, **kwargs)
            for handler in opener.handlers:
                if isinstance(handler, HTTPRedirectHandler):
                    handler.redirect_request = lambda req, fp, code, msg, headers, newurl: None
            return opener
    director = downloader.build_request_director([RplayUrllibRH])
    try:
        url = endpoint + ('?' + urllib.parse.urlencode(query) if query else '')
        with director.send(Request(url, headers=headers, data=data)) as response:
            body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise AuthError('oversized_rplay_account_response')
            try:
                return json.loads(body)
            except (ValueError, UnicodeError):
                raise ExtractorError('Invalid Rplay account response') from None
    except HTTPError as exc:
        raise ExtractorError('Rplay account request failed', cause=exc) from None
    except RequestError:
        raise ExtractorError('Rplay account network request failed') from None
    finally:
        director.close()
