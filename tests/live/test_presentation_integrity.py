"""A monotonic decode clock alone cannot prove a usable presentation timeline."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from video_downloader.live.integrity import IntegrityChecker


@pytest.mark.parametrize('pts,expected',[(3601,False),(.133,True)])
def test_presentation_jump_is_not_hidden_by_a_monotonic_decode_clock(tmp_path,pts,expected):
    media=tmp_path/'recording.mkv'
    media.write_bytes(b'synthetic media placeholder')
    metadata={'streams':[{'index':0,'codec_type':'video','codec_name':'h264','avg_frame_rate':'30/1'},
                         {'index':1,'codec_type':'audio','codec_name':'aac'}],
              'format':{'format_name':'matroska','duration':str(pts+1)}}
    packets=f'''stream_index=0|pts_time=0|dts_time=0
stream_index=1|pts_time=0|dts_time=0
stream_index=0|pts_time={pts}|dts_time=0.033
stream_index=0|pts_time=0.067|dts_time=0.067
stream_index=1|pts_time=0.067|dts_time=0.067
'''
    def run(command,**kwargs):
        if '-show_format' in command:
            return SimpleNamespace(returncode=0,stderr=b'',stdout=json.dumps(metadata).encode())
        if '-show_packets' in command:
            kwargs['stdout'].write(packets.encode())
            return SimpleNamespace(returncode=0,stderr=b'')
        return SimpleNamespace(returncode=0,stderr=b'')
    with patch('video_downloader.live.integrity.subprocess.run',side_effect=run):
        result=IntegrityChecker('ffprobe','ffmpeg').inspect(media)
    assert result['valid'] is expected
    assert result['timestamps']['0']['backwards']==0
    assert ('presentation_timestamp_discontinuity' in result['errors']) is (not expected)
