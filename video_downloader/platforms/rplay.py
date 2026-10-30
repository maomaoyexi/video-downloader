"""Application policies and protected-session lifecycle for RPlay."""

import re
from urllib.parse import urlsplit, urlunsplit
from urllib.parse import quote
from pathlib import Path
import tempfile
import threading
import importlib.util
import sys


def format_selector(config):
    """Keep the resolution ceiling in every fallback, including muxed HLS.

    The resolution label denotes the shorter edge, as in yt-dlp's resolution
    sorting. RPlay also publishes portrait videos (e.g. 720x1280).
    """
    if str(config.get('AUDIO_MODE', '0')) == '1':
        raise ValueError('Rplay HLS 暂不支持分离音画，请选择合并、同时输出音频或只输出音频')
    resolution = str(config['RESOLUTION'])
    bounds = [''] if resolution == 'best' else [f'[rplay_resolution<={resolution}]']
    codec = {'h264': "[vcodec~='avc1|h264']", 'av1': "[vcodec~='av01']", 'vp9': "[vcodec~='vp9']"}.get(config['CODEC'], '')
    audio = 'bestaudio' + (f"[abr<={config['AUDIO_QUALITY']}]" if config['AUDIO_QUALITY'] != 'best' else '')
    selectors = []
    for preference in ([codec, ''] if codec else ['']):
        selectors.extend(f'bestvideo{bound}{preference}+{audio}' for bound in bounds)
        selectors.extend(f'best{bound}{preference}' for bound in bounds)
    return '/'.join(selectors)


def sanitize_output(value):
    """Remove signed queries/headers before a subprocess line enters UI/logs."""
    def clean(match):
        try:
            parts = urlsplit(match.group())
            return urlunsplit((parts.scheme, parts.hostname or '', parts.path, '', ''))
        except ValueError:
            return '[播放地址已隐藏]'
    value = re.sub(r'https?://[^\s\'"<>]+', clean, value)
    value = re.sub(r'(?i)([\'\"]?(?:authorization|refresh[-_]?token|key2|token)[\'\"]?\s*[=:]\s*[\'\"]?)(?:Bearer\s+)?[^\s,;\'"<>]+', r'\1***', value)
    return re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '***', value)


def auth_arguments(config, directory):
    source = config.get('RPLAY_AUTH_SOURCE', 'none')
    if source == 'none':
        return []
    if source != 'firefox' or directory is None:
        raise ValueError('Rplay 登录来源或会话目录无效')
    return ['--extractor-args', 'Rplay:auth=firefox;auth_dir=' + quote(str(directory), safe='')
            + ';profile=' + quote(str(config.get('RPLAY_FIREFOX_PROFILE', '')), safe='')]


class AuthWorkspace:
    """One encrypted credential cache shared by this app's child processes."""
    def __init__(self, paths):
        self.paths = paths
        self._temporary = None
        self._lock = threading.Lock()

    def directory(self, config):
        if config.get('RPLAY_AUTH_SOURCE', 'none') == 'none':
            return None
        with self._lock:
            if self._temporary is None:
                root = self.paths.download_dir / '.rplay-auth'
                root.mkdir(parents=True, exist_ok=True)
                self._temporary = tempfile.TemporaryDirectory(prefix='session-', dir=root)
            return Path(self._temporary.name)

    def close(self):
        with self._lock:
            if self._temporary:
                self._temporary.cleanup()
                self._temporary = None


_support_lock = threading.Lock()


def auth_support():
    """Load the same bundled auth implementation used by the external plugin."""
    name = '_video_downloader_rplay_auth'
    with _support_lock:
        if name not in sys.modules:
            root = Path(sys._MEIPASS) if getattr(sys, '_MEIPASS', None) else Path(__file__).resolve().parents[2] / 'resource'
            path = root / 'yt-dlp-plugins/video_downloader/yt_dlp_plugins/extractor/_rplay_auth.py'
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules[name] = module
        return sys.modules[name]


def command_auth_options(command):
    from urllib.parse import unquote
    result = {}
    for index, option in enumerate(command):
        value = option.split('=', 1)[1] if option.startswith('--extractor-args=') else (
            command[index + 1] if option == '--extractor-args' and index + 1 < len(command) else '')
        if not value.lower().startswith('rplay:'):
            continue
        for pair in value.split(':', 1)[1].split(';'):
            key, separator, value = pair.partition('=')
            if separator:
                result[key] = unquote(value)
    return result
