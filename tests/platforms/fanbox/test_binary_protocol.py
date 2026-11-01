from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading

import pytest

from video_downloader.platforms.fanbox import binary
from video_downloader.platforms.fanbox.downloader import resource_key
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.naming import confined
from video_downloader.platforms.fanbox.service import write_json
from .test_archive_io import DATA,DATE,setup_io


@contextmanager
def server(payload,status=200,extra=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            self.send_response(status)
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('ETag','"version-1"')
            for key,value in (extra or {}).items():self.send_header(key,value)
            self.end_headers()
            try:self.wfile.write(payload)
            except (OSError,ConnectionError):pass
    instance=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=instance.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{instance.server_port}/file'
    finally:instance.shutdown();instance.server_close();thread.join()


def test_real_curl_callbacks_have_backpressure_and_metering(monkeypatch):
    monkeypatch.setattr(binary,'validate_resource_url',lambda url:url)
    data=DATA*10000
    chunks=[];headers=[];meter=[];thread=threading.get_ident()
    with server(data) as url:
        binary.BinaryTransport().transfer(url,{},lambda code,value:headers.append((code,value)),
            lambda chunk:chunks.append((threading.get_ident(),chunk)),meter=meter.append)
    assert b''.join(value for _,value in chunks)==data
    assert all(identity==thread for identity,_ in chunks)
    assert sum(meter)==len(data) and headers[0][0]==200
    assert max(len(value) for _,value in chunks)<=65536


@pytest.mark.parametrize('status,extra,code',[
    (302,{'Location':'http://127.0.0.1/private'},'unexpected_redirect'),
    (403,{'Content-Type':'text/html'},'challenge_required'),
    (404,{},'not_found'),(500,{},'server_error'),
    (429,{'Retry-After':'0'},'rate_limited'),
])
def test_real_error_responses_cannot_be_promoted(tmp_path,monkeypatch,status,extra,code):
    monkeypatch.setattr(binary,'validate_resource_url',lambda url:url)
    downloader,model,asset,options=setup_io(tmp_path,binary.BinaryTransport())
    with server(DATA,status,extra) as url:
        asset.url=url
        with pytest.raises(FanboxError) as failure:downloader.download(model,asset,options,DATE)
    assert failure.value.code==code
    assert downloader.repository.asset(resource_key(model,asset)).get('status')!='completed'


def test_real_range_resume_and_zero_length_file(tmp_path,monkeypatch):
    monkeypatch.setattr(binary,'validate_resource_url',lambda url:url)
    downloader,model,asset,options=setup_io(tmp_path,binary.BinaryTransport())
    with server(DATA[10:],206,{'Content-Range':f'bytes 10-{len(DATA)-1}/{len(DATA)}'}) as url:
        asset.url=url
        key=resource_key(model,asset)
        part=confined(tmp_path,f'.fanbox/parts/{key}.part',create=True);part.write_bytes(DATA[:10])
        write_json(part.with_suffix('.json'),{'key':key,'etag':'"version-1"','total':len(DATA)})
        result=downloader.download(model,asset,options,DATE)
    assert (tmp_path/result['path']).read_bytes()==DATA
    with server(b'') as url:
        asset.url=url;asset.id='empty';asset.size=0
        result=downloader.download(model,asset,options,DATE)
    assert result['size']==0 and (tmp_path/result['path']).read_bytes()==b''


def test_callback_failure_is_preserved_without_secret_error_body(monkeypatch):
    monkeypatch.setattr(binary,'validate_resource_url',lambda url:url)
    def fail(*_):raise FanboxError('cancelled','cancelled')
    with server(DATA) as url:
        with pytest.raises(FanboxError) as error:binary.BinaryTransport().transfer(url,{},lambda *a:None,fail)
    assert error.value.code=='cancelled'


def test_native_maximum_rejects_larger_resource(monkeypatch):
    monkeypatch.setattr(binary,'validate_resource_url',lambda url:url)
    with server(DATA) as url:
        with pytest.raises(FanboxError) as error:
            binary.BinaryTransport().transfer(url,{},lambda *a:None,lambda *a:None,maximum=1)
    assert error.value.code=='quota_exceeded'
