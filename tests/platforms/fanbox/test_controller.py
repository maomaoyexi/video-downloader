from dataclasses import replace
import hashlib
import http.client
import json
import sqlite3
import threading

import pytest

from video_downloader.platforms.fanbox.archive import ArchiveApplication
from video_downloader.platforms.fanbox.controller import FanboxController
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.options import normalize_options
from video_downloader.platforms.fanbox.repository import Repository
from video_downloader.web.handler import HttpService,create_handler
from tests.helpers.web import make_dependencies
from .test_content import post
from .test_scan import FakeTransport
from .test_archive_io import Body


@pytest.fixture
def setup_controller(tmp_path):
    posts=[]
    for index in range(35):
        value=post('text',{'text':'body'});value['id']=str(index+1);value['title']=('Match ' if index%2 else 'Other ')+str(index)
        posts.append(value)
    class T(FakeTransport):
        def __enter__(self):return self
        def __exit__(self,*_):pass
    app=ArchiveApplication(tmp_path/'files',transport_factory=lambda *a,**kw:T([posts]),binary_factory=lambda *a,**kw:Body())
    config={'FANBOX_OPTIONS':json.dumps({'network':{'api_interval_seconds':0,'file_start_interval_seconds':0}})}
    launches=[];cancelled=[]
    controller=FanboxController(app,tool_dir=tmp_path,config_getter=lambda:config,
        start=lambda *args:launches.append(args) or {'ok':True,'task':{'id':'task'}},cancel=lambda *args:cancelled.append(args))
    yield app,controller,config,launches,cancelled
    controller.stop()


def preview(app,controller,key='request-test-1'):
    response=controller.create({'url':'https://sample.fanbox.cc','preview':True,'request_id':key})
    job=response['job']['id'];app.run(job,preview=True);controller.list()
    return app.repository.job(job)


def test_persistent_idempotency_and_versioned_selection(setup_controller):
    app,controller,config,launches,cancelled=setup_controller
    state=preview(app,controller)
    again=controller.create({'url':'https://sample.fanbox.cc','preview':True,'request_id':'request-test-1'})
    assert again['replayed'] and len(launches)==1
    with pytest.raises(FanboxError) as error:controller.create({'url':'https://other.fanbox.cc','request_id':'request-test-1'})
    assert error.value.code=='request_conflict'
    assert controller.detail(state['id'],offset=25)['total']==35
    assert len(controller.detail(state['id'],offset=25)['posts'])==10
    assert controller.detail(state['id'],query='match')['total']==17
    with pytest.raises(FanboxError) as error:
        controller.action({'id':state['id'],'action':'download','version':state['version']-1})
    assert error.value.code=='stale_version'
    result=controller.action({'id':state['id'],'action':'download','version':state['version'],
        'selection':{'title_query':'match','exclude_post_ids':['2']}})
    controller.finished(state['id'])
    assert app.run(state['id'])['status']=='completed'
    saved=app.repository.job(state['id'])
    assert len(saved['archives'])==16 and len(launches)==2
    assert (app.root/saved['output']).is_file()


def test_detailed_projection_hides_source_and_asset_urls(setup_controller):
    app,controller,*_=setup_controller
    state=preview(app,controller)
    value=controller.detail(state['id'],post_id='1')
    assert 'source' not in value['post']
    assert all('url' not in asset for asset in value['assets'])
    with pytest.raises(FanboxError):controller.detail(state['id'],offset=-1)
    with pytest.raises(FanboxError):controller.detail(state['id'],post_id='unknown')
    with pytest.raises(FanboxError):controller.action({'id':'../bad','action':'open'})


def test_pause_recovery_and_bad_selection(setup_controller):
    app,controller,config,launches,cancelled=setup_controller
    job=controller.create({'url':'https://sample.fanbox.cc','request_id':'pause-request'})['job']
    controller.action({'id':job['id'],'action':'pause'})
    assert cancelled==[(job['id'],'task')]
    controller.finished(job['id'])
    restored=controller.list()[0]
    assert restored['status']=='paused' and restored['error']['code']=='interrupted'
    assert controller.snapshot()[0]['id']==job['id']
    state=preview(app,controller,'second-request')
    for selection in [{'unknown':1},{'post_ids':['999']},{'asset_ids':['bad']},{'accessible_only':'yes'},{'title_query':42}]:
        with pytest.raises(FanboxError):controller.action({'id':state['id'],'version':state['version'],'action':'download','selection':selection})


