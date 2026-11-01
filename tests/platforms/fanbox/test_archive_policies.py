from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import threading

import pytest

from video_downloader.platforms.fanbox import download_cli
from video_downloader.platforms.fanbox.archive import ArchiveApplication
from video_downloader.platforms.fanbox.downloader import resource_key
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.exporters import export_post,paragraph_html
from video_downloader.platforms.fanbox.models import Asset,Link
from video_downloader.platforms.fanbox.naming import asset_path,confined,render
from video_downloader.platforms.fanbox.repository import Repository
from video_downloader.platforms.fanbox.scheduling import AccountGate
from .test_archive_io import Body,DATA,DATE,setup_io
from .test_scan import FakeTransport
from .test_content import post


@pytest.mark.parametrize('status,expected',[('completed',0),('preview_ready',0),('paused',2),('partial',2)])
def test_native_cli_uses_config_and_frozen_job_resume(tmp_path,monkeypatch,capsys,status,expected):
    calls=[]
    class App:
        def __init__(self,path):calls.append(path)
        def create(self,url,options):calls.append((url,options));return {'id':'new'}
        def run(self,job_id,**kw):calls.append((job_id,kw));return {'status':status}
    monkeypatch.setattr(download_cli,'ArchiveApplication',App)
    monkeypatch.setattr(download_cli,'read_config',lambda root:{'FANBOX_OPTIONS':'{}','USE_COOKIES':0})
    args=['https://sample.fanbox.cc','--directory',str(tmp_path/'files'),'--anonymous','--max-posts','2','--preview']
    assert download_cli.main(args,root=tmp_path)==expected
    assert calls[1][1]['filters']['max_posts']==2 and calls[-1][1]['preview']
    assert json.loads(capsys.readouterr().out)['status']==status
    calls.clear()
    assert download_cli.main(['--resume','existing','--directory',str(tmp_path/'files')],root=tmp_path)==expected
    assert calls[-1][0]=='existing' and len(calls)==2


