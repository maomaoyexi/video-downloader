import copy
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from video_downloader.platforms.fanbox.client import FanboxClient
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.options import normalize_options
from video_downloader.platforms.fanbox.service import ScanService, write_json
from .test_content import post


class FakeTransport:
    def __init__(self, pages, details=None, fail_page=None):
        self.pages=pages;self.details=details or {};self.calls=[];self.fail_page=fail_page

    def get_json(self,url):
        self.calls.append(url)
        endpoint=urlsplit(url).path[1:];query=parse_qs(urlsplit(url).query)
        if endpoint=='post.paginateCreator':
            return {'body':{'pageUrls':[f'https://api.fanbox.cc/post.listCreator?creatorId=sample&page={n}' for n in range(len(self.pages))]}}
        if endpoint=='post.listCreator':
            n=int(query['page'][0])
            if n==self.fail_page:raise FanboxError('network_error','模拟网络中断')
            summaries=copy.deepcopy(self.pages[n])
            for item in summaries:item.pop('body',None);item.pop('type',None)
            return {'body':{'posts':summaries}}
        if endpoint=='post.info':
            identity=query['postId'][0]
            if self.details.get(identity)=='challenge':raise FanboxError('challenge_required','模拟浏览器验证')
            value=self.details.get(identity) or next(p for page in self.pages for p in page if p['id']==identity)
            return {'body':{'post':copy.deepcopy(value)}}
        raise AssertionError('Unexpected request (including attachment requests): '+url)


def test_pagination_empty_page_pins_and_300_posts():
    pages=[[post(identity=str(i)) for i in range(1,151)],[],[post(identity='1')]+[post(identity=str(i)) for i in range(151,306)]]
    transport=FakeTransport(pages)
    result=ScanService(FanboxClient(transport)).scan('https://sample.fanbox.cc/')
    assert result['status']=='completed' and result['counts']['posts_parsed']==305
    assert result['coverage']['list_complete']
    assert len([u for u in transport.calls if '/post.info?' in u])==305
    assert all(urlsplit(u).hostname=='api.fanbox.cc' for u in transport.calls)


def test_failed_listing_resume_and_reuse_parsed_details():
    pages=[[post(identity='1')],[post(identity='2')]]
    transport=FakeTransport(pages,fail_page=1);service=ScanService(FanboxClient(transport))
    first=service.scan('https://sample.fanbox.cc/')
    assert first['status']=='partial' and first['checkpoint']['page_index']==1
    transport.fail_page=None;transport.calls.clear()
    second=service.scan('https://sample.fanbox.cc/',checkpoint=first['checkpoint'])
    assert second['status']=='completed' and second['counts']['posts_parsed']==2
    assert not any('postId=1' in u for u in transport.calls)


def test_restricted_text_unknown_and_max_posts():
    restricted=post(identity='2');restricted['body']=None
    transport=FakeTransport([[post(),restricted],[post(identity='3')]])
    result=ScanService(FanboxClient(transport)).scan('https://sample.fanbox.cc/',{'filters':{'max_posts':2}})
    assert result['counts']['restricted']==1 and result['coverage']['limit_reached']
    assert not result['coverage']['list_complete'] and result['status']=='completed'
    assert len([u for u in transport.calls if 'post.listCreator?' in u])==1


def test_single_post_filters_and_challenge_stops():
    transport=FakeTransport([[post(),post(identity='2')]],details={'1':'challenge'})
    result=ScanService(FanboxClient(transport)).scan('https://sample.fanbox.cc/')
    assert result['status']=='failed' and len([u for u in transport.calls if 'post.info?' in u])==1
    assert result['errors'][0]['code']=='challenge_required'
    transport=FakeTransport([[post()]])
    result=ScanService(FanboxClient(transport)).scan('https://sample.fanbox.cc/posts/1',{'filters':{'include_paid':False}})
    assert result['status']=='completed' and result['counts']['posts_filtered']==1


def test_resume_rejects_changed_settings_account_source_and_tampered_urls():
    service=ScanService(FanboxClient(FakeTransport([[post()]])))
    state=service.scan('https://sample.fanbox.cc/')['checkpoint']
    for kwargs in [{'options':{'content':{'links':False}}},{'auth_scope':'different'}]:
        with pytest.raises(FanboxError):service.scan('https://sample.fanbox.cc/',checkpoint=state,**kwargs)
    with pytest.raises(FanboxError):service.scan('https://other.fanbox.cc/',checkpoint=state)
    state['pages']=['https://127.0.0.1/private']
    with pytest.raises(FanboxError):service.scan('https://sample.fanbox.cc/',checkpoint=state)


def test_client_rejects_schema_and_cross_creator():
    class T:
        value={}
        def get_json(self,url):return {'body':self.value}
    transport=T();client=FanboxClient(transport)
    for call in [lambda:client.pages('sample'),lambda:client.page('https://api.fanbox.cc/post.listCreator?creatorId=sample','sample'),
                 lambda:client.creator('sample'),lambda:client.post('1','sample')]:
        with pytest.raises(FanboxError):call()
    with pytest.raises(FanboxError):client.page_url('https://api.fanbox.cc/post.listCreator?creatorId=other','sample')
    transport.value={'posts':[post()]}
    assert client.page('https://api.fanbox.cc/post.listCreator?creatorId=sample','sample')
    transport.value={'post':post()}
    with pytest.raises(FanboxError):client.post('2','sample')


def test_comments_pages_duplicates_partial_and_links():
    class T(FakeTransport):
        def get_json(self,url):
            if 'post.getComments' not in url:return super().get_json(url)
            offset=int(parse_qs(urlsplit(url).query)['offset'][0])
            return {'body':{'viewMode':'all','commentList':{'items':[{'id':str(i),'body':'https://example.test/comment','replies':[]} for i in range(50 if offset==0 else 1)],'nextUrl':None}}}
    value=post();value['commentCount']=51
    transport=T([[value]])
    result=ScanService(FanboxClient(transport)).scan('https://sample.fanbox.cc/',{'content':{'comments':True}})
    parsed=result['posts'][0]
    assert parsed['comments_complete'] and len(parsed['comments'])==50
    assert parsed['links'][0]['occurrences'][0]['source']=='comment'
    items,complete,warning=FanboxClient(transport).comments('1',max_pages=1)
    assert len(items)==50 and not complete and warning=='comment_page_limit'


def test_atomic_json_write(tmp_path,monkeypatch):
    path=tmp_path/'manifest.json';write_json(path,{'ok':True});assert json.loads(path.read_text())=={'ok':True}
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr('video_downloader.platforms.fanbox.service.os.replace',fail)
    with pytest.raises(OSError):write_json(path,{'changed':True})
    assert json.loads(path.read_text())=={'ok':True} and not list(tmp_path.glob('*.tmp'))
