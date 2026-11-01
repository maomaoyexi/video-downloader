import copy
from urllib.parse import parse_qs,urlsplit,urlencode

import pytest

from video_downloader.platforms.fanbox.client import FanboxClient
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.options import normalize_options
from video_downloader.platforms.fanbox.service import ScanService
from video_downloader.platforms.fanbox.urls import parse_source,source_for_options
from .test_content import post


def value(identity,creator='alpha'):
    result=post(identity=str(identity));result['creatorId']=creator
    return result


class CollectionTransport:
    def __init__(self,scope='following',fail=False):
        self.scope=scope;self.calls=[];self.fail=fail;self.cycle=False;self.unsafe=False
        self.posts={str(i):value(i,'alpha' if i<=151 else 'beta') for i in range(1,306)}
    def get_json(self,url):
        self.calls.append(url);parsed=urlsplit(url);query=parse_qs(parsed.query);endpoint=parsed.path[1:]
        if endpoint=='creator.listFollowing':
            return {'body':{'creators':[{'creatorId':'alpha'},{'creatorId':'beta'},{'creatorId':'alpha'}]}}
        if endpoint=='creator.get':return {'body':{'creatorId':'alpha','user':{'userId':'100'}}}
        if endpoint=='post.paginateCreator':
            return {'body':[f'https://api.fanbox.cc/post.listCreator?creatorId={query["creatorId"][0]}&page={n}' for n in range(2)]}
        if endpoint=='post.listCreator':
            creator=query['creatorId'][0];page=int(query['page'][0])
            if self.fail and creator=='beta' and page==1:raise FanboxError('network_error','synthetic outage')
            batch=(range(1,152) if page==0 else []) if creator=='alpha' else (range(152,304) if page==0 else [303,304,305])
            return {'body':{'posts':[copy.deepcopy(self.posts[str(i)]) for i in batch]}}
        if endpoint in {'post.listSupporting','post.listTagged'}:
            page=int(query.get('page',['0'])[0]);batch=[range(1,152),[],range(152,306)][page]
            next_url=None
            if page<2:
                params={'page':page+1}
                if endpoint=='post.listTagged':params.update(userId='999' if self.unsafe else '100',tag=query['tag'][0])
                next_url='https://api.fanbox.cc/'+endpoint+'?'+urlencode(params)
                if self.cycle:next_url=url
            rows=[copy.deepcopy(self.posts[str(i)]) for i in batch]
            if endpoint=='post.listTagged':
                for row in rows:row['creatorId']='alpha'
            return {'body':{'items':rows,'nextUrl':next_url}}
        if endpoint=='post.info':
            result=copy.deepcopy(self.posts[query['postId'][0]])
            if self.scope=='tag':result['creatorId']='alpha'
            return {'body':result}
        raise AssertionError(endpoint)


@pytest.mark.parametrize('scope,url',[
    ('following','https://www.fanbox.cc/creators/following'),
    ('supporting','https://www.fanbox.cc/home/supporting'),
    ('tag','https://alpha.fanbox.cc/tags/'+urlencode({'x':'日本語 + #'}).split('=',1)[1])])
def test_all_collection_pages_include_empty_pages_and_305_posts(scope,url):
    transport=CollectionTransport(scope)
    result=ScanService(FanboxClient(transport)).scan(url,{'network':{'api_interval_seconds':0}})
    assert result['status']=='completed' and result['coverage']['list_complete']
    assert len(result['posts'])==305 and len({p['id'] for p in result['posts']})==305


def test_following_resume_freezes_members_and_does_not_refetch_completed_posts():
    transport=CollectionTransport(fail=True);service=ScanService(FanboxClient(transport))
    url='https://www.fanbox.cc/creators/following'
    first=service.scan(url)
    assert first['status']=='partial' and len(first['posts'])==303
    transport.calls=[];transport.fail=False
    result=service.scan(url,checkpoint=first['checkpoint'])
    assert result['status']=='completed' and len(result['posts'])==305
    assert not any('creator.listFollowing' in call or 'creatorId=alpha' in call or 'postId=1&' in call for call in transport.calls)
    assert sum('post.info?' in call for call in transport.calls)==2
    corrupted=copy.deepcopy(first['checkpoint']);corrupted['members']=['beta']
    with pytest.raises(FanboxError):service.scan(url,checkpoint=corrupted)


def test_feed_cycles_and_wrong_tag_identity_are_not_followed():
    transport=CollectionTransport('tag');transport.unsafe=True
    result=ScanService(FanboxClient(transport)).scan('https://alpha.fanbox.cc/tags/test')
    assert result['status']=='failed' and result['errors'][0]['code']=='unsafe_api_url'
    assert len(transport.calls)==2
    transport=CollectionTransport('supporting');transport.cycle=True
    result=ScanService(FanboxClient(transport)).scan('https://www.fanbox.cc/creators/supporting')
    assert result['status']=='partial' and result['errors'][0]['code']=='pagination_cycle'


def test_scope_override_and_encoded_tag_url():
    options=normalize_options({'workflow':{'scope':'following'}})
    assert source_for_options('https://www.fanbox.cc/',options).scope=='following'
    source=parse_source('https://alpha.fanbox.cc/tags/a%2Fb%20%2B%20%23')
    assert source.tag=='a/b + #' and '%2F' in source.url
    for url in ['https://alpha.fanbox.cc/tags/%GG','https://alpha.fanbox.cc/tags/%FF','https://fanbox.cc.evil.test/']:
        with pytest.raises(FanboxError):parse_source(url)


def test_collection_post_limit_is_global_across_creators():
    transport=CollectionTransport();result=ScanService(FanboxClient(transport)).scan(
        'https://www.fanbox.cc/creators/following',{'filters':{'max_posts':153}})
    assert len(result['posts'])==153 and result['coverage']['limit_reached'] and not result['coverage']['list_complete']
