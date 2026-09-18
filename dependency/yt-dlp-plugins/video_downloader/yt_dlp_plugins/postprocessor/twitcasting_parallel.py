"""TwitCasting VOD HLS compatibility and parallel prefetch for yt-dlp.

Some TwitCasting archives switch fMP4 initialization sections after an HLS
discontinuity.  yt-dlp's native HLS downloader intentionally rejects that
layout, while FFmpeg understands it but fetches the small media fragments
largely serially.  This before_dl postprocessor downloads the remote assets in
parallel, rewrites the playlist to local files, and leaves the actual muxing
and all normal yt-dlp postprocessing to FFmpeg/yt-dlp.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from yt_dlp.networking import Request
from yt_dlp.postprocessor.common import PostProcessor


_URI_ATTRIBUTE_RE = re.compile(r'(?P<prefix>\bURI=)(?P<quote>["\']?)(?P<uri>.*?)(?P=quote)(?=,|$)')
_SAFE_COMPONENT_RE = re.compile(r'[^A-Za-z0-9_.-]+')
_MEDIA_EXTENSIONS = {'.aac', '.m4a', '.m4s', '.mp4', '.ts'}
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_ASSETS = 50_000


class _DownloadLimiter:
    """Best-effort aggregate limiter matching yt-dlp's --limit-rate setting."""

    def __init__(self, bytes_per_second):
        self._rate = int(bytes_per_second or 0)
        self._started = time.monotonic()
        self._reserved = 0
        self._lock = threading.Lock()

    def wait(self, size):
        if self._rate <= 0 or size <= 0:
            return
        with self._lock:
            self._reserved += size
            target = self._started + self._reserved / self._rate
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)


