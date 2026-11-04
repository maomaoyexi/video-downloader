"""Comment source contracts, clock provenance, bounded workers and safe re-export."""
import io
import json
import os
import queue
import threading
import time
import contextlib
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from video_downloader.core.validation import validate_config
from video_downloader.live.danmaku import nicochannel, niconico, sources, worker
from video_downloader.live.danmaku.capture import CommentCapture
from video_downloader.live.danmaku.dependencies import library, MissingDependency
from video_downloader.live.danmaku.models import CommentEvent
from video_downloader.live.danmaku.preferences import enabled, platform_defaults, SOURCES
from video_downloader.live.danmaku.service import process_comments
from video_downloader.live.danmaku.store import CommentStore
from video_downloader.live.danmaku.timeline import epoch, project
from video_downloader.live.danmaku.transport import Transport, remote_url, option
from video_downloader.live.danmaku.twitch import parse_line, unescape
from video_downloader.live.danmaku.twitcasting import events as tc_events
from video_downloader.live.danmaku.withny import read_chat
from video_downloader.live.danmaku.youtube import messages
from video_downloader.live.engines.withnydl import WithnyEngine
from video_downloader.live.session import LiveSession, RecordingStore, recover_interrupted


def event(**kw):
    return replace(CommentEvent('Twitch', 'room', '_timeline', 0, 'hello', user_id='user',
                                user_name='name', utc_ts=1001, message_id='one', time_source='server'), **kw)


@pytest.mark.parametrize('platform', SOURCES)
def test_platform_switch_overrides_both_global_states(platform):
    for global_, preference, expected in [(0,'inherit',False),(1,'inherit',True),(0,'on',True),(1,'off',False)]:
        config={'LIVE_DANMAKU_ENABLED':global_, 'LIVE_DANMAKU_PLATFORMS':json.dumps({platform:preference})}
        normalized, errors=validate_config(config)
        assert not errors
        assert enabled(normalized,platform) is expected
    assert not enabled({'LIVE_DANMAKU_ENABLED':1},'Twitter')
    assert enabled({'LIVE_DANMAKU_ENABLED':1,'LIVE_DANMAKU_PLATFORMS':'bad'},platform)


@pytest.mark.parametrize('value', ['[]','null','{"Twitter":"on"}','{"Twitch":1}','{"Twitch":[]}'])
def test_platform_validation_rejects_invalid_values(value):
    assert validate_config({'LIVE_DANMAKU_PLATFORMS':value})[1]


def test_offset_validation_and_clock_provenance():
    assert platform_defaults({'YouTube':'inherit','Twitch':'on'})=={'Twitch':'on'}
    assert validate_config({'LIVE_DANMAKU_OFFSET_MS':600001})[1]
    assert epoch('2026-10-26T00:00:00Z')==1792972800
    assert epoch('NaN') is None and epoch('bad') is None and epoch(None) is None
    stats={}
    out=list(project([event(),event(utc_ts=999),event(utc_ts=None,recv_ts=1002),event(utc_ts=None)],
        segment='part',anchor_utc=1000,mode='live_edge',platform='Twitch',offset_ms=100,stats=stats))
    assert [e.relative_ms for e in out]==[1100,-900,2100]
    assert stats['pre_start_count']==1 and stats['unmapped_count']==1
    assert stats['anchor_error_ms'] is None
    assert list(project([event()],segment='s',anchor_utc=None,mode='',platform=''))==[]
    replay=list(project([event(time_source='source_relative',relative_ms=800)],segment='s',anchor_utc=2000,
                        mode='catch_up',platform='YouTube',stats=stats))
    assert replay[0].relative_ms==800 and stats['anchor_source']=='programme_relative_unverified_head'
    assert not list(project([event(utc_ts=1e13)],segment='s',anchor_utc=0,mode='',platform=''))


