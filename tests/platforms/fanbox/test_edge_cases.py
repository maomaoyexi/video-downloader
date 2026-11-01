from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import threading
from unittest.mock import patch

import httpx
import pytest

from video_downloader.platforms.fanbox import runtime
from video_downloader.platforms.fanbox.auth import load_credentials
from video_downloader.platforms.fanbox.client import FanboxClient
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.links import LinkCollector
from video_downloader.platforms.fanbox.options import normalize_options
from video_downloader.platforms.fanbox.parsers import parse_post
from video_downloader.platforms.fanbox.service import ScanService
from video_downloader.platforms.fanbox.transport import CurlTransport, HttpTransport, RequestGate, retry_after
from .test_content import image, post
from .test_scan import FakeTransport


def test_curl_adapter_has_tls_proxy_and_stream_boundaries(monkeypatch):
    settings=[]
    class NetworkError(Exception):pass
    class Session:
        def __init__(self,**kwargs):settings.append(kwargs);self.closed=False
        @contextmanager
        def stream(self,method,url,**kwargs):
            assert method=='GET' and kwargs['allow_redirects'] is False
            class Response:
                status_code=200;headers={'Content-Type':'application/json'}
                def iter_content(self,chunk_size):yield b'{"body":{"ok":true}}'
            yield Response()
        def close(self):self.closed=True
    class Library:
        exceptions=type('Exceptions',(),{'RequestException':NetworkError})
        CurlOpt=type('CurlOpt',(),{'NOPROXY':10177})
        @staticmethod
        def where():return 'test-ca-bundle'
    Library.Session=Session
    monkeypatch.setattr(runtime,'library',lambda name:Library)
    with CurlTransport(gate=RequestGate(0),user_agent='test') as transport:
        assert transport.get_json('https://api.fanbox.cc/creator.get')['body']['ok']
    assert settings[0]['verify'] and settings[0]['trust_env'] is False
    assert settings[0]['proxies']=={'all':''} and settings[0]['curl_options']=={10177:''}
    assert transport._client.session.closed
    with pytest.raises(FanboxError):CurlTransport(user_agent='bad\nheader')


def test_httpx_transport_network_challenge_json_and_close():
    def error(req):raise httpx.ConnectError('private credential URL')
    client=httpx.Client(transport=httpx.MockTransport(error))
    transport=HttpTransport(client=client,gate=RequestGate(0))
    with client,pytest.raises(FanboxError) as failure:transport.get_json('https://api.fanbox.cc/post.info')
    assert failure.value.code=='network_error' and 'private' not in str(failure.value)
    for status,body,headers,code in [
        (403,b'challenge',{'Content-Type':'text/html'},'challenge_required'),
        (200,b'not-json',{'Content-Type':'application/json'},'schema_changed'),
        (200,b'[]',{'Content-Type':'application/json'},'schema_changed'),
    ]:
        client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(status,content=body,headers=headers)))
        with client,pytest.raises(FanboxError) as failure:
            HttpTransport(client=client,gate=RequestGate(0)).get_json('https://api.fanbox.cc/post.info')
        assert failure.value.code==code
    with pytest.raises(FanboxError):HttpTransport(user_agent='bad\nheader')
    transport=HttpTransport(gate=RequestGate(0));transport.close()
    with pytest.raises(ValueError):transport.probe_resource('https://downloads.fanbox.cc/a',limit=0)


def test_cookie_limits_and_request_gate_cancel_while_waiting(tmp_path):
    path=tmp_path/'too-big.txt';path.write_bytes(b'x'*(2*1024*1024+1))
    with pytest.raises(FanboxError):load_credentials(path)
    with pytest.raises(ValueError):RequestGate(-1)
    gate=RequestGate(0);gate.defer(30);gate.cancel.set()
    with pytest.raises(FanboxError):
        with gate:pass
    future=format_datetime(datetime.now(timezone.utc)+timedelta(seconds=120))
    assert 100<retry_after(future)<=120
    assert retry_after('') is None


@pytest.mark.parametrize('change',[
    lambda p:p.update(publishedDatetime='invalid'),lambda p:p.update(id='bad'),
    lambda p:p.update(user='not-a-user'),lambda p:p.update(cover='bad'),
    lambda p:p.update(coverImageUrl=42),lambda p:p.update(body=[]),
])
def test_malformed_post_is_schema_error(change):
    value=post();change(value)
    with pytest.raises(FanboxError) as failure:parse_post(value)
    assert failure.value.code=='schema_changed'


