import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

import pytest

from video_downloader.platforms.fanbox.archive import ArchiveApplication
from video_downloader.platforms.fanbox.downloader import Downloader,resource_key
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.exporters import export_post
from video_downloader.platforms.fanbox.models import Asset
from video_downloader.platforms.fanbox.naming import asset_path,confined,render,component
from video_downloader.platforms.fanbox.options import normalize_options
from video_downloader.platforms.fanbox.parsers import parse_post
from video_downloader.platforms.fanbox.repository import Repository
from video_downloader.platforms.fanbox.scheduling import AccountGate
from video_downloader.platforms.fanbox.service import write_json
from .test_content import post
from .test_scan import FakeTransport

DATE='2026-10-31T00:00:00+00:00'
DATA=b'content payload for a real protocol boundary'


def setup_io(tmp_path,transport):
    repository=Repository(tmp_path/'.fanbox/library.sqlite')
    gate=AccountGate(repository,threading.Event(),0)
    options=normalize_options({'network':{'file_start_interval_seconds':0,'api_interval_seconds':0}})
    value=post('file',{'text':'hello','files':[]})
    model=parse_post(value,options)
    asset=Asset('a','other','test','bin','https://downloads.fanbox.cc/test.bin',size=len(DATA))
    model.assets=[asset]
    return Downloader(tmp_path,repository,gate,transport),model,asset,options


class Body:
    def __init__(self,data=DATA,status=200,headers=None,fail_after=None):
        self.data,self.status,self.headers,self.fail_after=data,status,headers,fail_after
        self.requests=[]
    def transfer(self,url,headers,on_headers,on_chunk,*,maximum=None,meter=None):
        self.requests.append(dict(headers))
        response={'content-length':str(len(self.data)),'etag':'"version-1"'}
        response.update(self.headers or {})
        on_headers(self.status,response)
        if meter:meter(len(self.data))
        on_chunk(self.data)
        if self.fail_after:raise FanboxError('network_error','network')


def test_success_reuse_missing_and_modified_disk_repair(tmp_path):
    body=Body();downloader,model,asset,options=setup_io(tmp_path,body)
    first=downloader.download(model,asset,options,DATE)
    assert first['status']=='completed' and first['size']==len(DATA)
    assert downloader.download(model,asset,options,DATE)['status']=='reused'
    target=tmp_path/first['path'];target.write_bytes(b'changed')
    assert downloader.download(model,asset,options,DATE)['status']=='completed'
    target.unlink()
    assert downloader.download(model,asset,options,DATE)['status']=='completed'
    assert len(body.requests)==3 and downloader.repository.usage('Asia/Shanghai')==3*len(DATA)


def test_conditional_resume_validates_range_and_restarts_on_200(tmp_path):
    body=Body(DATA[10:],206,{'content-range':f'bytes 10-{len(DATA)-1}/{len(DATA)}'})
    downloader,model,asset,options=setup_io(tmp_path,body)
    key=resource_key(model,asset)
    part=confined(tmp_path,f'.fanbox/parts/{key}.part',create=True);part.write_bytes(DATA[:10])
    write_json(part.with_suffix('.json'),{'key':key,'etag':'"version-1"','total':len(DATA)})
    result=downloader.download(model,asset,options,DATE)
    assert (tmp_path/result['path']).read_bytes()==DATA
    assert body.requests==[{'Range':'bytes=10-','If-Range':'"version-1"'}]
    options['archive']['incremental']=False
    part.write_bytes(DATA[:10]);write_json(part.with_suffix('.json'),{'key':key,'etag':'"version-1"','total':len(DATA)})
    body.status=200;body.data=DATA;body.headers={}
    result=downloader.download(model,asset,options,DATE)
    assert (tmp_path/result['path']).read_bytes()==DATA


@pytest.mark.parametrize('headers',[
    {'content-range':'bytes 1-5/10'}, {'content-range':'bytes 0-4/10','content-length':'8'},
    {'content-range':'invalid'}, {'content-range':f'bytes 0-{len(DATA)-1}/{len(DATA)}','content-encoding':'gzip'},
])
def test_bad_ranges_never_enter_success_index(tmp_path,headers):
    body=Body(status=206,headers=headers)
    downloader,model,asset,options=setup_io(tmp_path,body)
    with pytest.raises(FanboxError):downloader.download(model,asset,options,DATE)
    assert downloader.repository.asset(resource_key(model,asset)).get('status')!='completed'


def test_416_complete_and_mismatched_etag_are_distinct(tmp_path):
    body=Body(b'',416,{'content-range':f'bytes */{len(DATA)}','content-length':'0'})
    downloader,model,asset,options=setup_io(tmp_path,body)
    key=resource_key(model,asset)
    part=confined(tmp_path,f'.fanbox/parts/{key}.part',create=True);part.write_bytes(DATA)
    write_json(part.with_suffix('.json'),{'key':key,'etag':'"version-1"','total':len(DATA)})
    assert downloader.download(model,asset,options,DATE)['status']=='completed'
    options['archive']['incremental']=False
    part.write_bytes(DATA);write_json(part.with_suffix('.json'),{'key':key,'etag':'"other"','total':len(DATA)})
    with pytest.raises(FanboxError) as failure:downloader.download(model,asset,options,DATE)
    assert failure.value.code=='range_restart'