def test_youtube_native_replay_paid_sticker_and_emoji():
    item={'id':'m','timestampUsec':'1001000000','authorExternalChannelId':'uid','authorName':{'simpleText':'name'},
          'message':{'runs':[{'text':'Hi'},{'emoji':{'shortcuts':[':wave:']}}]},'purchaseAmountText':{'simpleText':'$5'}}
    action={'replayChatItemAction':{'videoOffsetTimeMsec':'1234','actions':[
        {'addChatItemAction':{'item':{'liveChatTextMessageRenderer':item}}},
        {'liveChatPaidMessageRenderer':item},{'liveChatPaidStickerRenderer':item},{'liveChatMembershipItemRenderer':item}]}}
    result=list(messages(action,'room',1002))
    assert [e.kind for e in result]==['chat','superchat','gift','guard']
    assert result[0].text=='Hi:wave:' and result[0].relative_ms==1234
    assert result[0].utc_ts==1001 and result[0].time_source=='source_relative'
    assert list(messages({'liveChatTextMessageRenderer':{}},'room',1))==[]


def test_twitch_irc_tags_action_and_wrong_channel():
    assert unescape(r'a\sb\:c\\d\re\nf\q')=='a b;c\\d\re\nfq'
    line='@id=m;user-id=1;display-name=two\\swords;color=#123456;tmi-sent-ts=1001000 :u!u@host PRIVMSG #room :\x01ACTION waves\x01'
    e=parse_line(line,'room',1002)
    assert (e.text,e.user_name,e.color,e.utc_ts,e.message_id)==('waves','two words',0x123456,1001,'m')
    assert parse_line(line,'other',1) is None
    assert parse_line('PING :host','room',1) is None
    assert parse_line(':host ROOMSTATE #room','room',1) is None
    assert parse_line(':u!u@h PRIVMSG #room :hi','room',1).time_source=='receive'


def test_native_withny_trailing_comma_deleted_malformed_and_partial(tmp_path):
    rows=[{'streamUUID':'s','commentUUID':'a','content':'hello','createdAt':'2026-10-26T00:00:01Z'},
          {'commentUUID':'b','content':'paid','tipAmount':'10','createdAt':'bad'},
          {'commentUUID':'c','itemID':'gift','itemName':'flower'}, {'deletedAt':'now','content':'removed'},42,{}]
    path=tmp_path/'chat.json';path.write_text('[\n'+',\n'.join(json.dumps(r) for r in rows)+',\n]\n',encoding='utf-8')
    stats={};result=list(read_chat(path,'part',stats))
    assert len(result)==3 and result[1].kind=='superchat' and result[2].kind=='gift'
    assert result[0].utc_ts==1792972801 and stats['rejected_count']==2 and not stats['truncated']
    path.write_text('[{"content":"good"},{"partial":',encoding='utf-8')
    assert len(list(read_chat(path,'s',stats)))==1 and stats['truncated']
    path.write_text('['+'x'*1048577,encoding='utf-8')
    with pytest.raises(ValueError,match='oversized'):list(read_chat(path,'s',{}))


def test_twicas_event_shapes_and_timestamp_units():
    rows=[{'type':'comment','id':1,'message':'a','createdAt':1792972801000,'author':{'id':'u','name':'n'}},
          {'type':'gift','item':{'name':'flower'},'sender':{'screenName':'s'}},{'type':'other'},{'type':'comment'}]
    result=list(tc_events({'data':rows},'123',1792972802))
    assert result[0].utc_ts==1792972801 and result[1].time_source=='receive' and result[1].kind=='gift'
    assert len(result)==2 and list(tc_events('bad','123',1))==[]


def ndgr_message(id='m',stamp=1001,body='hello'):
    p=niconico.protocol();m=p.ChunkedMessage();m.meta.id=id;m.meta.at.seconds=stamp
    m.message.chat.content=body;m.message.chat.vpos=123;m.message.chat.raw_user_id=42
    return m


def framed(message):
    data=message.SerializeToString();n=len(data);header=bytearray()
    while n>127:header.append((n&127)|128);n>>=7
    return bytes(header+bytes([n]))+data


