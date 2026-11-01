import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.helpers import PROJECT_ROOT
from video_downloader.core.command import build_ytdlp_cmd
from video_downloader.core.constants import DEFAULT_CONFIG
from video_downloader.core.paths import DOWNLOAD_PLATFORM_DIRS
from video_downloader.core.platform import detect_platform, is_live_url
from video_downloader.core.validation import validate_config
from video_downloader.live.inspect import LiveInspector
from video_downloader.live.modes import resolve_mode, LiveModeError, capability_for
from video_downloader.live.probe import ProbeService, LiveStatus, YtDlpProbe, LiveProbe
from video_downloader.live.urls import classify_target, TargetKind
from video_downloader.live.wait import LiveWatchService, WatchJobStore

OID = '682065da13ed2c564c77d8f7'
VOD = f'https://rplay.live/play/{OID}'
LIVE = f'https://rplay.live/live/{OID}'


@pytest.mark.parametrize('path,kind,live', [
    ('play/'+OID, TargetKind.ARCHIVE, False), ('live/'+OID, TargetKind.CHANNEL, True),
    ('creatorhome/'+OID, TargetKind.CHANNEL, True),
    ('creatorhome/'+OID+'?page=contents', TargetKind.LIST, False),
    ('live', TargetKind.UNKNOWN, False), ('play/invalid', TargetKind.UNKNOWN, False),
    ('c/handle', TargetKind.UNKNOWN, False), ('live/'+OID+'/extra', TargetKind.UNKNOWN, False),
])
def test_url_contracts(path, kind, live):
    url = 'https://rplay.live/' + path
    assert detect_platform(url) == 'Rplay'
    assert classify_target(url).kind is kind
    assert is_live_url(url) is live


@pytest.mark.parametrize('url', ['http://rplay.live/live/'+OID, 'https://api.rplay.live/live/'+OID,
    'https://user:secret@rplay.live/live/'+OID, 'https://rplay.live:500/live/'+OID,
    'https://rplay.live:invalid/live/'+OID, 'https://rplay.live.evil/live/'+OID])
def test_urls_cannot_enable_live_through_host_or_scheme_confusion(url):
    assert classify_target(url, 'Rplay').kind is TargetKind.UNKNOWN
    assert not is_live_url(url, 'Rplay')


def test_platform_settings_paths_and_commands_reuse_existing_options():
    config, errors = validate_config({'PLATFORM': 'Rplay', 'RESOLUTION': '720', 'AUDIO_MODE': '3'})
    assert not errors and config['PLATFORM'] == 'Rplay'
    assert 'Rplay' in DOWNLOAD_PLATFORM_DIRS
    command = build_ytdlp_cmd(VOD, config, PROJECT_ROOT, platform_override='Rplay', cookie_file='cookies.txt')
    assert str(PROJECT_ROOT/'resource/yt-dlp-plugins') in command
    assert '--no-continue' in command and '--abort-on-unavailable-fragments' in command
    assert '--cookies' not in command and '--cookies-from-browser' not in command
    assert '-x' in command and command[-1] == VOD
    assert 'Rplay' in command[command.index('-o')+1]


def test_catch_up_remains_closed_without_verified_dvr():
    with pytest.raises(LiveModeError):
        resolve_mode('Rplay', 'catch_up')
    for mode in ['auto', 'live_edge']:
        assert resolve_mode('Rplay', mode).value == 'live_edge'
        command = build_ytdlp_cmd(LIVE, DEFAULT_CONFIG, PROJECT_ROOT, platform_override='Rplay', is_live=True, live_mode=mode)
        assert 'http:ffmpeg' in command and '--no-live-from-start' in command


def test_unsupported_download_path_fails_before_network():
    with pytest.raises(ValueError, match='路径'):
        build_ytdlp_cmd('https://rplay.live/c/somebody', DEFAULT_CONFIG, PROJECT_ROOT, platform_override='Rplay')


def test_live_probe_is_readonly_uses_proxy_and_has_stable_session_identity():
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps({
        'id': OID, 'live_status': 'is_live', 'timestamp': 1793239200,
        'title': '真实接口形状的合成在播状态', 'formats': [],
    }), stderr=''))
    probe = YtDlpProbe('yt-dlp', runner=runner, command_context=lambda target: [
        'yt-dlp', '--proxy', 'socks5://127.0.0.1:7890', '--download-archive', 'private-archive'])
    target = classify_target(LIVE)
    first = probe.probe(target)
    second = probe.probe(target)
    assert first.status is LiveStatus.LIVE
    assert first.stream_instance_key == second.stream_instance_key
    assert str(first.started_at) in first.stream_instance_key
    command = runner.call_args.args[0]
    assert 'RplayLive:inspect=1' in command and '--ignore-no-formats-error' in command
    assert command[command.index('--proxy')+1].startswith('socks5:')
    assert '--download-archive' not in command and '--simulate' in command
    service = ProbeService(providers={'Rplay': SimpleNamespace(probe=lambda *a, **k: first)})
    inspection = LiveInspector(service).inspect(LIVE)
    assert inspection['status'] == 'live' and inspection['can_wait'] is True
    assert inspection['effective_mode'] == 'live_edge'


def test_wait_privacy_failure_does_not_start_media(tmp_path):
    store = WatchJobStore(tmp_path/'jobs.sqlite')
    probe = Mock()
    probe.probe.return_value = LiveProbe('Rplay', TargetKind.CHANNEL, OID, LiveStatus.PRIVATE, retryable=False)
    start = Mock()
    service = LiveWatchService(store=store, probe_service=probe, on_live=start, start_thread=False)
    try:
        result = service.add(LIVE)
        assert result['waiting'] is True
        service.tick(wait=True)
        assert store.get(result['job']['id']).status.value == 'expired'
        start.assert_not_called()
        assert capability_for('Rplay').wait is True
    finally:
        service.stop()


@pytest.mark.parametrize('status,expected', [('private', LiveStatus.PRIVATE), ('HTTP 429', LiveStatus.ERROR)])
def test_probe_failure_cannot_expose_signed_urls(status, expected):
    runner = Mock(return_value=SimpleNamespace(returncode=1, stdout='', stderr=(
        f'{status}: https://api.rplay.live/live/play?token=SECRET')))
    service = ProbeService('yt-dlp', runner=runner, command_context=lambda target: ['yt-dlp'])
    result = service.probe(classify_target(LIVE))
    assert result.status is expected
    assert 'SECRET' not in result.error
