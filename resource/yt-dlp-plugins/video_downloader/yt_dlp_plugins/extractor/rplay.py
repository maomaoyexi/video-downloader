"""RPlay authorized HLS VOD, live playback and read-only inspection.

Protocol observations and validation boundaries: docs/rplay-integration.md.
Use yt-dlp networking and media downloaders. Firefox account credentials stay
inside the plugin; shared refresh state is encrypted with Windows DPAPI.
"""

import re
import json
from urllib.parse import urlsplit, urlencode, unquote

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import DownloadError, ExtractorError, float_or_none, parse_iso8601

__all__ = ['RplayVodIE', 'RplayLiveIE', 'RplayUnsupportedIE']

_OID = r'[0-9a-fA-F]{24}'
_SITE = r'https://(?:www\.)?rplay\.live(?::443)?'
_END = r'/?(?:[?#].*)?$'
_HEADERS = {'Origin': 'https://rplay.live', 'Referer': 'https://rplay.live/'}


def _media_url(value):
    """Only accept HTTPS playback endpoints belonging to RPlay."""
    if not isinstance(value, str):
        return None
    if any(character.isspace() or ord(character) < 32 for character in value):
        return None
    try:
        parts = urlsplit(value)
        host = (parts.hostname or '').lower()
        if (parts.scheme == 'https' and not parts.username and not parts.password
                and parts.port in (None, 443)
                and (host == 'rplay.live' or host.endswith('.rplay.live') or host.endswith('.live-video.net'))):
            return value
    except ValueError:
        pass
    return None


def _check_hls(document):
    if not isinstance(document, str) or not document.lstrip('\ufeff').startswith('#EXTM3U'):
        raise ExtractorError('Rplay 返回的播放清单无效', expected=True)
    for tag in re.findall(r'^#EXT-X-(?:SESSION-)?KEY:(.*)', document, re.M):
        attributes = dict(re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,\s]+)', tag))
        method = attributes.get('METHOD', '').strip('"')
        keyformat = attributes.get('KEYFORMAT', 'identity').strip('"')
        if method not in {'NONE', 'AES-128'} or keyformat != 'identity':
            raise ExtractorError('Rplay DRM 或非标准加密暂不支持', expected=True)


class _RplayBaseIE(InfoExtractor):
    def _auth_context(self):
        source = self._configuration_arg('auth', ie_key='Rplay', default=['none'])[0]
        if source == 'none':
            return None
        if source != 'firefox':
            raise ExtractorError('Rplay 登录来源无效', expected=True)
        if not hasattr(self, '_rplay_auth'):
            from ._rplay_auth import AuthContext
            directory = unquote(self._configuration_arg('auth_dir', ie_key='Rplay', default=[''], casesense=True)[0])
            if not directory:
                raise ExtractorError('Rplay 缺少受保护的会话目录', expected=True)
            profile = unquote(self._configuration_arg('profile', ie_key='Rplay', default=[''], casesense=True)[0])
            self._rplay_auth = AuthContext(directory, self._refresh, profile=profile)
        return self._rplay_auth

    def _refresh(self, oid, refresh_token):
        from ._rplay_auth import protected_json
        return protected_json(self._downloader,
            'https://api.rplay.live/rplay/account/refresh-token',
            data=json.dumps({'requestorOid': oid}).encode(),
            headers={**_HEADERS, 'Content-Type': 'application/json', 'platform-type': 'rplay',
                     'refresh-token': refresh_token})

    def _json(self, path, resource_id, query):
        try:
            context = self._auth_context()
            rejected_token = None
            for attempt in range(2):
                credential = context.credential(rejected_token=rejected_token) if context else None
                request_query = dict(query)
                headers = {**_HEADERS, 'Authorization': 'null'}
                if credential:
                    request_query.update(requestorOid=credential['user_oid'], loginType=credential['login_type'], platformType='rplay')
                    headers.update(Authorization=credential['access_token'], **{'platform-type': 'rplay'})
                    if path == 'live/bytedance/play-urls':
                        request_query.update(userId=credential['user_oid'], token=credential['access_token'])
                try:
                    if context:
                        from ._rplay_auth import protected_json
                        result = protected_json(self._downloader, 'https://api.rplay.live/' + path,
                                                headers=headers, query=request_query)
                    else:
                        result = self._download_json(
                            'https://api.rplay.live/' + path, resource_id,
                            headers=headers, query=request_query, note='读取 Rplay 状态')
                    break
                except ExtractorError as exc:
                    if context and attempt == 0 and getattr(exc.cause, 'status', None) == 401:
                        rejected_token = credential['access_token']
                        continue
                    raise
        except ExtractorError as exc:
            # Exception bodies and URLs can contain credential data. Only expose
            # the HTTP status; do not attach the original exception as a cause.
            status = getattr(exc.cause, 'status', None)
            message = {
                401: 'Rplay login required：需要登录',
                403: 'Rplay private：没有观看权限',
                404: 'Rplay 内容不存在或已删除',
                429: 'Rplay HTTP 429：请求过于频繁，请稍后重试',
            }.get(status, f'Rplay 请求失败（HTTP {status}）' if status else 'Rplay 网络请求失败')
            raise ExtractorError(message, expected=True) from None
        except (ValueError, OSError):
            raise ExtractorError('Rplay login required：Firefox 登录状态不可用，请重新登录', expected=True) from None
        if not isinstance(result, dict):
            raise ExtractorError('Rplay 响应结构无效', expected=True)
        return result