def test_ndgr_generated_protocol_and_stream_chunk_boundaries():
    m=ndgr_message();m.message.chat.modifier.full_color.r=255
    raw=framed(m)
    result=list(niconico.frames([raw[:1],raw[1:3],raw[3:]+raw],type(m)))
    assert len(result)==2
    e=niconico.normalize(result[0],'lv1',1002)
    assert e.relative_ms==1230 and e.user_id=='42' and e.color==0xFF0000
    assert niconico.normalize(type(m)(),'lv1',1) is None
    m.message.ClearField('chat');m.message.overflowed_chat.content='overflow'
    m.message.overflowed_chat.modifier.position=1
    assert niconico.normalize(m,'lv1',1).text=='overflow'
    for data,reason in [(b'\xff'*5,'varint'),(b'\x02x','truncated'),(b'\xff\xff\xff\x7f','oversized')]:
        with pytest.raises(ValueError,match=reason):list(niconico.frames([data],type(m)))
    parser=niconico.EmbeddedData();parser.feed('<script id="embedded-data" data-props="{&quot;x&quot;:1}"></script>')
    assert parser.value=={'x':1}


class OnePoll:
    def is_set(self):return False
    def wait(self,seconds):return True


def test_nicochannel_token_history_contract_auth_and_schema():
    t=Mock()
    video={'data':{'video_page':{'video_comment_setting':{'comment_group_id':'g'}}}}
    def response(url, **kwargs):
        if url.endswith('/site/settings.json'):
            return {'api_base_url':'https://nfc-api.nicochannel.jp/fc','fanclub_site_id':1}
        if url.endswith('/content_providers/channel_domain'):
            return {'data':{'content_providers':{'id':1}}}
        if url.endswith('/comments_user_token'):
            return {'data':{'access_token':'secret'}}
        if url.endswith('/messages.history'):
            return [{'id':'1','message':'good','sent_at':'2026-10-26T00:00:01Z'},{}]
        if url.endswith('/video_pages/sm1'):
            return video
        raise AssertionError(url)
    t.json.side_effect=response
    output=[];stats={'rejected_count':0}
    nicochannel.collect({'url':'https://nicochannel.jp/ch/live/sm1','command':['x','--username','jwt_token','--password','secret']},
                        t,OnePoll(),output.append,stats)
    assert len(output)==1 and stats['rejected_count']==1
    assert t.json.call_args.kwargs['params']=={'sort_direction':'desc','limit':120}
    page_call=next(c for c in t.json.call_args_list if c.args[0].endswith('/video_pages/sm1'))
    assert page_call.kwargs['headers']['Authorization']=='Bearer secret'
    video['data']['video_page']={}
    with pytest.raises(ValueError,match='disabled'):nicochannel.collect({'url':'https://nicochannel.jp/c/live/sm1','command':['x']},t,OnePoll(),output.append,{})


def test_irc_adapter_separate_handshake_ping_and_reconnect():
    t=Mock();ws=t.socket.return_value
    ws.recv.side_effect=['PING :tmi\r\n:id PRIVMSG #room :hello\r\n',':host RECONNECT\r\n']
    output=[]
    with pytest.raises(ConnectionError):sources.twitch({'url':'https://twitch.tv/room'},t,threading.Event(),output.append,{'rejected_count':0})
    assert len(output)==1 and ws.send.call_count==5
    assert ws.send.call_args.args[0]=='PONG :tmi\r\n'
    assert all(call.args[0].count('\r\n')==1 for call in ws.send.call_args_list)
    ws.close.assert_called_once()


def test_twicas_adapter_post_and_current_show_page():
    t=Mock();t.json.side_effect=[{'is_live':True},{'url':'wss://s1.twitcasting.tv/event.pubsub'}]
    t.text.return_value='<a class="tw-movie-thumbnail2" href="/room/movie/123">'
    ws=t.socket.return_value;ws.recv.side_effect=['[{"type":"comment","id":1,"message":"hi"}]','']
    output=[]
    with pytest.raises(ConnectionError):sources.twitcasting({'url':'https://twitcasting.tv/room'},t,threading.Event(),output.append,{'rejected_count':0})
    assert len(output)==1 and output[0].room_id=='123'
    assert t.json.call_args_list[0].kwargs['method']=='POST'
    ws.close.assert_called_once()