def test_partial_survives_transport_failure_but_not_missing_validator(tmp_path):
    body=Body(DATA[:10],headers={'content-length':str(len(DATA))},fail_after=True)
    downloader,model,asset,options=setup_io(tmp_path,body)
    with pytest.raises(FanboxError):downloader.download(model,asset,options,DATE)
    key=resource_key(model,asset)
    assert (tmp_path/f'.fanbox/parts/{key}.part').exists()
    body.fail_after=False;body.status=206;body.data=DATA[10:]
    body.headers={'content-range':f'bytes 10-{len(DATA)-1}/{len(DATA)}'}
    result=downloader.download(model,asset,options,DATE)
    assert (tmp_path/result['path']).read_bytes()==DATA


@pytest.mark.parametrize('template',['../x','/x','C:/x','a/../../x','a\\x','{unknown}'])
def test_paths_reject_traversal_and_unknown_tokens(template):
    with pytest.raises(FanboxError):render(template,{'title':'safe'})


def test_windows_names_template_aliases_and_actual_html_paths(tmp_path):
    assert component('CON.txt')=='_CON.txt'
    assert len(component('长'*200).encode())<=120
    downloader,model,asset,options=setup_io(tmp_path,Body())
    model.title='<script>alert(1)</script>';model.blocks=[{'type':'file','asset_id':'a'}]
    options['naming']['attachments']='{postid}/{create_id}/{uid}/{index}-{name}.{ext}'
    options['naming']['post_dir']='{creator_id}/same'
    result=downloader.download(model,asset,options,DATE)
    assert result['path'].endswith('.bin') and not result['path'].endswith('.bin.bin')
    entry=export_post(tmp_path,downloader.repository,model,options,DATE,{'a:original':result})
    page=(tmp_path/entry['index']).read_text(encoding='utf-8')
    assert '<script>' not in page and 'Content-Security-Policy' in page
    assert result['path'].split('/')[-1] in page
    assert (tmp_path/entry['directory']/'post.json').is_file()


def test_symlink_is_not_followed(tmp_path):
    target=tmp_path/'outside';target.mkdir()
    link=tmp_path/'root'/'link';link.parent.mkdir()
    try:link.symlink_to(target,target_is_directory=True)
    except OSError:
        import os,subprocess
        if os.name!='nt':pytest.skip('symlink creation unavailable')
        subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(link),str(target)],
                       check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    with pytest.raises(FanboxError):confined(link.parent,'link/private',create=True)


def test_quota_reservation_concurrency_midnight_and_crash_expiry(tmp_path):
    now=[datetime(2026,10,31,15,59,59,tzinfo=timezone.utc).timestamp()]
    repository=Repository(tmp_path/'db.sqlite',clock=lambda:now[0])
    quota={'enabled':True,'limit_gib':100/1024**3,'timezone':'Asia/Shanghai'}
    first,_=repository.acquire('file',limit=2);second,_=repository.acquire('file',limit=2)
    assert repository.reserve(first,quota,80)==80
    with pytest.raises(FanboxError) as failure:repository.reserve(second,quota,30)
    assert failure.value.code=='quota_busy'
    repository.charge(first,70)
    now[0]+=2
    assert repository.usage('Asia/Shanghai')==0
    repository.charge(first,10)
    assert repository.usage('Asia/Shanghai')==10
    now[0]+=121
    third,_=repository.acquire('file',limit=2)
    assert repository.reserve(third,quota,90)==90


def test_shared_cooldown_and_tighter_file_concurrency(tmp_path):
    now=[1000.]
    repo=Repository(tmp_path/'db.sqlite',clock=lambda:now[0])
    first,_=repo.acquire('file',limit=1)
    assert repo.acquire('file',limit=3)[0] is None
    repo.release(first);repo.defer(60)
    gate=AccountGate(repo,threading.Event(),0)
    with pytest.raises(FanboxError) as failure:gate.acquire('api')
    assert failure.value.code=='rate_limited'
    assert repo.acquire('job:test')[0] is not None


def test_archive_preview_selection_and_restart_reuse(tmp_path):
    value=post('file',{'text':'paid prose','files':[{'id':'f','name':'file','extension':'bin','url':'https://downloads.fanbox.cc/file','size':len(DATA)}]})
    class T(FakeTransport):
        def __enter__(self):return self
        def __exit__(self,*_):pass
    transport=T([[value]])
    binary=Body()
    app=ArchiveApplication(tmp_path,transport_factory=lambda *a,**kw:transport,binary_factory=lambda *a,**kw:binary)
    options={'network':{'api_interval_seconds':0,'file_start_interval_seconds':0}}
    job=app.create('https://sample.fanbox.cc',options)
    assert app.run(job['id'],preview=True)['status']=='preview_ready'
    assert not binary.requests
    assert app.run(job['id'],selection={'post_ids':[value['id']]})['status']=='completed'
    restored=ArchiveApplication(tmp_path,transport_factory=lambda *a,**kw:transport,binary_factory=lambda *a,**kw:binary)
    result=restored.run(job['id'])
    assert result['status']=='completed' and result['counts']['reused']==1 and len(binary.requests)==1


def test_quota_pauses_job_and_releases_execution_lease(tmp_path):
    value=post('file',{'text':'','files':[{'id':'f','name':'file','extension':'bin','url':'https://downloads.fanbox.cc/file','size':len(DATA)}]})
    class T(FakeTransport):
        def __enter__(self):return self
        def __exit__(self,*_):pass
    app=ArchiveApplication(tmp_path,transport_factory=lambda *a,**kw:T([[value]]),binary_factory=lambda *a,**kw:Body())
    job=app.create('https://sample.fanbox.cc',{'quota':{'limit_gib':1/1024**3},'network':{'api_interval_seconds':0}})
    result=app.run(job['id'])
    assert result['status']=='paused' and result['error']['code']=='quota_exceeded'
    token,_=app.repository.acquire('job:'+job['id'])
    assert token