class RplayVodIE(_RplayBaseIE):
    IE_NAME = 'rplay:vod'
    _VALID_URL = _SITE + r'/play/(?P<id>' + _OID + ')' + _END

    def _real_extract(self, url):
        video_id = self._match_id(url).lower()
        info = self._json('content', video_id, {
            'contentOid': video_id, 'status': 'published',
            'requestCanView': 'true', 'lang': 'en',
        })
        if info.get('_id') != video_id:
            raise ExtractorError('Rplay 点播身份与请求不一致', expected=True)
        if info.get('drm') is not False:
            raise ExtractorError('Rplay DRM 或未知加密类型暂不支持', expected=True)
        if info.get('deleted') is True:
            raise ExtractorError('Rplay 内容已删除', expected=True)
        if info.get('waitingEncoding') is True:
            raise ExtractorError('Rplay 点播仍在转码，请稍后重试', expected=True)
        access = info.get('canView')
        if not isinstance(access, dict) or access.get('canView') is not True:
            # A URL may be a preview even when the full resource is inaccessible.
            raise ExtractorError('Rplay login required：此内容需要有效登录或订阅权限', expected=True)
        media_url = _media_url(access.get('url'))
        if not media_url:
            raise ExtractorError('Rplay 没有有效的授权播放地址', expected=True)
        if access.get('mediaType') != 'video/mp4' or 'hlsstream' not in urlsplit(media_url).path:
            raise ExtractorError('Rplay 当前仅支持已验证的 HLS 点播', expected=True)
        try:
            document = self._download_webpage(media_url, video_id, headers=_HEADERS,
                                              note='读取 Rplay HLS 清单')
            _check_hls(document)
            formats, _ = self._parse_m3u8_formats_and_subtitles(
                document, media_url, ext='mp4', m3u8_id='hls',
                entry_protocol='m3u8_native', headers=_HEADERS, video_id=video_id)
        except ExtractorError:
            # Keep signed query strings out of the caller's logs/SSE/history.
            raise ExtractorError('Rplay HLS 清单不可用或包含不支持的加密', expected=True) from None
        formats = [item for item in formats if not item.get('has_drm') and _media_url(item.get('url'))]
        if not formats:
            raise ExtractorError('Rplay 没有可下载的普通 HLS 格式', expected=True)
        for item in formats:
            dimensions = [float_or_none(item.get(axis)) for axis in ('width', 'height')]
            if all(value is not None and value > 0 for value in dimensions):
                item['rplay_resolution'] = min(dimensions)
        creator = info.get('creatorInfo')
        creator = creator if isinstance(creator, dict) else {}
        return {
            'id': video_id,
            'title': info.get('title') or video_id,
            'description': info.get('introText'),
            'uploader': creator.get('nickname') or info.get('creatorNickname'),
            'uploader_id': info.get('creatorOid'),
            'timestamp': parse_iso8601(info.get('createdAt')),
            'release_timestamp': parse_iso8601(info.get('publishedAt')),
            'duration': float_or_none(info.get('length')),
            'thumbnail': f'https://pb.rplay.live/thumbnail/{video_id}',
            'age_limit': 18 if info.get('isAdultContent') or info.get('hideContent') else 0,
            'formats': formats,
            'subtitles': {},
            'http_headers': dict(_HEADERS),
            'webpage_url': f'https://rplay.live/play/{video_id}',
        }


