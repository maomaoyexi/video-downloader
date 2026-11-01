"""Playback contracts, loopback isolation and source identity on reconnect."""

import importlib
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError as UrlHTTPError
from urllib.request import urlopen

import pytest
from yt_dlp.utils import ExtractorError

from tests.platforms.test_rplay_plugin import rplay, fixture, live_ie, LIVE, CREATOR, MASTER
from video_downloader.live.engines.rplay import RplayEngine
from video_downloader.live.probe import LiveProbe, LiveStatus, ProbeError
from video_downloader.live.urls import TargetKind


def playing(**changes):
    return dict(fixture('offline-live.json'), streamState='live',
                streamStartTime='2026-10-29T10:00:00Z', **changes)


def test_signed_byteplus_formats_keep_remote_credentials_out_of_argv(monkeypatch):
    monkeypatch.setenv('no_proxy','example.test')
    monkeypatch.setenv('NO_PROXY','example.test')
    ie = live_ie(playing(useBytePlusStream=True), inspect=False)
    ie._json = Mock(side_effect=[playing(useBytePlusStream=True), {
        'mode': 'signed', 'playUrls': {'ld': 'https://livestream-play.rplay.live/live/id_ld.flv?sign=SECRET',
                                    'hd': 'https://evil.example/id.flv', 'sd': 'https://rplay.live/x.m3u8'}}])
    result = ie._real_extract(LIVE)
    try:
        assert result['is_live'] and len(result['formats']) == 1
        media = result['formats'][0]
        assert media['height'] == 360 and media['protocol'] == 'http'
        assert result['downloader_options']['ffmpeg_args'] == ['-rw_timeout','15000000']
        assert media['url'].startswith('http://127.0.0.1:') and 'SECRET' not in str(result)
        request = ie._json.call_args.args
        assert request[0] == 'live/bytedance/play-urls'
        assert request[2]['watching'] == '0'
    finally:
        ie._rplay_relay.close()


@pytest.mark.parametrize('authorization', [
    {'mode':'signed','playUrls':{}}, {'mode':'signed','playUrls':[]}, {'mode':'unknown'},
])
def test_unverified_playback_modes_never_start_media(authorization):
    ie = live_ie(inspect=False)
    ie._json = Mock(side_effect=[playing(useBytePlusStream=True), authorization])
    with pytest.raises(ExtractorError):
        ie._real_extract(LIVE)


@pytest.mark.parametrize('backend', ['legacy', 'native', 'ivs'])
def test_hls_live_backends_reuse_encryption_and_resolution_policy(backend):
    data = playing(useBytePlusStream=backend == 'legacy', useRplayStreamServer=backend == 'native',
                   bytePlusPlaybackUrl='https://livestream.rplay.live/live/master.m3u8',
                   playUrl='https://example.live-video.net/master.m3u8')
    ie = live_ie(inspect=False)
    ie._json = Mock(side_effect=[data, {'mode':'legacy'}] if backend == 'legacy' else [data])
    ie._download_webpage = Mock(return_value=MASTER)
    result = ie._real_extract(LIVE)
    assert result['formats'][0]['height'] == result['formats'][0]['rplay_resolution'] == 720
    assert result['is_live'] and result['timestamp'] > 0


def test_native_authenticated_live_requests_key_without_exposing_it():
    ie = live_ie(inspect=False)
    ie._auth_context = Mock(return_value=object())
    ie._json = Mock(side_effect=[playing(useRplayStreamServer=True), {'authKey':'TEST_KEY'}])
    ie._download_webpage = Mock(return_value=MASTER)
    ie._real_extract(LIVE)
    assert ie._json.call_args.args[0] == 'live/key2'
    assert 'key2=TEST_KEY' in ie._download_webpage.call_args.args[0]
    ie._json = Mock(side_effect=[playing(useRplayStreamServer=True), {'authKey':[] }])
    with pytest.raises(ExtractorError, match='授权无效'):
        ie._real_extract(LIVE)


@pytest.mark.parametrize('document', ['broken', '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="x"'])
def test_live_invalid_manifest_is_sanitized(document):
    ie = live_ie(playing(playUrl='https://rplay.live/live.m3u8'), inspect=False)
    ie._download_webpage = Mock(return_value=document)
    with pytest.raises(ExtractorError, match='直播清单不可用'):
        ie._real_extract(LIVE)


def test_live_rejects_missing_url_and_empty_formats():
    ie = live_ie(playing(playUrl='https://evil.example/x'), inspect=False)
    with pytest.raises(ExtractorError, match='播放地址'):
        ie._real_extract(LIVE)
    ie = live_ie(playing(playUrl='https://rplay.live/live.m3u8'), inspect=False)
    ie._download_webpage = Mock(return_value='#EXTM3U')
    ie._parse_m3u8_formats_and_subtitles = Mock(return_value=([], {}))
    with pytest.raises(ExtractorError, match='可用直播格式'):
        ie._real_extract(LIVE)