class TwitCastingParallelHlsPP(PostProcessor):
    """Prefetch multi-map TwitCasting VOD playlists with bounded concurrency."""

    def __init__(self, downloader=None, cleanup='false', **kwargs):
        super().__init__(downloader)
        self._cleanup = str(cleanup).strip().lower() in {'1', 'true', 'yes', 'on'}

    @staticmethod
    def _is_twitcasting(info):
        extractor = str(info.get('extractor_key') or info.get('extractor') or '').lower()
        webpage_url = str(info.get('webpage_url') or info.get('original_url') or '').lower()
        return 'twitcasting' in extractor or 'twitcasting.tv/' in webpage_url

    @staticmethod
    def _safe_component(value, fallback):
        cleaned = _SAFE_COMPONENT_RE.sub('_', str(value or '')).strip('._')
        return (cleaned or fallback)[:80]

    @staticmethod
    def _format_rate(value):
        value = float(value or 0)
        for suffix in ('B/s', 'KiB/s', 'MiB/s', 'GiB/s'):
            if value < 1024 or suffix == 'GiB/s':
                return f'{value:.2f}{suffix}'
            value /= 1024

    @staticmethod
    def _format_eta(seconds):
        seconds = max(0, int(seconds or 0))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'

    @staticmethod
    def _safe_error(error):
        message = re.sub(r'https?://\S+', '<url>', str(error))
        return message[:300]

    def _request_bytes(self, url, headers, *, maximum=None, limiter=None):
        request = Request(url, headers=headers)
        with self._downloader.urlopen(request) as response:
            chunks = []
            total = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if maximum is not None and total > maximum:
                    raise ValueError('播放列表体积异常')
                if limiter is not None:
                    limiter.wait(len(chunk))
                chunks.append(chunk)
        return b''.join(chunks)

    @staticmethod
    def _replace_uri(line, replacement):
        match = _URI_ATTRIBUTE_RE.search(line)
        if not match:
            raise ValueError('HLS URI 属性无法解析')
        escaped = replacement.replace('"', '%22')
        return f'{line[:match.start()]}URI="{escaped}"{line[match.end():]}'

    def _build_local_playlist(self, manifest_url, manifest_text):
        if '#EXT-X-STREAM-INF' in manifest_text:
            raise ValueError('预期媒体播放列表，但收到主播放列表')

        assets = {}
        rewritten = []
        map_count = 0
        media_count = 0
        key_count = 0

        def register(source, kind, ordinal):
            absolute = urljoin(manifest_url, source)
            if urlsplit(absolute).scheme not in {'http', 'https'}:
                raise ValueError('播放列表包含非 HTTP(S) 资源')
            if absolute in assets:
                return assets[absolute]
            suffix = Path(urlsplit(absolute).path).suffix.lower()
            if kind == 'media':
                suffix = suffix if suffix in _MEDIA_EXTENSIONS else '.mp4'
                name = f'media-{ordinal:06d}{suffix}'
            elif kind == 'map':
                suffix = suffix if suffix in _MEDIA_EXTENSIONS else '.mp4'
                name = f'init-{ordinal:04d}{suffix}'
            else:
                name = f'key-{ordinal:04d}.bin'
            assets[absolute] = name
            return name

        for raw_line in manifest_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith('#EXT-X-MAP:'):
                match = _URI_ATTRIBUTE_RE.search(line)
                if not match:
                    raise ValueError('EXT-X-MAP 缺少 URI')
                map_count += 1
                rewritten.append(self._replace_uri(
                    line, register(match.group('uri'), 'map', map_count)))
            elif line.startswith('#EXT-X-KEY:') and 'METHOD=NONE' not in line.upper():
                match = _URI_ATTRIBUTE_RE.search(line)
                if not match:
                    raise ValueError('加密播放列表的 EXT-X-KEY 缺少 URI')
                key_count += 1
                rewritten.append(self._replace_uri(
                    line, register(match.group('uri'), 'key', key_count)))
            elif line.startswith('#'):
                rewritten.append(line)
            else:
                media_count += 1
                rewritten.append(register(line, 'media', media_count))

        if map_count < 2:
            return None
        if not media_count:
            raise ValueError('播放列表中没有媒体分片')
        if len(assets) > _MAX_ASSETS:
            raise ValueError(f'播放列表资源过多（{len(assets)}）')
        return assets, '\n'.join(rewritten) + '\n', media_count, map_count

    def _cache_dir(self, info, format_info):
        output = Path(info.get('_filename') or info.get('filename') or 'twitcasting.mp4')
        video_id = self._safe_component(info.get('id'), 'video')
        format_identity = '-'.join(str(value or '') for value in (
            format_info.get('format_id'),
            f'{format_info.get("width") or 0}x{format_info.get("height") or 0}',
            format_info.get('vcodec'),
            format_info.get('acodec'),
        ))
        format_id = self._safe_component(format_identity, 'default')
        # Do not include the signed manifest URL: TwitCasting can refresh it between
        # runs, while the immutable VOD id + selected format remain a stable cache key.
        return output.parent / f'.tc-hls-{video_id}-{format_id}'

    def _download_asset(self, url, destination, headers, limiter, retries):
        if destination.is_file() and destination.stat().st_size > 0:
            return destination.stat().st_size, True

        partial = destination.with_suffix(destination.suffix + '.part')
        last_error = None
        for attempt in range(retries + 1):
            try:
                request = Request(url, headers=headers)
                with self._downloader.urlopen(request) as response, open(partial, 'wb') as output:
                    downloaded = 0
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        limiter.wait(len(chunk))
                        output.write(chunk)
                        downloaded += len(chunk)
                if downloaded <= 0:
                    raise OSError('服务器返回空分片')
                os.replace(partial, destination)
                return downloaded, False
            except Exception as error:
                last_error = error
                try:
                    partial.unlink()
                except FileNotFoundError:
                    pass
                if attempt < retries:
                    time.sleep(min(4, 0.5 * (2 ** attempt)))
        raise OSError(f'分片下载失败: {last_error}')

    def _prepare_format(self, info, format_info):
        manifest_url = str(format_info.get('url') or '')
        protocol = str(format_info.get('protocol') or '')
        if protocol not in {'m3u8', 'm3u8_native'} or not manifest_url.startswith(('http://', 'https://')):
            return None

        headers = dict(format_info.get('http_headers') or info.get('http_headers') or {})
        manifest_data = self._request_bytes(
            manifest_url, headers, maximum=_MAX_MANIFEST_BYTES)
        manifest_text = manifest_data.decode('utf-8-sig')
        plan = self._build_local_playlist(manifest_url, manifest_text)
        if plan is None:
            return None
        assets, local_manifest, media_count, map_count = plan

        cache_dir = self._cache_dir(info, format_info)
        cache_dir.mkdir(parents=True, exist_ok=True)
        threads = max(1, min(16, int(
            self._downloader.params.get('concurrent_fragment_downloads') or 1)))
        retries_value = self._downloader.params.get('fragment_retries', 3)
        retries = 3 if retries_value in (None, 'inf', 'infinite') else max(0, min(10, int(retries_value)))
        limiter = _DownloadLimiter(self._downloader.params.get('ratelimit'))

        self.to_screen(
            f'[TwitCastingParallel] 检测到 {media_count} 个媒体分片和 {map_count} 个初始化段，'
            f'使用 {threads} 线程并发下载')
        started = time.monotonic()
        last_report = 0.0
        completed = 0
        downloaded_bytes = 0
        asset_items = list(assets.items())
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as pool:
            futures = {
                pool.submit(
                    self._download_asset,
                    url,
                    cache_dir / filename,
                    headers,
                    limiter,
                    retries,
                ): filename
                for url, filename in asset_items
            }
            try:
                for future in concurrent.futures.as_completed(futures):
                    size, cached = future.result()
                    completed += 1
                    if not cached:
                        downloaded_bytes += size
                    now = time.monotonic()
                    if completed < len(asset_items) and now - last_report < 0.25:
                        continue
                    last_report = now
                    elapsed = max(now - started, 0.001)
                    speed = downloaded_bytes / elapsed
                    remaining = len(asset_items) - completed
                    eta = elapsed / completed * remaining if completed else 0
                    percent = completed / len(asset_items) * 100
                    codecs = (
                        f'{format_info.get("vcodec") or "unknown"}|'
                        f'{format_info.get("acodec") or "unknown"}')
                    self.to_screen(
                        f'[TwitCastingParallel] {percent:.1f}% of '
                        f'{completed}/{len(asset_items)} fragments at {self._format_rate(speed)} '
                        f'ETA {self._format_eta(eta)} __VD_STAGE__{codecs}')
            except Exception:
                for pending in futures:
                    pending.cancel()
                raise

        playlist_path = cache_dir / 'local.m3u8'
        partial_playlist = cache_dir / 'local.m3u8.part'
        with open(partial_playlist, 'w', encoding='utf-8', newline='\n') as output:
            output.write(local_manifest)
        os.replace(partial_playlist, playlist_path)
        format_info['url'] = playlist_path.resolve().as_uri()
        format_info['protocol'] = 'm3u8'
        self.to_screen('[TwitCastingParallel] 并发分片准备完成，正在由 FFmpeg 本地封装')
        return str(cache_dir)

    def _cleanup_cache(self, info):
        output = Path(info.get('_filename') or info.get('filename') or '').resolve()
        for raw_path in info.pop('_tc_parallel_cache_dirs', []) or []:
            cache_dir = Path(raw_path).resolve()
            # Only remove the exact cache directories created beside this output.
            if cache_dir.parent != output.parent or not cache_dir.name.startswith('.tc-hls-'):
                self.report_warning('[TwitCastingParallel] 忽略了异常的缓存清理路径')
                continue
            shutil.rmtree(cache_dir, ignore_errors=True)

    def run(self, info):
        if self._cleanup:
            self._cleanup_cache(info)
            return [], info
        if not self._is_twitcasting(info) or info.get('is_live'):
            return [], info
        if Path(info.get('_filename') or info.get('filename') or '').is_file():
            return [], info

        targets = info.get('requested_formats') or [info]
        cache_dirs = []
        original_targets = [
            (format_info, format_info.get('url'), format_info.get('protocol'))
            for format_info in targets
        ]
        try:
            for format_info in targets:
                cache_dir = self._prepare_format(info, format_info)
                if cache_dir:
                    cache_dirs.append(cache_dir)
        except Exception as error:
            for format_info, url, protocol in original_targets:
                format_info['url'] = url
                format_info['protocol'] = protocol
            self.report_warning(
                '[TwitCastingParallel] 并发预取失败，将回退到 FFmpeg 串行下载: '
                f'{self._safe_error(error)}')
            return [], info

        if cache_dirs:
            info['_tc_parallel_cache_dirs'] = cache_dirs
            if info.get('requested_formats'):
                info['protocol'] = '+'.join(
                    str(item.get('protocol') or '') for item in info['requested_formats'])
        return [], info