def test_transport_proxy_cookie_scope_bounds_and_domain_guards(tmp_path):
    assert option(['x','--proxy=first','--proxy','last'],'--proxy')=='last'
    for url in ['http://nicovideo.jp/x','https://nicovideo.jp.evil/x','https://u:p@nicovideo.jp/x','https://nicovideo.jp:444/x']:
        with pytest.raises(ValueError):remote_url(url,['nicovideo.jp'])
    assert remote_url('wss://sub.nicovideo.jp/x',['nicovideo.jp'],websocket=True)
    t=Transport(['x','--proxy',''])
    try:
        with patch.object(library('websocket'),'create_connection',return_value=Mock()) as create:
            t.socket('wss://example.com/a');assert create.call_args.kwargs['http_no_proxy']==['*']
        httpx=library('httpx')
        t.client.close();t.client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'ok':1})))
        assert t.json('https://example.com')=={'ok':1}
        assert 'ok' in t.text('https://example.com')
        with t.stream('https://example.com') as data:assert list(data)
        t.client.close();t.client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'x'*(8*1024*1024+1))))
        with pytest.raises(ValueError,match='oversized'):t.json('https://example.com')
    finally:t.close()


def test_worker_dedup_privacy_and_priority_backpressure(tmp_path):
    def collect(c,t,stop,emit,stats):
        for i in range(20):emit(event(message_id=str(i)))
        emit(event(message_id='gift',kind='gift'))
        emit(event(message_id='gift',kind='gift'))
    original_queue=queue.Queue
    with patch.dict(worker.SOURCES,{'Twitch':collect}),patch.object(worker,'Transport',return_value=Mock()),\
         patch.object(worker.queue,'Queue',side_effect=lambda size:original_queue(2 if size==49000 else 1)):
        assert worker.run({'root':str(tmp_path),'platform':'Twitch','command':['x'],'anonymize':True})==0
    report=json.loads((tmp_path/'capture-status.json').read_text())
    assert report['status']=='partial' and report['dropped_count']>0
    with CommentStore(tmp_path)as store:
        assert any(e.kind=='gift' for e in store.events())
        assert all(e.anonymized for e in store.events())
    assert '"user_id": "user"' not in (tmp_path/'events.jsonl').read_text()


@pytest.mark.parametrize('failure', [PermissionError('secret'),MissingDependency('secret')])
def test_worker_terminal_failure_contains_no_credentials(tmp_path,failure):
    with patch.dict(worker.SOURCES,{'YouTube':Mock(side_effect=failure)}):
        assert worker.run({'root':str(tmp_path),'platform':'YouTube','command':['x']})==1
    text=(tmp_path/'capture-status.json').read_text()
    assert 'unavailable' in text and 'secret' not in text


def test_worker_parent_death_and_retry_stop(tmp_path):
    def collect(c,t,stop,emit,stats):
        emit(event());stop.wait(2)
    with patch.dict(worker.SOURCES,{'YouTube':collect}),patch.object(worker,'_process_exists',return_value=False):
        worker.run({'root':str(tmp_path),'platform':'YouTube','command':['x'],'owner_pid':123})
    assert json.loads((tmp_path/'capture-status.json').read_text())['owner_interrupted']
    (tmp_path/'stop').touch()
    with patch.dict(worker.SOURCES,{'YouTube':Mock(side_effect=ConnectionError('signedURL'))}):
        worker.run({'root':str(tmp_path),'platform':'YouTube','command':['x']})
    assert json.loads((tmp_path/'capture-status.json').read_text())['reconnects']==1
    request=tmp_path/'bad.json';request.write_text(json.dumps({'root':str(tmp_path),'platform':'Twitch'}))
    with pytest.raises(ValueError):worker.main(request)


def test_capture_cookie_snapshot_exit_status_and_cleanup(tmp_path):
    session=LiveSession(tmp_path,'Twitch','live_edge','https://twitch.tv/room')
    cookie=tmp_path/'cookies.txt';cookie.write_text('secret')
    capture=CommentCapture(session,['x','--cookies',str(cookie)],{'LIVE_DANMAKU_ENABLED':1},force_kill=Mock())
    with patch('video_downloader.live.danmaku.capture.subprocess.Popen')as spawn:
        spawn.return_value.poll.return_value=0;capture.start()
        request=json.loads((capture.root/'request.json').read_text(encoding='utf-8'))
        assert request['owner_pid']==os.getpid() and request['command'][-1]!=str(cookie)
        (capture.root/'capture-status.json').write_text('{"status":"running"}')
        assert capture.finish()['status']=='partial'
    assert not (capture.root/'request.json').exists() and cookie.read_text()=='secret'
    assert not (capture.root/'cookies.private').exists()


