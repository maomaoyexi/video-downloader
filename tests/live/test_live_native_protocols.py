"""Portable native plugin contracts and live rendition preservation."""
from tests.helpers import PROJECT_ROOT
import importlib.util
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from video_downloader.live.catchup import CatchUpPlanner, metadata_command
from video_downloader.live.engines.withnydl import managed_binary

ROOT=PROJECT_ROOT


def load_plugin(kind,name):
    path=ROOT/'resource/yt-dlp-plugins/video_downloader/yt_dlp_plugins'/kind/(name+'.py')
    spec=importlib.util.spec_from_file_location('release_'+name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_niconico_native_mux_delegates_both_inputs_to_upstream_heartbeat():
    module=load_plugin('postprocessor','niconico_live_mux')
    from yt_dlp.downloader.niconico import NiconicoLiveFD
    formats=[{'protocol':'niconico_live','url':'https://media/video'},
             {'protocol':'niconico_live','url':'https://media/audio'}]
    info={'is_live':True,'requested_formats':formats,'protocol':'niconico_live+niconico_live'}
    pp=module.NiconicoLiveMuxPP(Mock(params={}, _postprocessor_hooks=[]))
    native=Mock(return_value=True)
    def upstream(self, filename, info):
        return native(self, filename, info)
    with patch.object(NiconicoLiveFD,'real_download',upstream):
        _,adapted=pp.run(dict(info))
        assert 'requested_formats' not in adapted and adapted['protocol']=='niconico_live'
        assert NiconicoLiveFD.real_download(SimpleNamespace(),'out',adapted)
        passed=native.call_args.args[2]
        assert [f['url'] for f in passed['requested_formats']]==['https://media/video','https://media/audio']
        assert all(f['protocol']=='m3u8' for f in passed['requested_formats'])
        # Installation is idempotent and never creates another seat connection.
        wrapper=NiconicoLiveFD.real_download
        module.install_mux_adapter()
        assert NiconicoLiveFD.real_download is wrapper
    pp=module.NiconicoLiveMuxPP(Mock(params={'simulate':True}, _postprocessor_hooks=[]))
    assert 'requested_formats' in pp.run(dict(info))[1]
    info['is_live']=False
    assert pp.run(info)[1] is info


def test_niconico_ended_programme_is_exposed_as_replay():
    module=load_plugin('extractor','niconico_live')
    parser=module.ProgrammeData()
    parser.feed('<script id="embedded-data" data-props="{&quot;program&quot;:{&quot;status&quot;:&quot;ENDED&quot;}}"></script>')
    assert parser.status=='ENDED'
    extractor=module.NiconicoLiveIE()
    def source(self,url):
        self._broadcast_status='ENDED'
        return {'is_live':True,'id':'lv1'}
    with patch.object(module.BaseNiconicoLiveIE,'_real_extract',source):
        result=extractor._real_extract('https://live.nicovideo.jp/watch/lv1')
    assert result['is_live'] is False and result['live_status']=='was_live'


def test_managed_withny_binary_requires_matching_manifest(tmp_path):
    root=tmp_path/'Withny';root.mkdir()
    executable=root/'withny-dl.exe';executable.write_bytes(b'native')
    manifest=root/'manifest.json'
    manifest.write_text(json.dumps({'version':'2.0.0-local-chat-1','sha256':hashlib.sha256(b'native').hexdigest()}))
    assert managed_binary(tmp_path)==executable
    executable.write_bytes(b'changed')
    assert managed_binary(tmp_path) is None
    manifest.write_text('bad')
    assert managed_binary(tmp_path) is None


def test_niconico_live_rejects_sequential_separate_files(tmp_path):
    import pytest
    from video_downloader.core.command import build_ytdlp_cmd
    from video_downloader.core.constants import DEFAULT_CONFIG
    with pytest.raises(ValueError,match='分离音视频'):
        build_ytdlp_cmd('https://live.nicovideo.jp/watch/lv123',dict(DEFAULT_CONFIG,AUDIO_MODE='1'),
                        tmp_path,is_live=True,platform_override='Niconico')


def test_catchup_preserves_selection_and_chooses_matching_archive_rendition():
    command=['app','--format=worst','-S','res:480','-o','private','url']
    prepared=metadata_command(command,'url')
    assert '--format=worst' in prepared and 'res:480' in prepared and 'private' not in prepared
    edge={'is_live':True,'timestamp':1000,'uploader_id':'channel','height':480,'fps':30}
    archive={'id':'v123','timestamp':1000,'uploader_id':'channel','formats':[
        {'is_from_start':True,'format_id':'480p30','height':480,'fps':30},
        {'is_from_start':True,'format_id':'1080p60','height':1080,'fps':60}]}
    planner=CatchUpPlanner(lambda *_:SimpleNamespace(returncode=0,stdout=json.dumps(archive)))
    evidence=planner.probe(command,'url','Twitch',edge_info=edge)
    assert evidence.available and evidence.backfill_format=='480p30'
    edge['fps']=60
    assert not planner.probe(command,'url','Twitch',edge_info=edge).available

def test_withny_wait_markers_and_opaque_private_clock_cache(tmp_path):
    from video_downloader.live.engines.withnydl import WithnyEngine
    from video_downloader.live.session import LiveSession
    from video_downloader.live.danmaku.dependencies import library
    session=LiveSession(tmp_path/'jobs','Withny','live_edge','withny://configured-channels')
    config=tmp_path/'watch.yaml'
    config.write_text('channels:\n  room: {}\ncredentialsFile: original.yaml\n')
    (tmp_path/'original.yaml').write_text('sessionToken: scoped-session\n')
    engine=WithnyEngine(['withny','watch','--config',str(config)],session,config,True)
    directory,part=session.part('withny-dl',[])
    engine.command(directory)
    assert not engine.waiting
    engine.line('LIVE_NATIVE_STATE:{"kind":"idle","channel":"room"}')
    assert engine.waiting
    engine.line('LIVE_NATIVE_STATE:{"kind":"started","channel":"room","stream":"one"}')
    assert not engine.waiting
    engine.line('LIVE_NATIVE_STATE:{"kind":"finished","channel":"room","stream":"one"}')
    assert engine.waiting
    engine.line('LIVE_NATIVE_STATE:{"kind":"error","channel":"room"}')
    assert not engine.waiting
    engine.line('LIVE_NATIVE_STATE:invalid')
    (directory/'one.info.json').write_text('{"Stream":{"uuid":"one"}}')
    engine.private_cache.write_bytes(b'\xffencrypted-native-cache')
    transport=Mock()
    transport.json.side_effect=[{'accessToken':'credential-value-123'}, 'https://media.test/live.m3u8?token=private']
    with patch('video_downloader.live.danmaku.transport.Transport',return_value=transport):
        metadata=engine.clock_metadata(directory)
    assert metadata['url'].startswith('https://media.test')
    assert transport.json.call_count==2
    assert transport.json.call_args.kwargs['headers']['Authorization']=='Bearer credential-value-123'
    assert 'Authorization' not in metadata['http_headers']
    assert 'credential-value-123' not in engine.private.read_text(encoding='utf-8')
    engine.close()
    assert not engine.private.exists() and not engine.private_cache.exists()


def test_twitcasting_comment_unlock_reuses_password_and_hidden_inputs():
    import threading
    import pytest
    from video_downloader.live.danmaku.sources import twitcasting
    transport=Mock()
    transport.json.side_effect=[{'is_live':True,'movie':{'id':123}},
                                {'url':'wss://s1.twitcasting.tv/event.pubsub'}]
    transport.text.return_value='<input type="hidden" name="csrf" value="csrf-value">'
    transport.response.return_value=b'<div>unlocked</div>'
    transport.socket.return_value.recv.return_value=''
    with pytest.raises(ConnectionError):
        twitcasting({'url':'https://twitcasting.tv/room/movie/123','command':['x','--video-password=pw']},
                    transport,threading.Event(),Mock(),{'rejected_count':0})
    assert transport.response.call_args.kwargs['data']=={'csrf':'csrf-value','password':'pw'}
    transport.json.side_effect=[{'is_live':True,'movie':{'id':456}}]
    with pytest.raises(PermissionError,match='broadcast_changed'):
        twitcasting({'url':'https://twitcasting.tv/room/movie/123'},transport,threading.Event(),Mock(),{})
