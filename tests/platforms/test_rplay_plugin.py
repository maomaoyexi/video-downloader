"""Real response contracts plus adversarial cases; no network in unit tests."""

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.helpers import PROJECT_ROOT

pytest.importorskip('yt_dlp')
from yt_dlp import YoutubeDL
from yt_dlp.networking.common import Response
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import ExtractorError

PLUGIN = PROJECT_ROOT / 'resource/yt-dlp-plugins/video_downloader/yt_dlp_plugins/extractor/rplay.py'
FIXTURES = Path(__file__).parent / 'fixtures/rplay'
spec = importlib.util.spec_from_file_location('rplay_contract_test', PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
rplay = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rplay
spec.loader.exec_module(rplay)
OID = '682065da13ed2c564c77d8f7'
VOD = f'https://rplay.live/play/{OID}'
CREATOR = '667adc9e9aa7f739a2158ff3'
LIVE = f'https://rplay.live/live/{CREATOR}'
MASTER = '''#EXTM3U
#EXT-X-SESSION-KEY:METHOD=AES-128,URI="https://api2.rplay.live/content/key",KEYFORMAT="identity"
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2"
https://pb3.rplay.live/fixture/720.m3u8
'''


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def vod_ie(data=None, document=MASTER):
    ie = rplay.RplayVodIE(YoutubeDL({'quiet': True}))
    ie._download_json = Mock(return_value=fixture('public-vod.json') if data is None else data)
    ie._download_webpage = Mock(return_value=document)
    return ie


@pytest.mark.parametrize('suffix', ['', '/', '?playlist=untrusted', '#player'])
def test_public_vod_identity_formats_and_metadata(suffix):
    ie = vod_ie()
    result = ie._real_extract(VOD + suffix)
    assert result['id'] == OID
    assert result['duration'] == 11.483
    assert result['formats'][0]['height'] == 720
    assert result['formats'][0]['protocol'] == 'm3u8_native'
    assert result['uploader'] == fixture('public-vod.json')['creatorInfo']['nickname']
    assert result['webpage_url'] == VOD
    assert result['subtitles'] == {}
    assert 'canView' not in result and 'streamables' not in result
    assert ie._download_json.call_count == 1  # never expand a playlist
    assert ie._download_json.call_args.kwargs['query']['requestCanView'] == 'true'


@pytest.mark.parametrize('change,message', [
    ({'_id': '0' * 24}, '身份'), ({'drm': True}, 'DRM'), ({'drm': None}, 'DRM'),
    ({'deleted': True}, '删除'), ({'waitingEncoding': True}, '转码'),
    ({'canView': None}, 'login required'),
    ({'canView': {'canView': False, 'url': 'https://pb3.rplay.live/preview.m3u8'}}, 'login required'),
    ({'canView': {'canView': True, 'url': 'https://evil.example/media', 'mediaType': 'video/mp4'}}, '播放地址'),
    ({'canView': {'canView': True, 'url': 'https://pb3.rplay.live/media.mpd', 'mediaType': 'application/dash+xml'}}, 'HLS'),
])
def test_unsafe_or_unavailable_vod_never_requests_media(change, message):
    data = fixture('public-vod.json')
    data.update(change)
    ie = vod_ie(data)
    with pytest.raises(ExtractorError, match=message):
        ie._real_extract(VOD)
    ie._download_webpage.assert_not_called()


def test_user_supplied_vod_requires_account_and_is_not_a_preview_success():
    data = fixture('login-required-vod.json')
    ie = vod_ie(data)
    with pytest.raises(ExtractorError, match='login required'):
        ie._real_extract(f'https://rplay.live/play/{data["_id"]}')
    ie._download_webpage.assert_not_called()


@pytest.mark.parametrize('document', [
    '<html>login</html>', '', '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="secret"',
    '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,KEYFORMAT="com.widevine",URI="secret"',
    '#EXTM3U\n#EXT-X-SESSION-KEY:METHOD=UNKNOWN,URI="secret"',
    '#EXTM3U\n#EXT-X-KEY:URI="secret"',
])
def test_invalid_or_drm_manifests_fail_without_exposing_urls(document):
    with pytest.raises(ExtractorError, match='清单不可用') as exc:
        vod_ie(document=document)._real_extract(VOD)
    assert 'REDACTED' not in str(exc.value)


def test_no_valid_format_is_an_error():
    ie = vod_ie()
    ie._parse_m3u8_formats_and_subtitles = Mock(return_value=([
        {'url': 'https://pb3.rplay.live/fixture.m3u8', 'has_drm': True},
        {'url': 'https://evil.example/master.m3u8'},
    ], {}))
    with pytest.raises(ExtractorError, match='普通 HLS'):
        ie._real_extract(VOD)


@pytest.mark.parametrize('status,expected', [(401, 'login required'), (403, 'private'), (404, '不存在'), (429, '429'), (503, '503')])
def test_api_errors_are_bounded_and_redacted(status, expected):
    ie = vod_ie()
    response = Response(io.BytesIO(b'credential-response'), 'https://api.rplay.live/content?token=secret', {}, status)
    ie._download_json.side_effect = ExtractorError('private-token=secret', cause=HTTPError(response))
    with pytest.raises(ExtractorError, match=expected) as exc:
        ie._real_extract(VOD)
    assert 'secret' not in str(exc.value)
    assert exc.value.cause is None
    ie._download_json.assert_called_once()


def test_network_error_and_wrong_response_shape_are_sanitized():
    ie = vod_ie()
    ie._download_json.side_effect = ExtractorError('secret network path')
    with pytest.raises(ExtractorError, match='网络请求失败'):
        ie._real_extract(VOD)
    for data in ([], None, 'secret'):
        ie._download_json.side_effect = None
        ie._download_json.return_value = data
        with pytest.raises(ExtractorError, match='响应结构'):
            ie._json('content', OID, {})


@pytest.mark.parametrize('value', [None, '', 'http://pb3.rplay.live/x', 'https://rplay.live.evil/x',
    'https://evil.example/x', 'https://user:secret@api.rplay.live/x', 'https://api.rplay.live:444/x',
    'https://api.rplay.live:invalid/x', 'https://api.rplay.live/\nx'])
def test_media_endpoint_allowlist(value):
    assert rplay._media_url(value) is None


def live_ie(data=None, inspect=True):
    params = {'quiet': True, 'extractor_args': {'rplaylive': {'inspect': ['1']}}} if inspect else {'quiet': True}
    ie = rplay.RplayLiveIE(YoutubeDL(params))
    ie._download_json = Mock(return_value=fixture('offline-live.json') if data is None else data)
    return ie


def test_real_offline_response_does_not_fetch_keys_or_media():
    ie = live_ie()
    result = ie._real_extract(LIVE)
    assert result['live_status'] == 'not_live'
    assert result['timestamp'] is None and result['formats'] == []
    assert 'chatUrl' not in result and 'playUrl' not in result
    ie._download_json.assert_called_once()


def test_normal_live_extraction_cannot_record_an_offline_room():
    ie = live_ie(inspect=False)
    with pytest.raises(ExtractorError, match='not live'):
        ie._real_extract(LIVE)
    ie._download_json.assert_called_once()


@pytest.mark.parametrize('change,message', [
    ({'creatorOid': '0' * 24}, '身份'), ({'streamState': 'youtube'}, '转播'),
    ({'streamState': 'unknown'}, '未知'),
    ({'streamState': 'live', 'allowAnonymous': False}, 'private'),
    ({'streamState': 'live', 'accessible': False}, 'private'),
    ({'streamState': 'live', 'streamStartTime': 'invalid'}, '场次时间'),
])
def test_live_uncertain_states_do_not_look_offline(change, message):
    data = fixture('offline-live.json')
    data.update(change)
    with pytest.raises(ExtractorError, match=message):
        live_ie(data)._real_extract(LIVE)


def test_native_public_live_is_inspectable_but_has_no_download_formats():
    data = fixture('offline-live.json')
    data.update(streamState='live', streamStartTime='2026-10-29T10:00:00Z')
    result = live_ie(data)._real_extract(LIVE)
    assert result['live_status'] == 'is_live' and result['timestamp'] > 0
    assert not result['formats']


@pytest.mark.parametrize('url', [VOD, VOD+'/', 'https://www.rplay.live:443/play/'+OID])
def test_vod_matching_and_unsupported_fallback_do_not_overlap(url):
    assert rplay.RplayVodIE.suitable(url)
    assert not rplay.RplayUnsupportedIE.suitable(url)


def test_unsupported_paths_have_an_actionable_error():
    ie = rplay.RplayUnsupportedIE()
    assert ie.suitable('https://rplay.live/c/custom')
    assert not ie.suitable(VOD.replace('rplay.live', 'rplay.live.evil'))
    assert not ie.suitable(LIVE)
    with pytest.raises(ExtractorError, match='单个'):
        ie._real_extract('https://rplay.live/c/custom')


def test_authenticated_requests_retry_401_once_and_never_retry_403(monkeypatch):
    import importlib
    support=importlib.import_module(rplay.__name__+'._rplay_auth')
    context=Mock()
    context.credential.side_effect=[{'user_oid':OID,'access_token':'TEST_ACCESS','login_type':'rplay'},
                                    {'user_oid':OID,'access_token':'TEST_RENEWED','login_type':'rplay'}]
    ie=vod_ie()
    ie._auth_context=Mock(return_value=context)
    response=Response(io.BytesIO(b'SECRET'),'https://api.rplay.live/',{},401)
    request=Mock(side_effect=[ExtractorError('SECRET',cause=HTTPError(response)),{'mode':'signed'}])
    monkeypatch.setattr(support,'protected_json',request)
    assert ie._json('live/bytedance/play-urls',OID,{}) == {'mode':'signed'}
    assert context.credential.call_args.kwargs == {'rejected_token':'TEST_ACCESS'}
    sent=request.call_args.kwargs
    assert sent['query']['userId'] == OID and sent['query']['token'] == 'TEST_RENEWED'
    assert sent['headers']['Authorization'] == 'TEST_RENEWED'
    context.credential.side_effect=None
    context.credential.return_value={'user_oid':OID,'access_token':'TEST_ACCESS','login_type':'rplay'}
    request.reset_mock()
    response=Response(io.BytesIO(b'SECRET'),'https://api.rplay.live/',{},403)
    request.side_effect=ExtractorError('SECRET',cause=HTTPError(response))
    with pytest.raises(ExtractorError,match='private'):
        ie._json('content',OID,{})
    assert request.call_count == 1
    context.credential.side_effect=ValueError('SECRET')
    with pytest.raises(ExtractorError,match='login required') as error:
        ie._json('content',OID,{})
    assert 'SECRET' not in str(error.value)


def test_auth_configuration_preserves_paths_and_refresh_header(tmp_path,monkeypatch):
    import importlib
    from urllib.parse import quote
    support=importlib.import_module(rplay.__name__+'._rplay_auth')
    directory=tmp_path/'中文 Path;profile'
    params={'quiet':True,'extractor_args':{'rplay':{'auth':['firefox'],'auth_dir':[quote(str(directory),safe='')],
                                                  'profile':[quote('CaseSensitive.Profile',safe='')]}}}
    ie=rplay.RplayVodIE(YoutubeDL(params))
    assert ie._auth_context().directory == directory
    assert ie._auth_context().profile == 'CaseSensitive.Profile'
    request=Mock(return_value={'accessToken':'TEST'})
    monkeypatch.setattr(support,'protected_json',request)
    assert ie._refresh(OID,'TEST_REFRESH') == {'accessToken':'TEST'}
    assert request.call_args.kwargs['headers']['refresh-token'] == 'TEST_REFRESH'
    assert json.loads(request.call_args.kwargs['data']) == {'requestorOid':OID}
    for config in [{'auth':['unknown']},{'auth':['firefox']}]:
        ie=rplay.RplayVodIE(YoutubeDL({'quiet':True,'extractor_args':{'rplay':config}}))
        with pytest.raises(ExtractorError):
            ie._auth_context()