def test_native_cli_invalid_input_and_explicit_cookie_errors(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(download_cli,'read_config',lambda root:{'FANBOX_OPTIONS':'{}','USE_COOKIES':0})
    assert download_cli.main(['--cookies','missing','--anonymous'],root=tmp_path)==2
    assert download_cli.main(['--directory',str(tmp_path/'output')],root=tmp_path)==2
    path=tmp_path/'bad-options.json';path.write_text('[]')
    assert download_cli.main(['https://sample.fanbox.cc','--options',str(path)],root=tmp_path)==2
    assert download_cli.main(['https://sample.fanbox.cc','--cookies','missing'],root=tmp_path)==2
    assert 'Traceback' not in capsys.readouterr().out


def test_expired_url_refresh_keeps_stable_identity(tmp_path):
    class Refresh(Body):
        def transfer(self,url,headers,on_headers,on_chunk,**kw):
            if 'new=1' not in url:raise FanboxError('access_denied','expired')
            return super().transfer(url,headers,on_headers,on_chunk,**kw)
    downloader,model,asset,options=setup_io(tmp_path,Refresh())
    updated=replace(asset,url=asset.url+'?new=1')
    assert resource_key(model,asset)==resource_key(model,updated)
    result=downloader.download(model,asset,options,DATE,refresh=lambda:updated)
    assert result['status']=='completed'


@pytest.mark.parametrize('policy,code',[('ask','fallback_required'),('never','not_found'),('allow',None)])
def test_thumbnail_fallback_is_explicit_and_never_original_success(tmp_path,policy,code):
    image=b'\xff\xd8\xff'+DATA
    class Thumbnail(Body):
        def transfer(self,url,*args,**kwargs):
            if '/thumb.' not in url:raise FanboxError('not_found','not found')
            return super().transfer(url,*args,**kwargs)
    downloader,model,asset,options=setup_io(tmp_path,Thumbnail(image))
    asset=replace(asset,kind='image',extension='jpg',size=None,thumbnail_url='https://downloads.fanbox.cc/thumb.jpg')
    options['content']['image_fallback']=policy
    if code:
        with pytest.raises(FanboxError) as error:downloader.download(model,asset,options,DATE)
        assert error.value.code==code
    else:
        result=downloader.download(model,asset,options,DATE)
        assert result['status']=='degraded' and result['variant']=='thumbnail'
        assert downloader.repository.asset(resource_key(model,asset)).get('status')!='completed'


@pytest.mark.parametrize('policy,code',[('prompt','conflict_required'),('skip',None),('overwrite',None)])
def test_existing_unknown_file_conflict_policy(tmp_path,policy,code):
    downloader,model,asset,options=setup_io(tmp_path,Body())
    name=asset_path(model,asset,options,DATE)
    path=confined(tmp_path,name,create=True);path.write_bytes(b'user file')
    options['naming']['conflict']=policy
    if code:
        with pytest.raises(FanboxError) as error:downloader.download(model,asset,options,DATE)
        assert error.value.code==code and path.read_bytes()==b'user file'
    else:
        result=downloader.download(model,asset,options,DATE)
        assert result['status']==('skipped' if policy=='skip' else 'completed')
        assert path.read_bytes()==(b'user file' if policy=='skip' else DATA)


def test_offline_exports_preserve_utf16_links_and_escape_html(tmp_path):
    block={'type':'p','text':'😀go <script>', 'links':[{'offset':2,'length':2,'url':'https://example.test/#key'}],
           'styles':[{'type':'bold','offset':2,'length':2}]}
    rendered=paragraph_html(block)
    assert '😀' in rendered and '<strong>go</strong>' in rendered and 'href="https://example.test/#key"' in rendered
    assert '<script>' not in rendered
    block['links'][0]['url']='javascript:alert(1)'
    assert 'javascript:' not in paragraph_html(block)
    downloader,model,asset,options=setup_io(tmp_path,Body())
    model.blocks=[block,{'type':'image','asset_id':'missing'},{'type':'embed','urls':['https://example.test/']},{'type':'unknown'}]
    model.comments=[{'id':'1','body':'comment'}]
    model.links=[Link('https://example.test/#key',occurrences=[{'context':'password context'}])]
    options['content']['comments']=True;options['content']['body_formats']=['html','txt','md']
    record=export_post(tmp_path,downloader.repository,model,options,DATE,{})
    for name in ['post.html','post.txt','post.md','links.json','links.txt','comments.json']:
        assert (tmp_path/record['directory']/name).is_file()
    assert render('{title}',{'title':'{literal}'})=='{literal}'


def test_repository_rolls_back_and_rejects_unknown_schemas(tmp_path):
    repo=Repository(tmp_path/'good.sqlite')
    with pytest.raises(RuntimeError):
        with repo.transaction() as db:
            db.execute('INSERT INTO traffic VALUES(1,10)')
            raise RuntimeError('rollback')
    with repo.connect() as db:assert db.execute('SELECT COUNT(*) FROM traffic').fetchone()[0]==0
    for number in [0,99]:
        path=tmp_path/f'bad-{number}.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE unknown(value)');db.execute(f'PRAGMA user_version={number}')
        with pytest.raises(FanboxError):Repository(path)


def test_cancelled_waits_and_expired_leases_are_not_success(tmp_path):
    repo=Repository(tmp_path/'db.sqlite')
    cancel=threading.Event();cancel.set()
    gate=AccountGate(repo,cancel)
    with pytest.raises(FanboxError):gate.acquire('api')
    with pytest.raises(FanboxError):gate.wait(.01)
    with pytest.raises(FanboxError):repo.heartbeat('missing')


def test_partial_scan_restricted_and_resume_credentials_are_distinct(tmp_path):
    value=post('file',None);value['isRestricted']=True
    class T(FakeTransport):
        def __enter__(self):return self
        def __exit__(self,*_):pass
    app=ArchiveApplication(tmp_path,transport_factory=lambda *a,**kw:T([[value]]),binary_factory=lambda *a,**kw:Body())
    job=app.create('https://sample.fanbox.cc',{'network':{'api_interval_seconds':0}})
    result=app.run(job['id'])
    assert result['status']=='partial' and result['outcome']=='restricted'
    state=app.repository.job(job['id']);state['auth_scope']='other';app.repository.save_job(state)
    assert app.run(job['id'])['error']['code']=='credentials_changed'
    with pytest.raises(FanboxError):app.run('missing')
