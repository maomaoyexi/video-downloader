from dataclasses import asdict
from datetime import datetime
import sqlite3

import pytest

from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.models import Asset,Post
from video_downloader.platforms.fanbox.downloader import resource_key
from video_downloader.platforms.fanbox.records import preview_records
from video_downloader.platforms.fanbox.repository import Repository
from .test_archive_io import setup_io,Body,DATE,DATA
from .test_controller import setup_controller,preview
from .test_content import post as source_post
from .test_scan import FakeTransport
from video_downloader.platforms.fanbox.archive import ArchiveApplication
from video_downloader.platforms.fanbox.exporters import export_post
from video_downloader.platforms.fanbox.options import import_plugin_settings


def test_url_import_is_only_a_hint_and_clear_preserves_verified_files(tmp_path):
    downloader,model,asset,options=setup_io(tmp_path,Body())
    paths,report=preview_records([{'url':asset.url+'?credential=secret'},{'url':asset.url},
        {'url':'https://evil.test/file'},{'url':'../escape'},{'url':'https://i.pximg.net/image.png?token=secret'}])
    assert report['accepted']==2 and report['duplicates']==1 and report['rejected']==2
    downloader.repository.import_url_records(paths)
    assert downloader.repository.record_stats()=={'urls':2,'imported':2,'verified':0}
    saved=downloader.download(model,asset,options,DATE)
    assert saved['status']=='completed' and 'secret' not in repr(downloader.repository.url_records())
    downloader.repository.clear_url_records()
    assert downloader.repository.record_stats()['verified']==1 and (tmp_path/saved['path']).is_file()
    assert downloader.download(model,asset,options,DATE)['status']=='reused'


def test_completed_volume_and_received_bytes_use_distinct_local_days(tmp_path):
    now=[datetime.fromisoformat('2026-10-31T15:59:59+00:00').timestamp()]
    repo=Repository(tmp_path/'library.sqlite',clock=lambda:now[0])
    for index,(received,size) in enumerate([(10,20),(30,40)]):
        token,_=repo.acquire('file');repo.charge(token,received);repo.release(token)
        key=str(index);repo.allocate(key,key);repo.save_asset(key,{'status':'completed','size':size,'resource_path':'/file'+key})
        now[0]+=2
    days=repo.usage_history('Asia/Shanghai')
    assert days[-2]['bytes']==10 and days[-2]['completed_bytes']==20
    assert days[-1]['bytes']==30 and days[-1]['completed_bytes']==40


def test_version_two_migration_preserves_data_and_backup(tmp_path):
    path=tmp_path/'library.sqlite';repo=Repository(path)
    with repo.connect() as db:
        db.execute('DROP TABLE url_records');db.execute('DROP TABLE success_traffic');db.execute('DROP TABLE metadata');db.execute('DROP TABLE verifications');db.execute('DROP INDEX jobs_source')
        db.execute('PRAGMA user_version=2')
    repo=Repository(path)
    assert path.with_suffix('.sqlite.v2.bak').is_file()
    with sqlite3.connect(path.with_suffix('.sqlite.v2.bak')) as db:assert db.execute('PRAGMA user_version').fetchone()[0]==2
    with repo.connect() as db:assert db.execute('PRAGMA user_version').fetchone()[0]==Repository.VERSION


def test_cache_cleanup_only_removes_known_partials_and_checks_version(setup_controller):
    app,controller,*_=setup_controller;state=preview(app,controller)
    state['scan']['posts'][0]['assets']=[asdict(Asset('a','other','file','bin','https://downloads.fanbox.cc/file'))]
    app.repository.save_job(state);controller.list()
    post=Post.from_dict(state['scan']['posts'][0]);key=resource_key(post,post.assets[0])
    parts=app.root/'.fanbox/parts';parts.mkdir(exist_ok=True)
    part=parts/(key+'.part');part.write_bytes(b'partial');(parts/(key+'.json')).write_text('{}')
    keep=app.root/'saved.bin';keep.write_bytes(b'keep');unrelated=parts/'unrelated.part';unrelated.write_bytes(b'other')
    with pytest.raises(FanboxError):controller.action({'id':state['id'],'action':'clear_cache','version':state['version']-1})
    assert part.exists()
    result=controller.action({'id':state['id'],'action':'clear_cache','version':state['version']})
    assert result['cache']['removed']==2 and not part.exists() and unrelated.exists() and keep.read_bytes()==b'keep'
    assert app.repository.job(state['id'])['checkpoint'] is None


def test_summaries_and_history_do_not_load_full_jobs(setup_controller,monkeypatch):
    app,controller,*_=setup_controller;state=preview(app,controller)
    def forbidden(*args):raise AssertionError('Full collection materialized')
    monkeypatch.setattr(app.repository,'jobs',forbidden)
    assert controller.list()[0]['id']==state['id']
    result=controller.history(state['source'])
    assert result['runs'][0]['id']==state['id'] and 'body' not in repr(result)
    assert controller.records()=={'urls':0,'imported':0,'verified':0}
    report=controller.record_command({'action':'import','records':[{'url':'files/a.zip?secret=value'}]})
    assert report['inserted']==1 and controller.records(export=True)['records']==[{'url':'files/a.zip'}]


def test_comment_html_text_and_compatibility_report_are_explicit(tmp_path):
    downloader,model,asset,options=setup_io(tmp_path,Body())
    model.comments=[{'user':{'name':'<author>'},'body':'<script>bad()</script>',
                     'replies':{'items':[{'body':'reply'}]}}]
    model.comments_complete=False;options['content'].update(comments=True,body_formats=['html','txt'])
    entry=export_post(tmp_path,downloader.repository,model,options,DATE,{})
    folder=tmp_path/entry['directory']
    html=(folder/'post.html').read_text(encoding='utf-8');text=(folder/'post.txt').read_text(encoding='utf-8')
    assert '&lt;script&gt;' in html and '<script>' not in html and 'reply' in html and '评论未完整' in text
    _,report=import_plugin_settings({'userSetLang':'en','theme':'dark','showHowToUse':False})
    assert {row['key']:row['status'] for row in report}=={'userSetLang':'follows_application','theme':'follows_application','showHowToUse':'preserved_not_applied'}


def test_restricted_post_can_save_its_public_cover_without_claiming_full_access(tmp_path):
    value=source_post();value['body']=None;value['coverImageUrl']='https://pixiv.pximg.net/fanbox/public/cover.jpg'
    class Transport(FakeTransport):
        def __enter__(self):return self
        def __exit__(self,*args):pass
    binary=Body(b'\xff\xd8\xff'+DATA)
    app=ArchiveApplication(tmp_path,transport_factory=lambda *a,**k:Transport([[value]]),binary_factory=lambda *a,**k:binary)
    job=app.create('https://sample.fanbox.cc',{'network':{'api_interval_seconds':0,'file_start_interval_seconds':0}})
    result=app.run(job['id'])
    assert result['status']=='partial' and result['counts']['restricted']==1 and result['counts']['completed']==1
    assert len(binary.requests)==1
