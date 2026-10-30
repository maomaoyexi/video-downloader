"""Receive-only RPlay IVS contracts; all credentials/messages are synthetic."""

import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from video_downloader.live.danmaku import rplay
from video_downloader.live.danmaku.preferences import enabled
from video_downloader.live.danmaku.store import CommentStore
from video_downloader.live.danmaku.timeline import project

ROOM='a'*24
URL='https://rplay.live/live/'+ROOM
CHAT='wss://edge.ivschat.us-east-1.amazonaws.com'


def message(**changes):
    return dict(Type='MESSAGE',Id='SYNTHETIC_ID',Content='{"m":"hello 世界"}',
                Sender={'UserId':'TEST_USER','Attributes':{'nickname':'测试昵称'}},
                SendTime='2026-10-29T10:00:01Z',**changes)


def test_message_timestamps_identity_and_projection_remain_distinct(tmp_path):
    event=list(rplay.events(message(),ROOM,1793268002))[0]
    assert event.text=='hello 世界' and event.user_name=='测试昵称'
    assert event.utc_ts==1793268001 and event.recv_ts==1793268002 and event.time_source=='server'
    assert event.source=='rplay_ivs'
    with CommentStore(tmp_path,anonymize=True) as store:
        assert store.append(event) is True
        assert store.append(event) is False
        store.sync()
        assert 'TEST_USER' not in store.path.read_text(encoding='utf8')
    projected=list(project([event],segment='media/part1.mkv',anchor_utc=1793268000,
                           mode='live_edge',platform='Rplay'))
    assert projected[0].relative_ms==1000 and projected[0].time_source=='server'
    assert enabled({'LIVE_DANMAKU_ENABLED':1},'Rplay')


@pytest.mark.parametrize('content', ['plain text','"json scalar"','{"m":"json text"}'])
def test_content_can_be_text_or_rplay_json(content):
    payload=message()
    payload['Content']=content
    assert len(list(rplay.events(payload,ROOM,1000)))==1


@pytest.mark.parametrize('payload', [None,[],{}, {'Type':'MESSAGE','Content':None},
    {'Type':'MESSAGE','Content':'{}'}, {'Type':'MESSAGE','Content':' '},
    {'Type':'MESSAGE','Content':'x'*10001}, {'Type':'EVENT','EventName':'unknown'}])
def test_invalid_or_unrelated_events_are_ignored(payload):
    assert list(rplay.events(payload,ROOM,1000))==[]


def test_gift_has_no_invented_nickname_or_timestamp():
    payload={'Type':'EVENT','EventName':'donation','Id':'gift',
             'Attributes':{'content':'TEST gift','userId':'SYNTHETIC'}}
    event=list(rplay.events(payload,ROOM,1000))[0]
    assert event.kind=='gift' and event.placement=='top'
    assert event.utc_ts is None and event.time_source=='receive' and not event.user_name


def setup(monkeypatch,frames=None,live=None):
    stop=threading.Event()
    context=Mock()
    context.credential.return_value={'user_oid':'b'*24,'login_type':'rplay','access_token':'TEST_ACCESS'}
    support=SimpleNamespace(AuthContext=Mock(return_value=context),AuthError=ValueError)
    monkeypatch.setattr(rplay,'auth_support',lambda:support)
    transport=Mock()
    responses=[live or {'accessible':True,'chatUrl':CHAT+'\t '},{'token':'TEST_CHAT'}]
    transport.json.side_effect=responses
    ws=transport.socket.return_value
    frames=iter(frames or [json.dumps(message())])
    def receive():
        try:
            result=next(frames)
        except StopIteration:
            stop.set()
            return json.dumps({'Type':'NOTICE'})
        if isinstance(result,Exception):
            raise result
        return result
    ws.recv.side_effect=receive
    options={'url':URL,'command':['yt-dlp','--extractor-args','Rplay:auth=firefox;auth_dir=TEST_DIR']}
    return options,transport,stop,support,context