class RplayLiveIE(_RplayBaseIE):
    IE_NAME = 'rplay:live'
    _VALID_URL = _SITE + r'/(?:live|creatorhome)/(?P<id>' + _OID + ')' + _END

    def _real_extract(self, url):
        inspect = self._configuration_arg('inspect', default=['0']) == ['1']
        creator_id = self._match_id(url).lower()
        info = self._json('live/play', creator_id, {'creatorOid': creator_id, 'lang': 'en'})
        if info.get('creatorOid') != creator_id:
            raise ExtractorError('Rplay 直播身份与请求不一致', expected=True)
        state = info.get('streamState')
        if state not in {'offline', 'live', 'twitch'}:
            raise ExtractorError('Rplay 转播或未知直播状态尚未接入', expected=True)
        active = state in {'live', 'twitch'}
        if active and (info.get('accessible') is not True or (
                info.get('allowAnonymous') is not True and self._auth_context() is None)):
            raise ExtractorError('Rplay private：直播需要登录或没有观看权限', expected=True)
        started = parse_iso8601(info.get('streamStartTime')) if active else None
        if active and started is None:
            raise ExtractorError('Rplay 直播缺少有效的场次时间', expected=True)
        channel = info.get('twitchLogin') if state == 'twitch' else None
        if state == 'twitch' and (not isinstance(channel, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,25}', channel)):
            raise ExtractorError('Rplay 转播来源无效', expected=True)
        creator = info.get('creatorMetadata')
        creator = creator if isinstance(creator, dict) else {}
        result = {
            'id': creator_id,
            'title': info.get('title') or creator_id,
            'uploader': creator.get('nickname'),
            'timestamp': started,
            'live_status': 'is_live' if active else 'not_live',
            'formats': [],
            'webpage_url': f'https://rplay.live/live/{creator_id}',
        }
        if inspect:
            return result
        if state == 'offline':
            raise ExtractorError('Rplay is not live：直播尚未开始', expected=True)
        if state == 'twitch':
            # Resolve only the public canonical source through the existing
            # Twitch extractor. Never forward RPlay headers, tokens or keys.
            try:
                source = self._downloader.extract_info('https://www.twitch.tv/' + channel.lower(),
                                                       download=False, process=False, ie_key='TwitchStream')
            except (DownloadError, ExtractorError):
                raise ExtractorError('Rplay Twitch 转播源不可用，请检查源平台观看权限', expected=True) from None
            if not isinstance(source, dict) or source.get('is_live') is not True:
                raise ExtractorError('Rplay Twitch 转播源当前不在直播', expected=True)
            for item in source.get('formats') or []:
                dimensions = [float_or_none(item.get(axis)) for axis in ('width', 'height')]
                # One known edge is a conservative upper bound on the shorter
                # edge. Unknown dimensions cannot bypass a configured ceiling.
                dimensions = [value for value in dimensions if value is not None and value > 0]
                if dimensions:
                    item['rplay_resolution'] = min(dimensions)
            return source
        if info.get('useBytePlusStream') is True:
            authorization = self._json('live/bytedance/play-urls', creator_id, {
                'creatorId': creator_id, 'watching': '0', 'key': '',
            })
            play_urls = authorization.get('playUrls')
            if authorization.get('mode') == 'signed' and isinstance(play_urls, dict):
                from ._rplay_relay import MediaRelay
                from yt_dlp.networking import Request
                relay = MediaRelay(lambda endpoint: self._downloader.urlopen(Request(endpoint, headers=_HEADERS)))
                self._rplay_relay = relay
                formats = []
                for quality, height in [('ld', 360), ('sd', 540), ('hd', 720), ('ud', 1080)]:
                    endpoint = _media_url(play_urls.get(quality))
                    if endpoint and urlsplit(endpoint).path.endswith('.flv'):
                        formats.append({'format_id': quality, 'url': relay.add(endpoint), 'ext': 'flv',
                                        'protocol': 'http', 'height': height, 'rplay_resolution': height,
                                        'vcodec': 'h264', 'acodec': 'aac'})
                if not formats:
                    relay.close()
                    raise ExtractorError('Rplay 未返回可用的授权直播格式', expected=True)
                result.update(formats=formats, is_live=True, http_headers=dict(_HEADERS),
                              # Let LiveRunner reauthorize and validate the
                              # broadcast after EOF/network loss. Transparent
                              # FFmpeg reconnects could replay a finite response
                              # or cross into another broadcast in one file.
                              downloader_options={'ffmpeg_args': ['-rw_timeout', '15000000']},
                              thumbnail=f'https://pb.rplay.live/liveChannelThumbnails/{creator_id}')
                return result
            if authorization.get('mode') != 'legacy':
                raise ExtractorError('Rplay 播放授权协议暂不支持', expected=True)
            playback = _media_url(info.get('bytePlusPlaybackUrl'))
        elif info.get('useRplayStreamServer') is True:
            key = self._json('live/key2', creator_id, {'lang': 'en'}).get('authKey') if self._auth_context() else ''
            if not isinstance(key, str):
                raise ExtractorError('Rplay 播放授权无效', expected=True)
            playback = 'https://api.rplay.live/live/stream/playlist.m3u8?' + urlencode({'creatorOid': creator_id, 'key2': key})
        else:
            playback = _media_url(info.get('playUrl'))
        if not playback:
            raise ExtractorError('Rplay 没有有效的直播播放地址', expected=True)
        try:
            document = self._download_webpage(playback, creator_id, headers=_HEADERS, note='读取 Rplay 直播清单')
            _check_hls(document)
            formats, _ = self._parse_m3u8_formats_and_subtitles(
                document, playback, ext='mp4', m3u8_id='hls', live=True,
                entry_protocol='m3u8_native', headers=_HEADERS, video_id=creator_id)
        except ExtractorError:
            raise ExtractorError('Rplay 直播清单不可用或加密不受支持', expected=True) from None
        result.update(formats=[item for item in formats if not item.get('has_drm') and _media_url(item.get('url'))],
                      is_live=True, http_headers=dict(_HEADERS),
                      thumbnail=f'https://pb.rplay.live/liveChannelThumbnails/{creator_id}')
        for item in result['formats']:
            sizes = [float_or_none(item.get(axis)) for axis in ('width', 'height')]
            if all(value is not None and value > 0 for value in sizes):
                item['rplay_resolution'] = min(sizes)
        if not result['formats']:
            raise ExtractorError('Rplay 没有可用直播格式', expected=True)
        return result


class RplayUnsupportedIE(InfoExtractor):
    IE_NAME = 'rplay:unsupported'
    _VALID_URL = _SITE + r'(?:/.*)?$'

    @classmethod
    def suitable(cls, url):
        return not (RplayVodIE.suitable(url) or RplayLiveIE.suitable(url)) and super().suitable(url)

    def _real_extract(self, url):
        raise ExtractorError('Rplay 暂不支持此链接，请使用单个 /play/ 点播链接', expected=True)