def test_withny_managed_config_tracks_and_metadata_do_not_use_programme_start(tmp_path):
    config=tmp_path/'watch.yaml';config.write_text('credentialsFile: credentials.yaml\ndefaultParams:\n  writeChat: false\nchannels:\n  alice: {}\n  bob:\n    qualityConstraint:\n      audioOnly: true\n',encoding='utf-8')
    original=config.read_bytes();session=LiveSession(tmp_path/'jobs','Withny','live_edge','withny://configured')
    directory,_=session.part('withny-dl',[])
    engine=WithnyEngine(['x','watch','--config',str(config)],session,config,True)
    command=engine.command(directory)
    yaml=library('ruamel.yaml').YAML(typ='safe',pure=True);data=yaml.load(engine.private.read_text(encoding='utf-8'))
    assert data['channels']['alice']['writeChat'] and not data['channels']['bob']['concat']
    assert data['channels']['bob']['quality']['audioOnly'] is True
    assert 'qualityConstraint' not in data['channels']['bob']
    assert '.MetaData.Stream.UUID' in data['defaultParams']['outFormat']
    assert command[-1]==str(engine.private) and engine.cwd==tmp_path and config.read_bytes()==original
    folder=directory/'alice';folder.mkdir();ts=folder/'one.ts';ts.touch();mp4=folder/'one.mp4';mp4.touch()
    assert engine.output_files(session.media)==[mp4]
    assert engine.expected_tracks(directory/'bob'/'one.ts')=='a'
    assert engine.expected_tracks(mp4)=='av'
    mp4.with_suffix('.info.json').write_text('{"Stream":{"startedAt":"2020-01-01T00:00:00Z"}}')
    report={'files':[{'path':str(mp4)}]};engine.annotate(report)
    assert report['files'][0]['anchor_utc']>report['files'][0]['programme_started_at']
    engine.close();assert not engine.private.exists()


def test_reexport_finished_record_uses_frozen_privacy_and_offsets(tmp_path):
    session=LiveSession(tmp_path,'Twitch','live_edge','https://twitch.tv/room')
    directory,part=session.part('yt-dlp',[]);part['media_started_at']=1000
    media=directory/'video.mp4';media.write_bytes(b'unchanged')
    with CommentStore(session.root/'danmaku',anonymize=True)as store:store.append(event())
    session.data.update(comment_settings={'LIVE_DANMAKU_ENABLED':1,'LIVE_DANMAKU_ANONYMIZE':1},comment_capture={'status':'captured'})
    report={'files':[{'path':str(media),'duration':10,'streams':[]}],'conclusion':'complete'}
    session.finish('user',report)
    recordings=RecordingStore(tmp_path)
    result=recordings.export_comments(session.root.name,{'LIVE_DANMAKU_OFFSET_MS':1000,'LIVE_DANMAKU_FORMATS':'srt'})
    assert result['ok'] and result['comments']['status']=='partial'
    subtitle=library('pysubs2').load(str(media.with_suffix('.srt')),encoding='utf-8-sig')
    assert subtitle[0].start==2000 and 'name:' not in subtitle[0].text
    before=media.with_suffix('.srt').read_bytes()
    assert recordings.export_comments(session.root.name,{})['ok']
    assert media.with_suffix('.srt').read_bytes()==before and media.read_bytes()==b'unchanged'
    assert recordings.export_comments('../outside',{})['error']
    assert recordings.export_comments(session.root.name,{'LIVE_DANMAKU_ANONYMIZE':0})['error']
    assert recordings.export_comments(session.root.name,{'LIVE_DANMAKU_OFFSET_MS':999999})['error']
    report['files'][0]['path']=str(tmp_path/'outside.mp4')
    session.finish('user',report)
    assert recordings.export_comments(session.root.name,{})['error']


def test_recovery_removes_credential_snapshots_of_abandoned_jobs(tmp_path):
    session=LiveSession(tmp_path,'YouTube','live_edge','https://youtube.com/live/test')
    session.data['owner_pid']=-1;session.save()
    (session.root/'danmaku').mkdir();(session.root/'danmaku/request.json').write_text('secret')
    (session.root/'withny.private.yaml').write_text('secret')
    assert recover_interrupted(tmp_path)==1
    assert not (session.root/'danmaku/request.json').exists() and not (session.root/'withny.private.yaml').exists()