def test_collect_uses_single_use_subprotocol_only_and_never_sends(monkeypatch):
    options,transport,stop,support,context=setup(monkeypatch)
    output=[]
    stats={'rejected_count':0}
    rplay.collect(options,transport,stop,output.append,stats)
    assert len(output)==1 and stats['connected_at']>0
    transport.socket.assert_called_once_with(CHAT,origin='https://rplay.live',subprotocols=['TEST_CHAT'])
    transport.socket.return_value.send.assert_not_called()
    transport.socket.return_value.close.assert_called_once()
    for call in transport.json.call_args_list:
        assert call.kwargs['follow_redirects'] is False
        assert call.args[0].startswith('https://api.rplay.live/')
    refresh=support.AuthContext.call_args.args[1]
    transport.json.side_effect=None
    refresh('b'*24,'TEST_REFRESH')
    assert transport.json.call_args.kwargs['headers']['refresh-token']=='TEST_REFRESH'


@pytest.mark.parametrize('address', ['wss://evil.example','ws://edge.ivschat.us-east-1.amazonaws.com',
    CHAT+'/extra',CHAT+'?token=SECRET',CHAT+':bad',CHAT+'/\ninside','wss://user@edge.ivschat.us-east-1.amazonaws.com'])
def test_unknown_chat_endpoints_do_not_receive_tokens(address,monkeypatch):
    options,transport,stop,*_=setup(monkeypatch,live={'accessible':True,'chatUrl':address})
    with pytest.raises((PermissionError,ValueError)):
        rplay.collect(options,transport,stop,Mock(),{'rejected_count':0})
    transport.socket.assert_not_called()
    assert transport.json.call_count==1


@pytest.mark.parametrize('failure', [False,'no-token','auth'])
def test_access_and_missing_auth_fail_before_socket(failure,monkeypatch):
    options,transport,stop,support,context=setup(monkeypatch)
    if failure is False:
        transport.json.side_effect=[{'accessible':False}]
    elif failure=='no-token':
        transport.json.side_effect=[{'accessible':True,'chatUrl':CHAT},{}]
    else:
        context.credential.side_effect=ValueError('SYNTHETIC_SECRET')
    with pytest.raises(PermissionError):
        rplay.collect(options,transport,stop,Mock(),{})
    transport.socket.assert_not_called()
    options['command']=['yt-dlp']
    with pytest.raises(PermissionError):
        rplay.collect(options,transport,stop,Mock(),{})


def test_401_renews_once_and_reconnect_fetches_new_chat_token(monkeypatch):
    options,transport,stop,support,context=setup(monkeypatch)
    error=RuntimeError('SYNTHETIC')
    error.response=SimpleNamespace(status_code=401)
    transport.json.side_effect=[error,{'accessible':True,'chatUrl':CHAT},{'token':'FIRST'},
                               {'accessible':True,'chatUrl':CHAT},{'token':'SECOND'}]
    rplay.collect(options,transport,stop,Mock(),{'rejected_count':0})
    assert context.credential.call_args_list[1].kwargs=={'rejected_token':'TEST_ACCESS'}
    stop.clear()
    rplay.collect(options,transport,stop,Mock(),{'rejected_count':0})
    assert [call.kwargs['subprotocols'] for call in transport.socket.call_args_list]==[['FIRST'],['SECOND']]


@pytest.mark.parametrize('frame', ['',json.dumps({'Type':'DISCONNECT'}),ConnectionError('synthetic')])
def test_disconnect_marks_possible_gap_and_closes_socket(frame,monkeypatch):
    options,transport,stop,*_=setup(monkeypatch,frames=[frame])
    stats={'rejected_count':0}
    with pytest.raises(ConnectionError):
        rplay.collect(options,transport,stop,Mock(),stats)
    assert stats['possible_gap'] is True
    transport.socket.return_value.close.assert_called_once()


def test_malformed_and_oversized_frames_are_bounded_and_timeouts_are_not_disconnects(monkeypatch):
    options,transport,stop,*_=setup(monkeypatch,frames=[TimeoutError(),'bad','x'*(1024*1024+1),json.dumps(message())])
    output=[]
    stats={'rejected_count':0}
    rplay.collect(options,transport,stop,output.append,stats)
    assert len(output)==1 and stats['rejected_count']==2 and not stats.get('possible_gap')