def test_url_embeds_duplicate_images_and_partial_comments_resume():
    value=post('article',{'blocks':[{'type':'image','imageId':'a'},{'type':'image','imageId':'a'},
        {'type':'url_embed','urlEmbedId':'d'},{'type':'url_embed','urlEmbedId':'p'},
        {'type':'url_embed','urlEmbedId':'future'}], 'imageMap':{'a':image()},
        'urlEmbedMap':{'d':{'type':'default','url':'https://example.test/'},
                       'p':{'type':'fanbox.post','postInfo':{'creatorId':'sample','id':'2'}},
                       'future':{'type':'future'}}})
    parsed=parse_post(value)
    assert len(parsed.assets)==1 and len(parsed.links)==2 and parsed.assets[0].index==1
    for body in [{'blocks':[42]},{'blocks':[],'imageMap':[]},{'blocks':[{'type':'p','text':'x','links':[42]}]}]:
        with pytest.raises(FanboxError):parse_post(post('article',body))
    class T(FakeTransport):
        comments_fail=True
        def get_json(self,url):
            if 'post.getComments' not in url:return super().get_json(url)
            if self.comments_fail:raise FanboxError('network_error','network')
            return {'body':{'commentList':{'items':[{'id':'c1','body':'https://a.test/','replies':{'items':[{'id':'c2','body':'https://b.test/'}]}}],'nextUrl':None}}}
    value=post();value['commentCount']=1;transport=T([[value]]);service=ScanService(FanboxClient(transport))
    options={'content':{'comments':True}}
    first=service.scan('https://sample.fanbox.cc/',options)
    assert first['status']=='partial' and not first['posts'][0]['comments_complete']
    transport.comments_fail=False
    second=service.scan('https://sample.fanbox.cc/',options,checkpoint=first['checkpoint'])
    assert second['status']=='completed' and len(second['posts'][0]['links'])==2


def test_comments_malformed_cycles_and_unsafe_next():
    class T:
        value={}
        def get_json(self,url):return {'body':self.value}
    transport=T();client=FanboxClient(transport)
    for value in [{},{'commentList':{'items':42,'nextUrl':None}},{'commentList':{'items':[{}],'nextUrl':None}},
                  {'commentList':{'items':[],'nextUrl':42}}]:
        transport.value=value
        with pytest.raises(FanboxError):client.comments('1')
    transport.value={'commentList':{'items':[{'id':'1'}],'nextUrl':'https://127.0.0.1/private'}}
    with pytest.raises(FanboxError):client.comments('1')
    url='https://api.fanbox.cc/post.getComments?postId=1&offset=0&limit=50'
    transport.value={'commentList':{'items':[{'id':'1'}],'nextUrl':url}}
    assert client.comments('1')[2]=='comment_pagination_cycle'


def test_runtime_success_without_optional_modules_or_network(monkeypatch):
    class Session:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
    lib=type('Runtime',(),{'__version__':'test','Session':Session})
    monkeypatch.setattr(runtime,'library',lambda name:lib)
    assert runtime.health()=={'available':True,'version':'test'}


@pytest.mark.parametrize('valid', [True, False])
def test_timezone_fallback_without_system_iana_database(monkeypatch, valid):
    import zoneinfo
    from video_downloader.platforms.fanbox.options import normalize_options

    loaded = []
    calls = []
    def resolve(key):
        calls.append(key)
        if not loaded or not valid:
            raise zoneinfo.ZoneInfoNotFoundError(key)
        return object()

    monkeypatch.setattr(zoneinfo, 'ZoneInfo', resolve)
    monkeypatch.setattr(runtime, 'library', lambda name: loaded.append(name))
    if valid:
        assert normalize_options({'quota': {'timezone': 'Asia/Shanghai'}})['quota']['timezone'] == 'Asia/Shanghai'
    else:
        with pytest.raises(FanboxError) as failure:
            normalize_options({'quota': {'timezone': 'NoSuch/Zone'}})
        assert failure.value.code == 'invalid_config'
    assert loaded == ['tzdata']
    assert len(calls) == 2
