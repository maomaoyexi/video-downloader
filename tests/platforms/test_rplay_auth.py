"""Synthetic account data only; never read the developer's browser in tests."""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import struct
import time
from unittest import mock

import pytest

from video_downloader.platforms.rplay import auth_support, auth_arguments, AuthWorkspace, command_auth_options
from video_downloader.core.paths import AppPaths
from video_downloader.core.validation import validate_config

auth = auth_support()


def jwt(expiry):
    payload = base64.urlsafe_b64encode(json.dumps({'exp': expiry}).encode()).decode().rstrip('=')
    return 'eyJTEST.' + payload + '.TEST_SIGNATURE'


def credential(expiry=90):
    return {'user_oid': 'a'*24, 'access_token': jwt(expiry), 'refresh_token': 'TEST_REFRESH', 'login_type': 'rplay'}


def literal(data):
    length, prefix = len(data), bytearray()
    value = length
    while value > 127:
        prefix.append((value & 127) | 128)
        value >>= 7
    prefix.append(value)
    if length <= 60:
        return bytes(prefix) + bytes([(length - 1) << 2]) + data if data else b'\0'
    encoded = (length-1).to_bytes(((length-1).bit_length()+7)//8, 'little')
    return bytes(prefix) + bytes([(59 + len(encoded)) << 2]) + encoded + data


def tag(number, data=0):
    return struct.pack('<II', data, number)


def clone(value):
    if value is None:
        return tag(0xFFFF0000)
    if isinstance(value, bool):
        return tag(0xFFFF0002, int(value))
    if isinstance(value, int):
        return tag(0xFFFF0003, value & 0xffffffff)
    if isinstance(value, float):
        return struct.pack('<d', value)
    if isinstance(value, str):
        data = value.encode('utf-16le')
        return tag(0xFFFF0004, len(data)//2) + data + b'\0' * (-len(data) % 8)
    return tag(0xFFFF0008) + b''.join(clone(k)+clone(v) for k,v in value.items()) + tag(0xFFFF0013)


def compressed_record(value):
    return literal(tag(0xFFF10000, 3) + clone(value))


@pytest.mark.parametrize('size', [0, 1, 60, 61, 255, 256, 1024, 70000])
def test_snappy_literals_and_independent_roundtrip(size):
    value = (b'bounded session data' * (size//20+1))[:size]
    assert auth.decompress_session(literal(value)) == value


@pytest.mark.parametrize('compressed,expected', [
    (b'\x07\x08xab\x01\x02', b'xababab'),
    (b'\x07\x08xab\x0e\x02\0', b'xababab'),
    (b'\x07\x08xab\x0f\x02\0\0\0', b'xababab'),
])
def test_snappy_all_copy_offsets_with_overlap(compressed, expected):
    assert auth.decompress_session(compressed) == expected


@pytest.mark.parametrize('raw', [b'', b'\x80'*5, b'\xff\xff\xff\xff\x0f', b'\x05\x01\0', b'\x05\x10ab', b'\x01\x04ab'])
def test_snappy_rejects_truncation_and_oversized_allocations(raw):
    with pytest.raises(auth.AuthError):
        auth.decompress_session(raw)


def test_clone_primitives_unicode_and_bad_tags():
    record = {'text': '登录测试', 'bool': True, 'empty': None, 'signed': -7, 'float': 1.5, 'nested': {'token': 'TEST'}}
    assert auth.decode_clone(compressed_record(record)) == record
    latin = tag(0xFFF10000,3)+tag(0xFFFF0008)+tag(0xFFFF0004,0x80000001)+b'x'+b'\0'*7+clone('value')+tag(0xFFFF0013)
    assert auth.decode_clone(literal(latin)) == {'x':'value'}
    for raw in [literal(b'bad'), literal(tag(0xFFF10000,3)+tag(0xFFFF8022)), literal(tag(0xFFF10000,3)+clone('not-an-object'))]:
        with pytest.raises(auth.AuthError):
            auth.decode_clone(raw)


def test_firefox_reader_uses_only_rplay_session_and_includes_wal(tmp_path):
    profile = tmp_path/'Profiles/default'
    origin = profile/'storage/default/https+++rplay.live/idb'
    origin.mkdir(parents=True)
    db = origin/'session.sqlite'
    connection = sqlite3.connect(db)
    try:
        connection.executescript('PRAGMA journal_mode=WAL; CREATE TABLE database(name); INSERT INTO database VALUES("rplay-account-session"); CREATE TABLE object_store(id,name); INSERT INTO object_store VALUES(1,"records"); CREATE TABLE object_data(object_store_id,key,data);')
        session = {'user': {'oid':'a'*24}, 'token': jwt(1000), 'refreshToken':'TEST_REFRESH', 'loginType':'rplay'}
        connection.execute('INSERT INTO object_data VALUES(1,?,?)', (bytes.fromhex('30746674746a706f'), compressed_record({'session':session})))
        connection.commit()
        before = db.read_bytes()
        with mock.patch('yt_dlp.cookies._firefox_browser_dirs', return_value=[str(profile.parent),str(tmp_path/'missing')]):
            actual = auth.read_firefox_session()
        assert actual == credential(1000)
        assert db.read_bytes() == before
        with mock.patch('yt_dlp.cookies._firefox_browser_dirs', return_value=[]):
            with pytest.raises(auth.AuthError, match='login_required'):
                auth.read_firefox_session()
    finally:
        connection.close()


@pytest.mark.parametrize('expiry', [None, True, '123', float('inf'), float('nan')])
def test_invalid_token_expiration_is_not_accepted(expiry):
    with pytest.raises(auth.AuthError):
        auth.token_expiry(jwt(expiry))
    with pytest.raises(auth.AuthError):
        auth.token_expiry('invalid')


def fake_protection(value, *, decrypt=False):
    return base64.b64decode(value[4:]) if decrypt else b'ENC:' + base64.b64encode(value)


def test_refresh_is_serial_across_independent_contexts_and_rejected_token_is_renewed(tmp_path):
    refresh = mock.Mock(side_effect=lambda *_: {'accessToken': jwt(1000), 'refreshToken':'ROTATED_TEST_REFRESH'})
    def get():
        context = auth.AuthContext(tmp_path, refresh, reader=lambda _:credential(), clock=lambda:100, protection=fake_protection)
        return context.credential()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _:get(),range(4)))
    assert len(results) == 4 and refresh.call_count == 1
    assert all(value['refresh_token'] == 'ROTATED_TEST_REFRESH' for value in results)
    context = auth.AuthContext(tmp_path, refresh, reader=lambda _:credential(), clock=lambda:100, protection=fake_protection)
    context.credential(rejected_token=jwt(1000))
    assert refresh.call_args.args[1] == 'ROTATED_TEST_REFRESH'
    assert refresh.call_count == 2
    assert not list(tmp_path.glob('.auth-*'))


def test_fresh_browser_session_wins_over_cached_old_tokens(tmp_path):
    refresh = mock.Mock(return_value={'accessToken':jwt(1000)})
    auth.AuthContext(tmp_path,refresh,reader=lambda _:credential(),clock=lambda:100,protection=fake_protection).credential()
    fresh = auth.AuthContext(tmp_path,refresh,reader=lambda _:credential(2000),clock=lambda:100,protection=fake_protection).credential()
    assert fresh['access_token'] == jwt(2000) and refresh.call_count == 1


@pytest.mark.parametrize('change,code', [({'user_oid':'bad'},'identity'),({'login_type':'unknown'},'login_type'),({'refresh_token':None},'expired')])
def test_bad_credential_sources_never_refresh(tmp_path, change, code):
    source = dict(credential(), **change)
    refresh = mock.Mock()
    with pytest.raises(auth.AuthError, match=code):
        auth.AuthContext(tmp_path,refresh,reader=lambda _:source,clock=lambda:100,protection=fake_protection).credential()
    refresh.assert_not_called()


def test_bad_refresh_or_protection_failure_never_leaves_plaintext(tmp_path):
    for response in [{}, {'accessToken':jwt(90)}, {'accessToken':'invalid'}]:
        with pytest.raises(auth.AuthError):
            auth.AuthContext(tmp_path,lambda *_:response,reader=lambda _:credential(),clock=lambda:100,protection=fake_protection).credential()
    with pytest.raises(auth.AuthError):
        auth.AuthContext(tmp_path,lambda *_:{'accessToken':jwt(1000)},reader=lambda _:credential(),clock=lambda:100,
                         protection=lambda *_:(_ for _ in ()).throw(auth.AuthError('failed'))).credential()
    assert not list(tmp_path.glob('*.dpapi')) and not list(tmp_path.glob('.auth-*'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI')
def test_actual_dpapi_roundtrip_does_not_store_plaintext():
    plain = b'RPLAY_SYNTHETIC_TEST_SECRET'
    encrypted = auth.protect(plain)
    assert plain not in encrypted and auth.protect(encrypted,decrypt=True) == plain


def test_settings_roundtrip_arguments_and_workspace_cleanup(tmp_path):
    config, errors = validate_config({'RPLAY_AUTH_SOURCE':'firefox','RPLAY_FIREFOX_PROFILE':r'C:\Firefox Profile;A,B'})
    assert not errors
    workspace = AuthWorkspace(AppPaths(tmp_path))
    assert workspace.directory({'RPLAY_AUTH_SOURCE':'none'}) is None
    directory = workspace.directory(config)
    command = ['yt-dlp',*auth_arguments(config,directory),'https://rplay.live/live/'+'a'*24]
    values = command_auth_options(command)
    assert values['profile'] == config['RPLAY_FIREFOX_PROFILE'] and Path(values['auth_dir']) == directory
    assert auth_arguments({'RPLAY_AUTH_SOURCE':'none'},None) == []
    workspace.close()
    assert not directory.exists()
    for values in [{'RPLAY_AUTH_SOURCE':'chrome'},{'RPLAY_FIREFOX_PROFILE':'x\ny'}]:
        assert validate_config(values)[1]


def test_clone_reference_date_arrays_and_corrupt_records():
    header = tag(0xFFF10000,3)
    date = tag(0xFFFF0005)+struct.pack('<d',1234.5)
    raw = header+tag(0xFFFF0008)+clone('date')+date+clone('same')+tag(0xFFFF000D,1)+tag(0xFFFF0013)
    assert auth.decode_clone(literal(raw)) == {'date':1234.5,'same':1234.5}
    raw = header+tag(0xFFFF0007)+clone(0)+clone('item')+tag(0xFFFF0013)
    assert auth.decode_clone(literal(raw)) == {0:'item'}
    invalid = [header+tag(0xFFFF0008)+clone(None)+clone(1)+tag(0xFFFF0013),
               header+tag(0xFFFF0008)+tag(0xFFFF0004,0x7fffffff),
               header+tag(0xFFFF0008)+clone('key'),
               header+clone({})+b'extra']
    for raw in invalid:
        with pytest.raises(auth.AuthError):
            auth.decode_clone(literal(raw))
    value = {}
    for _ in range(70):
        value={'nested':value}
    with pytest.raises(auth.AuthError, match='complex'):
        auth.decode_clone(compressed_record(value))


def test_account_lock_timeout_is_bounded(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows locking branch')
    import msvcrt
    with mock.patch.object(msvcrt,'locking',side_effect=OSError), \
         mock.patch.object(auth.time,'monotonic',side_effect=[0,31]):
        with pytest.raises(auth.AuthError,match='lock_timeout'):
            with auth.account_lock(tmp_path):
                pytest.fail('lock must not be entered')


def test_protected_api_requests_disable_redirects_and_close_network_director():
    from urllib.request import HTTPRedirectHandler
    from yt_dlp.networking._urllib import UrllibRH
    from yt_dlp.utils import ExtractorError
    import io
    downloader=mock.MagicMock()
    director=downloader.build_request_director.return_value
    director.send.return_value.__enter__.return_value=io.BytesIO(b'{"ok":true}')
    assert auth.protected_json(downloader,'https://api.rplay.live/live/play',query={'creatorOid':'TEST'}) == {'ok':True}
    handler_type=downloader.build_request_director.call_args.args[0][0]
    redirect=HTTPRedirectHandler()
    with mock.patch.object(UrllibRH,'_create_instance',return_value=mock.Mock(handlers=[redirect])):
        handler_type(logger=mock.Mock())._create_instance()
    assert redirect.redirect_request(None,None,302,'',{},'https://evil.example') is None
    director.close.assert_called_once()
    assert director.send.call_args.args[0].url.endswith('?creatorOid=TEST')
    for value in [b'not json', b'x'*(8*1024*1024+1)]:
        director.send.return_value.__enter__.return_value=io.BytesIO(value)
        with pytest.raises((auth.AuthError,ExtractorError)):
            auth.protected_json(downloader,'https://api.rplay.live/content')
    for endpoint in ['http://api.rplay.live/content','https://evil.example/content','https://user@api.rplay.live/content']:
        with pytest.raises(auth.AuthError):
            auth.protected_json(downloader,endpoint)


def test_protected_api_http_and_transport_failures_retain_only_safe_message():
    import io
    from yt_dlp.networking.common import Response
    from yt_dlp.networking.exceptions import HTTPError, TransportError
    from yt_dlp.utils import ExtractorError
    downloader=mock.Mock()
    director=downloader.build_request_director.return_value
    response=Response(io.BytesIO(b'SECRET'),'https://api.rplay.live/x?token=SECRET',{},401)
    for error in [HTTPError(response),TransportError('SECRET')]:
        director.send.side_effect=error
        with pytest.raises(ExtractorError) as captured:
            auth.protected_json(downloader,'https://api.rplay.live/live/play')
        assert 'SECRET' not in str(captured.value)
    assert director.close.call_count == 2


@pytest.mark.skipif(os.name!='nt',reason='Windows cross-process DPAPI')
def test_actual_processes_share_one_encrypted_refresh_result(tmp_path):
    import subprocess
    import sys
    from tests.helpers import PROJECT_ROOT
    script=r'''
import sys,time,json
from pathlib import Path
from video_downloader.platforms.rplay import auth_support
support=auth_support()
source=json.loads(sys.argv[2])
def refresh(*args):
    with (Path(sys.argv[1])/'refresh-count').open('ab') as output: output.write(b'1')
    time.sleep(.1)
    return {'accessToken':sys.argv[3],'refreshToken':'SYNTHETIC_ROTATION'}
context=support.AuthContext(sys.argv[1],refresh,reader=lambda _:source,clock=lambda:100)
assert context.credential()['access_token']==sys.argv[3]
'''
    command=[sys.executable,'-B','-c',script,str(tmp_path),json.dumps(credential()),jwt(1000)]
    processes=[subprocess.Popen(command,cwd=PROJECT_ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(4)]
    try:
        for process in processes:
            out,err=process.communicate(timeout=20)
            assert process.returncode==0,err.decode('utf8','replace')
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    assert (tmp_path/'refresh-count').read_bytes()==b'1'
    cache=next(tmp_path.glob('*.dpapi')).read_bytes()
    assert b'SYNTHETIC_ROTATION' not in cache and jwt(1000).encode() not in cache