def test_relay_streams_known_route_and_rejects_arbitrary_remote_targets(monkeypatch):
    monkeypatch.setenv('no_proxy','example.test')
    monkeypatch.setenv('NO_PROXY','example.test')
    relay_module = importlib.import_module(rplay.__name__+'._rplay_relay')
    response = io.BytesIO(b'FLV'+b'x'*70000)
    remote = Mock(return_value=response)
    relay = relay_module.MediaRelay(remote)
    local = relay.add('https://livestream-play.rplay.live/x.flv?sign=SECRET')
    try:
        with urlopen(local, timeout=3) as output:
            assert output.read() == b'FLV'+b'x'*70000
            assert output.headers['Cache-Control'] == 'no-store'
        assert response.closed
        with pytest.raises(UrlHTTPError) as error:
            urlopen(local+'/https://evil.example', timeout=3)
        assert error.value.code == 404 and remote.call_count == 1
        remote.side_effect = SimpleRemoteError()
        with pytest.raises(UrlHTTPError) as error:
            urlopen(local, timeout=3)
        assert error.value.code == 403 and 'SECRET' not in str(error.value)
    finally:
        relay.close()
        relay.close()
    assert not relay._thread.is_alive() and not relay._routes


def test_real_ffmpeg_relay_bypasses_upstream_proxy_and_recovers_from_early_eof(tmp_path,monkeypatch):
    import os
    import subprocess
    import threading
    import json
    from tests.helpers import PROJECT_ROOT
    from video_downloader.core.paths import AppPaths
    from video_downloader.live.runner import LiveRunner
    ffmpeg=PROJECT_ROOT/'dependency/ffmpeg.exe'
    if not ffmpeg.exists():
        pytest.skip('requires managed FFmpeg')
    source=tmp_path/'source.flv'
    subprocess.run([str(ffmpeg),'-v','error','-nostdin','-y','-f','lavfi','-i','testsrc2=size=160x90:rate=10',
                    '-f','lavfi','-i','sine=frequency=500:sample_rate=44100','-t','2','-c:v','libx264',
                    '-preset','ultrafast','-c:a','aac','-f','flv',str(source)],check=True,capture_output=True,timeout=20)
    from yt_dlp import YoutubeDL
    from video_downloader.live.integrity import IntegrityChecker
    # Exercise yt-dlp's actual per-video FFmpeg options, rather than relying on
    # global input arguments that would also affect a delegated HLS source.
    with YoutubeDL({'quiet':True,'format':'ld','external_downloader':{'http':'ffmpeg'},
                    'ffmpeg_location':str(ffmpeg.parent),'outtmpl':str(tmp_path/'native.%(ext)s')}) as downloader:
        ie=rplay.RplayLiveIE(downloader)
        ie._json=Mock(side_effect=[playing(useBytePlusStream=True),{'mode':'signed',
                     'playUrls':{'ld':'https://livestream-play.rplay.live/native.flv?sign=SYNTHETIC'}}])
        downloader.urlopen=Mock(side_effect=lambda *args:source.open('rb'))
        info=ie._real_extract(LIVE)
        try:
            downloader.process_ie_result(info)
        finally:
            ie._rplay_relay.close()
    native=tmp_path/'native.flv'
    assert IntegrityChecker(PROJECT_ROOT/'dependency/ffprobe.exe',ffmpeg).inspect(native)['valid']
    monkeypatch.setenv('http_proxy','http://127.0.0.1:1')
    monkeypatch.setenv('HTTP_PROXY','http://127.0.0.1:1')
    monkeypatch.setenv('no_proxy','example.test')
    monkeypatch.setenv('NO_PROXY','example.test')
    relay_module=importlib.import_module(rplay.__name__+'._rplay_relay')
    relay=relay_module.MediaRelay(lambda url:source.open('rb'))
    local=relay.add('https://livestream-play.rplay.live/fixture.flv?sign=SYNTHETIC')
    assert 'example.test' in os.environ['no_proxy'] and '127.0.0.1' in os.environ['no_proxy']
    remote=Mock()
    remote.probe.side_effect=[probe(),probe(),probe(),probe(LiveStatus.OFFLINE)]
    engine=RplayEngine(['yt-dlp',LIVE],LIVE,probe=remote)
    validate=engine.command
    def command(directory):
        validate(directory)
        return [str(ffmpeg),'-v','error','-nostdin','-y','-i',local,'-c','copy',str(directory/'recording.mkv')]
    engine.command=command
    class NoBackoff(threading.Event):
        def wait(self,timeout=None):
            return self.is_set()
    paths=AppPaths(tmp_path/'app')
    paths.executable=lambda name,suffix:PROJECT_ROOT/'dependency'/(name+suffix)
    runner=LiveRunner(paths,'.exe',log=Mock(),progress=Mock(),publish_process=lambda proc:True,
                      clear_process=Mock(),force_kill=lambda proc:proc.kill(),emit_event=Mock())
    monkeypatch.setattr(runner,'_engine',lambda *args:engine)
    try:
        result=runner.run(['fixture'],url=LIVE,platform='Rplay',mode='live_edge',
                          config={'LIVE_MAX_RETRIES':1,'LIVE_MIN_FREE_MB':64},cancel=NoBackoff())
    finally:
        relay.close()
    report=json.loads(Path(result['report']).read_text(encoding='utf8'))
    assert remote.probe.call_count==4
    assert report['conclusion']=='gaps' and report['stop_reason']=='ended'
    assert len(report['files'])==2 and all(file['valid'] for file in report['files'])
    assert 'source_still_live_after_eof' in report['warnings']