def test_ndgr_watch_handshake_forward_and_backward_streams():
    proto=niconico.protocol();stop=threading.Event();received=threading.Event();output=[]
    t=Mock();t.text.return_value='<script id="embedded-data" data-props="'+json.dumps({
        'program':{'nicoliveProgramId':'lv1'},'site':{'relive':{'webSocketUrl':'wss://a.nicovideo.jp/watch'}}}).replace('"','&quot;')+'"></script>'
    t.socket.return_value.recv.side_effect=['{"type":"ping"}',json.dumps({'type':'messageServer','data':{'viewUri':'https://a.nicovideo.jp/view'}})]
    back=proto.ChunkedEntry();back.backward.segment.uri='https://a.nicovideo.jp/back'
    entry=proto.ChunkedEntry();entry.segment.uri='https://a.nicovideo.jp/segment'
    previous=proto.ChunkedEntry();previous.previous.uri=entry.segment.uri
    next_=proto.ChunkedEntry();next_.next.at=123
    packed=proto.PackedSegment();packed.messages.append(ndgr_message('old',stamp=10))
    t.response.return_value=packed.SerializeToString()
    def emit(e):
        output.append(e)
        if len(output)>=2:received.set()
    @contextlib.contextmanager
    def stream(uri):
        if uri.split('?',1)[0].endswith('/view'):
            def chunks():
                yield b''.join(framed(e) for e in (back,entry,previous,next_))
                assert received.wait(3)
                stop.set()
            yield chunks()
        else:
            yield [framed(ndgr_message('live',stamp=1001))]
    t.stream.side_effect=stream
    niconico.collect({'url':'https://live.nicovideo.jp/watch/lv1'},t,stop,emit,{})
    assert {e.message_id for e in output}=={'old','live'}
    assert t.socket.return_value.send.call_count==2
    t.socket.return_value.close.assert_called_once()


@pytest.mark.parametrize('page,frames,error', [('',[],ValueError),
    ('<script id="embedded-data" data-props="{&quot;program&quot;:{&quot;nicoliveProgramId&quot;:&quot;lv1&quot;},&quot;site&quot;:{&quot;relive&quot;:{&quot;webSocketUrl&quot;:&quot;wss://a.nicovideo.jp/x&quot;}}}"></script>',
     ['{"type":"error"}'],PermissionError)])
def test_ndgr_unavailable_permissions_do_not_guess_endpoints(page,frames,error):
    t=Mock();t.text.return_value=page;t.socket.return_value.recv.side_effect=frames
    with pytest.raises(error):niconico.collect({'url':'https://live.nicovideo.jp/watch/lv1'},t,threading.Event(),Mock(),{})


def test_youtube_child_reads_jsonl_ignores_pretty_fragments_and_stops(tmp_path):
    root=tmp_path/'.source';root.mkdir()
    item={'liveChatTextMessageRenderer':{'id':'real','message':{'simpleText':'hello'},'timestampUsec':'1001000000'}}
    (root/'chat.live_chat.json.part').write_text(json.dumps(item)+'\n',encoding='utf-8')
    (root/'chat.live_chat.json.part-Frag1').write_text(json.dumps(item,indent=2),encoding='utf-8')
    stop=threading.Event();stop.set();output=[];stats={'rejected_count':0}
    child=Mock();child.poll.return_value=None
    with patch.object(sources.subprocess,'Popen',return_value=child),patch.object(sources.process,'stop')as finish:
        sources.youtube({'root':str(tmp_path),'url':'https://youtube.com/watch?v=PUBLIC&token=secret','command':['yt-dlp','--proxy','']},None,stop,output.append,stats)
    assert len(output)==1 and output[0].room_id=='PUBLIC' and not stats['truncated'] and not stats['rejected_count']
    finish.assert_called_once()


def test_youtube_missing_track_and_child_failure_are_explicit(tmp_path):
    stop=threading.Event();stop.set()
    child=Mock();child.poll.return_value=0
    with patch.object(sources.subprocess,'Popen',return_value=child):
        with pytest.raises(PermissionError):sources.youtube({'root':str(tmp_path),'url':'https://youtube.com/live/public','command':['x']},None,stop,Mock(),{})
    child.poll.return_value=1;child.returncode=1
    with patch.object(sources.subprocess,'Popen',return_value=child):
        with pytest.raises(RuntimeError):sources.youtube({'root':str(tmp_path),'url':'https://youtube.com/live/public','command':['x']},None,threading.Event(),Mock(),{})


