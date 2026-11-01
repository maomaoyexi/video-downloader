import threading

import httpx
import pytest

from video_downloader.platforms.fanbox.auth import load_credentials
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.transport import HttpTransport, RequestGate, retry_after
from video_downloader.platforms.fanbox.urls import parse_source, validate_api_url, validate_resource_url


@pytest.mark.parametrize('url', ['https://alice.fanbox.cc/', 'https://www.fanbox.cc/@alice/posts?utm_source=x'])
def test_canonical_creator(url):
    assert parse_source(url).url == 'https://www.fanbox.cc/@alice'


def test_post_and_source_boundaries():
    assert parse_source('https://alice.fanbox.cc/posts/123').post_id == '123'
    for url in ['https://fanbox.cc.evil.test/@alice', 'https://api.fanbox.cc/',
                'https://a.b.fanbox.cc/', 'https://user:secret@alice.fanbox.cc/',
                'https://alice.fanbox.cc:8888/', 'https://www.fanbox.cc/@alice/shop']:
        with pytest.raises(FanboxError): parse_source(url)


def test_api_and_resource_boundaries():
    assert validate_api_url('https://api.fanbox.cc/post.info?postId=1')
    for url in ['http://api.fanbox.cc/post.info', 'https://evil.test/post.info',
                'https://api.fanbox.cc/post.delete', 'https://api.fanbox.cc/post.info#x']:
        with pytest.raises(FanboxError): validate_api_url(url)
    assert validate_resource_url('https://downloads.fanbox.cc/images/post/1/a.png')
    with pytest.raises(FanboxError): validate_resource_url('https://127.0.0.1/file')


def test_cookie_scope_expiry_and_repr(tmp_path):
    file = tmp_path/'cookies.txt'
    file.write_text('# Netscape HTTP Cookie File\n'
                    '.fanbox.cc\tTRUE\t/\tTRUE\t0\tFANBOXSESSID\tprivate-value\n'
                    '.evil.test\tTRUE\t/\tTRUE\t0\tother\tprivate-other\n'
                    '.fanbox.cc\tTRUE\t/\tTRUE\t1\texpired\tprivate-expired\n', encoding='utf-8')
    credentials = load_credentials(file)
    assert credentials.has_session and len(credentials.jar) == 1
    assert 'private' not in repr(credentials)
    assert not load_credentials().has_session
    with pytest.raises(FanboxError): load_credentials(tmp_path/'missing')


def transport_response(status=200, content=None, headers=None):
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(
        status, json={'body': {'ok': True}} if content is None else None,
        content=content, headers=headers)))
    return HttpTransport(client=client, gate=RequestGate(0)), client


@pytest.mark.parametrize('status,code', [(401,'access_denied'),(403,'access_denied'),
    (404,'not_found'),(429,'rate_limited'),(302,'unexpected_redirect'),(500,'server_error'),(418,'http_error')])
def test_http_errors_are_safe(status, code):
    transport, client = transport_response(status, b'secret-body')
    with client, pytest.raises(FanboxError) as error:
        transport.get_json('https://api.fanbox.cc/post.info?postId=1&secret=not-logged')
    assert error.value.code == code
    assert 'secret' not in str(error.value)


def test_json_challenge_size_and_resource_prefix():
    transport, client = transport_response()
    with client: assert transport.get_json('https://api.fanbox.cc/creator.get')['body']['ok']
    transport, client = transport_response(content=b'<html>challenge</html>',headers={'Content-Type':'text/html'})
    with client, pytest.raises(FanboxError, match='JSON'):
        transport.get_json('https://api.fanbox.cc/creator.get')
    transport, client = transport_response(content=b'x'*100,headers={'Content-Type':'application/json'})
    transport._limit=10
    with client, pytest.raises(FanboxError) as error: transport.get_json('https://api.fanbox.cc/creator.get')
    assert error.value.code == 'response_too_large'
    transport, client = transport_response(content=b'12345678',headers={'Content-Type':'image/png'})
    with client: assert transport.probe_resource('https://downloads.fanbox.cc/a',limit=4)['bytes_read']==4


def test_cancel_and_retry_after():
    cancel=threading.Event();cancel.set()
    with pytest.raises(FanboxError):
        with RequestGate(0,cancel): pass
    assert retry_after('1.5') == 1.5
    assert retry_after('nan') is None
    assert retry_after('not-a-date') is None