class SimpleRemoteError(Exception):
    status = 403


def probe(status=LiveStatus.LIVE, start=100):
    return LiveProbe('Rplay', TargetKind.CHANNEL, CREATOR, status, started_at=start)


def test_reconnect_revalidates_same_broadcast_and_never_joins_a_new_one(tmp_path):
    source = Mock()
    source.probe.side_effect = [probe(), probe(), probe(start=200)]
    engine = RplayEngine(['yt-dlp','--extractor-args','Rplay:auth=firefox',LIVE], LIVE, probe=source)
    for number in [1,2]:
        command = engine.command(tmp_path/str(number))
        assert str(tmp_path/str(number)) in command and 'Rplay:auth=firefox' in command
    with pytest.raises(PermissionError, match='instance_changed'):
        engine.command(tmp_path/'3')


@pytest.mark.parametrize('status', [LiveStatus.ERROR, LiveStatus.UNKNOWN, LiveStatus.PRIVATE, LiveStatus.OFFLINE])
def test_initial_uncertain_state_cannot_start_a_child(status,tmp_path):
    engine = RplayEngine(['yt-dlp',LIVE],LIVE,probe=Mock(probe=Mock(return_value=probe(status))))
    with pytest.raises(ProbeError if status in {LiveStatus.ERROR,LiveStatus.UNKNOWN} else PermissionError):
        engine.command(tmp_path)


def test_eof_requires_source_end_evidence_and_permission_loss_is_permanent():
    source = Mock()
    engine = RplayEngine(['yt-dlp',LIVE],LIVE,probe=source)
    source.probe.return_value = probe()
    engine.command(Path('part-1'))
    for status, expected in [(LiveStatus.LIVE,False),(LiveStatus.OFFLINE,True),
                              (LiveStatus.ENDED,True),(LiveStatus.UNKNOWN,False)]:
        source.probe.return_value=probe(status)
        assert engine.source_ended() is expected
    source.probe.side_effect = ProbeError('synthetic network',retryable=True)
    assert engine.source_ended() is False
    source.probe.side_effect = ProbeError('synthetic denial',status=LiveStatus.PRIVATE,retryable=False)
    with pytest.raises(PermissionError):
        engine.source_ended()
    source.probe.side_effect=None
    source.probe.return_value=probe(LiveStatus.PRIVATE)
    with pytest.raises(PermissionError):
        engine.source_ended()


def test_twitch_relay_resolves_canonical_source_without_forwarding_rplay_credentials():
    data=playing(twitchLogin='Test_Channel')
    data['streamState']='twitch'
    data['twitchToken']='SECRET_SOURCE_TOKEN'
    data['playUrl']='https://rplay.live/ignored?token=SECRET'
    inspection=live_ie(data)._real_extract(LIVE)
    assert inspection['live_status']=='is_live' and inspection['id']==CREATOR
    ie=live_ie(data,inspect=False)
    ie._downloader.extract_info=Mock(return_value={'id':'source-1','is_live':True,'formats':[
        {'height':360,'width':640},{'height':720},{'width':None,'height':None}]})
    result=ie._real_extract(LIVE)
    assert result['formats'][0]['rplay_resolution']==360
    assert result['formats'][1]['rplay_resolution']==720
    assert 'rplay_resolution' not in result['formats'][2]
    assert 'SECRET' not in str(result) and 'http_headers' not in result
    assert 'downloader_options' not in result
    ie._downloader.extract_info.assert_called_once_with('https://www.twitch.tv/test_channel',
                                                       download=False,process=False,ie_key='TwitchStream')
    for source in [None,{'is_live':False}]:
        ie._downloader.extract_info.return_value=source
        with pytest.raises(ExtractorError,match='不在直播'):
            ie._real_extract(LIVE)
    ie._downloader.extract_info.side_effect=ExtractorError('SYNTHETIC_SECRET')
    with pytest.raises(ExtractorError,match='观看权限') as error:
        ie._real_extract(LIVE)
    assert 'SYNTHETIC_SECRET' not in str(error.value)
    for name in ['name/extra','name?token=SECRET',None,'x'*26]:
        data['twitchLogin']=name
        with pytest.raises(ExtractorError,match='转播来源无效'):
            live_ie(data,inspect=False)._real_extract(LIVE)


def test_media_identity_also_prevents_source_platform_restart_from_being_joined():
    engine=RplayEngine(['yt-dlp',LIVE],LIVE,probe=Mock())
    engine.observe_metadata({'id':'source-stream-1','timestamp':100})
    engine.observe_metadata({'id':'source-stream-1','timestamp':100})
    with pytest.raises(PermissionError,match='media_instance_changed'):
        engine.observe_metadata({'id':'source-stream-2','timestamp':101})
    with pytest.raises(PermissionError,match='identity_unavailable'):
        engine.observe_metadata({})