def test_migration_keeps_v1_backup_and_job_state(tmp_path):
    path=tmp_path/'library.sqlite';repo=Repository(path)
    with repo.connect() as db:
        db.execute('DROP TABLE requests');db.execute('DROP TABLE url_records');db.execute('DROP TABLE success_traffic');db.execute('DROP TABLE metadata');db.execute('DROP TABLE verifications')
        db.execute('DROP INDEX jobs_source');db.execute('PRAGMA user_version=1')
    upgraded=Repository(path)
    with upgraded.connect() as db:assert db.execute('PRAGMA user_version').fetchone()[0]==Repository.VERSION
    backup=path.with_suffix('.sqlite.v1.bak')
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==1
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='requests'").fetchone()


def test_auth_file_loaded_is_not_a_claim_of_live_permission(setup_controller,tmp_path):
    app,controller,config,*_=setup_controller
    cookie=tmp_path/'cookies.txt';cookie.write_text('# Netscape HTTP Cookie File\n.fanbox.cc\tTRUE\t/\tTRUE\t0\tFANBOXSESSID\tsynthetic-session\n')
    status=controller.auth_status()
    assert status['status']=='loaded' and 'cookie' not in status
    config['FANBOX_ANONYMOUS']=1
    assert controller.auth_status()['status']=='anonymous'
    assert 'defaults' in controller.options()


def test_http_routes_keep_origin_token_and_version_guards(setup_controller):
    app,controller,*_=setup_controller
    deps=replace(make_dependencies(threading.Event()),fanbox=controller)
    service=HttpService(lambda:create_handler(deps));service.start()
    def request(method,path,data=None,token=True,origin=None):
        conn=http.client.HTTPConnection('127.0.0.1',service.port,timeout=5)
        headers={'Content-Type':'application/json'}
        if token:headers['X-Session-Token']='test-token'
        if origin:headers['Origin']=origin
        conn.request(method,path,json.dumps(data).encode() if data is not None else None,headers)
        response=conn.getresponse();body=response.read();status=response.status;conn.close()
        return status,body
    try:
        assert request('GET','/api/fanbox/options',token=False)[0]==403
        assert request('POST','/api/fanbox/create',{},origin='https://evil.test')[0]==403
        assert request('GET','/api/fanbox/options')[0]==200
        assert request('GET','/api/fanbox/auth')[0]==200
        assert request('GET','/api/fanbox/records',token=False)[0]==403
        assert request('GET','/api/fanbox/usage')[0]==200
        assert request('POST','/api/fanbox/records',{'action':'import','records':[{'url':'files/sample.zip?secret=x'}]},origin='https://evil.test')[0]==403
        assert request('POST','/api/fanbox/records',{'action':'import','records':[{'url':'files/sample.zip?secret=x'}]})[0]==200
        assert b'secret=' not in request('GET','/api/fanbox/records?export=1')[1]
        assert request('POST','/api/fanbox/create',{'url':True})[0]==400
        response=request('POST','/api/fanbox/create',{'url':'https://sample.fanbox.cc','request_id':'http-request','preview':True})
        assert response[0]==200
        job=json.loads(response[1])['job']['id'];app.run(job,preview=True);controller.list()
        assert request('GET','/api/fanbox/job?id='+job+'&offset=-1')[0]==400
        assert request('GET','/api/fanbox/job?id='+job)[0]==200
        assert request('GET','/api/fanbox/manifest?id='+job)[0]==200
        assert request('POST','/api/fanbox/naming-preview',{'options':{}})[0]==200
        assert request('POST','/api/fanbox/action',{'id':job,'action':'download','version':0})[0]==409
        assert request('POST','/api/fanbox/import-settings',{'settings':{'saveText':False}})[0]==200
        assert request('GET','/api/fanbox/jobs')[0]==200
        conn=http.client.HTTPConnection('127.0.0.1',service.port,timeout=5)
        conn.request('GET','/api/events',headers={'X-Session-Token':'test-token'})
        response=conn.getresponse();line=response.readline()
        ready=json.loads(line.decode().removeprefix('data: '))
        assert ready['data']['fanbox_jobs'][0]['id']==job
        response.close();conn.close()
    finally:service.stop()
