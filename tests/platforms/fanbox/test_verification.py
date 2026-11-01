import copy
import hashlib
import threading

import pytest

from video_downloader.platforms.fanbox import verification
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.repository import Repository
from .test_controller import setup_controller,preview


def completed(app,controller):
    state=preview(app,controller)
    payload=b'verified content';path=app.root/'ok.bin';path.write_bytes(payload)
    record={'status':'completed','path':'ok.bin','size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
    state.update(status='completed',phase='finished',files={'1':{'a:original':record}})
    app.repository.save_job(state);controller.list()
    return state


def finish(controller):
    controller.verifier.thread.join(5)
    assert not controller.verifier.thread.is_alive()


def test_verification_reports_changes_and_never_mutates_resources(setup_controller):
    app,controller,*_=setup_controller;state=completed(app,controller)
    record=state['files']['1']['a:original']
    (app.root/'changed.bin').write_bytes(b'changed content!')
    for name,path in [('b','changed.bin'),('c','missing.bin'),('d','unknown.bin'),('e','../outside.bin')]:
        state['files']['1'][name+':original']=dict(record,path=path)
    state['files']['1']['d:original'].pop('sha256')
    app.repository.save_job(state);before=copy.deepcopy(state)
    controller.action({'id':state['id'],'version':state['version'],'action':'verify'});finish(controller)
    report=controller.detail(state['id'])['verification']
    assert report['status']=='partial' and report['checked']==5 and report['ok']==1
    assert report['modified']==1 and report['missing']==1 and report['unverified']==1 and report['unreadable']==1
    assert (app.root/'ok.bin').read_bytes()==b'verified content' and not (app.root/'missing.bin').exists()
    assert app.repository.job(state['id'])==before
    assert controller.manifest(state['id'])['verification']['status']=='partial'
    assert 'issues' not in controller.list()[0]['verification']


def test_cancel_is_bounded_and_download_cache_actions_are_excluded(setup_controller,monkeypatch):
    app,controller,*_=setup_controller;state=completed(app,controller)
    entered=threading.Event();release=threading.Event();actual=verification.verify_file
    def slow(root,record,cancel,progress):
        entered.set();assert release.wait(3)
        return actual(root,record,cancel,progress)
    monkeypatch.setattr(verification,'verify_file',slow)
    controller.action({'id':state['id'],'version':state['version'],'action':'verify'})
    assert entered.wait(2)
    try:
        with pytest.raises(FanboxError) as error:controller.action({'id':state['id'],'version':state['version'],'action':'clear_cache'})
        assert error.value.code=='job_busy'
        controller.action({'id':state['id'],'action':'cancel_verification'})
    finally:release.set()
    finish(controller)
    assert controller.detail(state['id'])['verification']['status']=='cancelled'
    assert not app.repository.has_lease('job:'+state['id'])
    assert (app.root/'ok.bin').read_bytes()==b'verified content'


def test_busy_file_and_stale_versions_do_not_claim_success(setup_controller):
    app,controller,*_=setup_controller;state=completed(app,controller)
    with pytest.raises(FanboxError):controller.action({'id':state['id'],'version':state['version']-1,'action':'verify'})
    record=state['files']['1']['a:original'];record['key']='shared'
    app.repository.save_job(state);lease,_=app.repository.acquire('asset:shared')
    try:
        controller.action({'id':state['id'],'version':state['version'],'action':'verify'});finish(controller)
        assert controller.detail(state['id'])['verification']['busy']==1
    finally:app.repository.release(lease)
    controller.action({'id':state['id'],'version':state['version'],'action':'verify'});finish(controller)
    assert controller.detail(state['id'])['verification']['status']=='completed'
    app.repository.save_job(state)
    assert controller.detail(state['id'])['verification']['status']=='stale'


def test_interrupted_report_is_recovered_without_restarting_io(setup_controller):
    app,controller,*_=setup_controller;state=completed(app,controller)
    report={'status':'running','job_version':state['version'],'checked':0,'total':1,'issues':[]}
    app.repository.save_verification(state['id'],report)
    assert controller.list()[0]['verification']['status']=='interrupted'
    assert controller.verifier.thread is None


def test_schema_three_upgrade_keeps_url_records_and_backup(tmp_path):
    path=tmp_path/'library.sqlite';repo=Repository(path);repo.import_url_records(['/file'])
    with repo.connect() as db:db.execute('DROP TABLE verifications');db.execute('PRAGMA user_version=3')
    repo=Repository(path)
    assert path.with_suffix('.sqlite.v3.bak').is_file() and repo.record_stats()['imported']==1
    assert repo.verification('missing') is None