def test_capture_forced_child_failure_does_not_touch_media(tmp_path):
    session=LiveSession(tmp_path,'Twitch','live_edge','https://twitch.tv/room')
    media=session.media/'one.ts';media.write_bytes(b'media')
    capture=CommentCapture(session,['x'],{'LIVE_DANMAKU_ENABLED':1},force_kill=Mock())
    with patch('video_downloader.live.danmaku.capture.subprocess.Popen')as spawn:
        capture.start();capture.proc.poll.return_value=None
        capture.proc.wait.side_effect=[subprocess.TimeoutExpired('worker',8),0]
        raw=capture.root/'.source';raw.mkdir();(raw/'raw.json').write_text('secret')
        result=capture.finish()
    assert result['status']=='partial' and result['forced_stop']
    assert not raw.exists() and media.read_bytes()==b'media'
    capture.force_kill.assert_called_once_with(spawn.return_value)


@pytest.mark.parametrize('content,reason', [('channels: {}','channels'),('channels: {"../escape": {}}','channel'),
    ('channels: {alice: {}}\ndefaultParams: [invalid]','defaults'),('channels: {alice: []}','params')])
def test_withny_invalid_configuration_is_rejected(tmp_path,content,reason):
    path=tmp_path/'watch.yaml';path.write_text(content)
    session=LiveSession(tmp_path/'jobs','Withny','live_edge','withny://channels')
    engine=WithnyEngine(['x','--config',str(path)],session,path,True)
    with pytest.raises(ValueError,match=reason):engine.command(session.media)


def test_withny_pipeline_keeps_native_facts_and_repeatable_offsets(tmp_path):
    session=LiveSession(tmp_path,'Withny','live_edge','withny://channels');directory,part=session.part('withny-dl',[])
    part['media_started_at']=1000;media=directory/'s.mp4';media.touch()
    media.with_suffix('.chat.json').write_text('[{"commentUUID":"id","streamUUID":"s","content":"hello","createdAt":1001},]')
    report={'files':[{'path':str(media),'duration':5,'streams':[]}]}
    first=process_comments(session,report,{'LIVE_DANMAKU_ENABLED':1})
    assert first['status']=='partial' and first['outputs']
    again=process_comments(session,report,{'LIVE_DANMAKU_ENABLED':1,'LIVE_DANMAKU_OFFSET_MS':1000})
    assert again['sources'][0]['duplicate_count']==1
    assert library('pysubs2').load(str(media.with_suffix('.srt')),encoding='utf-8-sig')[0].start==2000


def test_reexport_rejects_active_jobs_and_symlinks(tmp_path):
    session=LiveSession(tmp_path,'Twitch','live_edge','url')
    store=RecordingStore(tmp_path)
    session.data['comment_settings']={'LIVE_DANMAKU_ENABLED':1};session.save()
    report={'files':[],'conclusion':'failed'}
    from video_downloader.live.session import atomic_json
    atomic_json(session.root/'integrity-report.json',report)
    assert store.export_comments(session.root.name,{})['error']
    session.finish('user',report)
    store._export_lock.acquire()
    try:assert store.export_comments(session.root.name,{})['error']
    finally:store._export_lock.release()
    (session.root/'danmaku').mkdir()
    with patch.object(Path,'is_symlink',return_value=True):
        assert store.export_comments(session.root.name,{})['error']


def test_source_and_protocol_release_smoke():
    from video_downloader.live.danmaku.dependencies import self_check
    assert all(self_check().values())


def test_anonymous_identity_survives_complete_index_rebuild(tmp_path):
    with CommentStore(tmp_path,anonymize=True)as store:
        store.append(event());name=store.events()[0].user_name
    (tmp_path/'events.sqlite').unlink()
    with CommentStore(tmp_path,anonymize=True)as store:
        store.append(event(message_id='two',utc_ts=1002))
        assert {e.user_name for e in store.events()}=={name}
