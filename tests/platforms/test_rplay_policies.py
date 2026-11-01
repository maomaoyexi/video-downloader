import subprocess
import sys

import pytest

from tests.helpers import PROJECT_ROOT
from tests.helpers.download import create_executor
from video_downloader.core.command import build_ytdlp_cmd
from video_downloader.core.constants import DEFAULT_CONFIG
from video_downloader.platforms.rplay import format_selector, sanitize_output

VOD = 'https://rplay.live/play/682065da13ed2c564c77d8f7'


@pytest.mark.parametrize('resolution,expected', [('best', 1080), ('1080', 1080), ('720', 720), ('480', 480)])
def test_portrait_format_selection_preserves_the_ceiling(resolution, expected):
    from yt_dlp import YoutubeDL
    data = {'id': 'test', 'title': 'portrait', 'extractor': 'rplay:vod', 'formats': [
        {'format_id': str(width), 'url': f'https://pb3.rplay.live/{width}.m3u8',
         'ext': 'mp4', 'width': width, 'height': height, 'rplay_resolution': width,
         'vcodec': 'avc1', 'acodec': 'mp4a', 'tbr': width*3}
        for width, height in [(480, 854), (720, 1280), (1080, 1920)]
    ]}
    with YoutubeDL({'quiet': True, 'format': format_selector(dict(DEFAULT_CONFIG, RESOLUTION=resolution))}) as ydl:
        selected = ydl.process_ie_result(data, download=False)
    assert selected['width'] == expected


def test_no_format_under_ceiling_cannot_fall_back_to_highest():
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import ExtractorError
    data = {'id': 'test', 'title': 'portrait', 'extractor': 'rplay:vod', 'formats': [
        {'url': 'https://pb3.rplay.live/1080.m3u8', 'ext': 'mp4', 'width': 1080, 'height': 1920,
         'rplay_resolution': 1080, 'vcodec': 'avc1', 'acodec': 'mp4a'},
    ]}
    with YoutubeDL({'quiet': True, 'format': format_selector(dict(DEFAULT_CONFIG, RESOLUTION='360'))}) as ydl:
        with pytest.raises(ExtractorError):
            ydl.process_ie_result(data, download=False)


def test_unavailable_codec_can_fall_back_without_dropping_resolution_limit():
    selector = format_selector(dict(DEFAULT_CONFIG, RESOLUTION='720', CODEC='av1'))
    assert all('[rplay_resolution<=720]' in option for option in selector.split('/'))
    assert "[vcodec~='av01']" in selector


def test_split_audio_video_fails_before_task_starts():
    with pytest.raises(ValueError, match='分离音画'):
        build_ytdlp_cmd(VOD, dict(DEFAULT_CONFIG, AUDIO_MODE='1'), PROJECT_ROOT, platform_override='Rplay')


def test_info_json_cannot_persist_playback_tokens_from_custom_args():
    command = build_ytdlp_cmd(VOD, DEFAULT_CONFIG, PROJECT_ROOT, platform_override='Rplay', custom_args='--write-info-json')
    assert command.index('--no-write-info-json') > command.index('--write-info-json')
    assert '--ignore-config' in command


@pytest.mark.parametrize('text', [
    'ERROR https://api2.rplay.live/content/hlsstream?token=SECRET&key2=ALSO_SECRET',
    'Authorization: Bearer SECRET', 'refresh-token=SECRET', 'key2=SECRET',
    '{"token": "SECRET"}', 'https://user:SECRET@pb3.rplay.live/master.m3u8?signature=ALSO_SECRET#fragment',
    'https://[invalid?SECRET', 'eyJabc.def.SECRET',
])
def test_logs_do_not_retain_signed_queries_or_tokens(text):
    cleaned = sanitize_output(text)
    assert 'SECRET' not in cleaned


def test_reader_redacts_before_lines_enter_the_output_queue(tmp_path):
    executor, _ = create_executor(tmp_path)
    text = 'ERROR https://api2.rplay.live/content/hlsstream?token=SECRET&key2=SECRET\n'
    process = subprocess.Popen([sys.executable, '-c', f'print({text!r})', VOD], stdout=subprocess.PIPE)
    try:
        output, done = executor._start_reader(process)
        assert done.wait(10)
        process.wait(timeout=10)
        lines = []
        while not output.empty():
            lines.append(output.get_nowait())
        assert lines and all('SECRET' not in line for line in lines)
        assert 'https://api2.rplay.live/content/hlsstream' in '\n'.join(lines)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
