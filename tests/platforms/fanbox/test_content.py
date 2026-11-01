"""Synthetic content matching observed API shapes; no creator content/cookies."""
import copy
import json

import pytest

from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.filters import category, post_reason
from video_downloader.platforms.fanbox.links import HtmlContent, LinkCollector, clean_link, embed_url, text_links
from video_downloader.platforms.fanbox.models import Post
from video_downloader.platforms.fanbox.options import LEGACY_KEYS, import_plugin_settings, normalize_options, options_json
from video_downloader.platforms.fanbox.parsers import parse_post, require_post


def image(identity='img1'):
    return {'id':identity,'extension':'png','width':2048,'height':3072,
            'originalUrl':f'https://downloads.fanbox.cc/images/post/1/{identity}.png',
            'thumbnailUrl':f'https://downloads.fanbox.cc/images/post/1/w/1200/{identity}.jpg'}


def attachment(identity='file1', extension='zip'):
    return {'id':identity,'name':'Sample Original','extension':extension,'size':512,
            'url':f'https://downloads.fanbox.cc/files/post/1/{identity}.{extension}'}


def post(kind='text', body=None, identity='1'):
    if body is None: body={'text':'Sample text'}
    return {'id':identity,'creatorId':'sample','user':{'userId':'100'},'title':'Sample Work',
            'feeRequired':500,'publishedDatetime':'2026-10-20T10:00:00+09:00',
            'updatedDatetime':'2026-10-21T10:00:00+09:00','type':kind,'body':body,'tags':['sample'],'commentCount':0}


def test_article_order_assets_links_and_roundtrip():
    value=post('article',{'blocks':[{'type':'p','text':'See https://example.test/a and https://mega.nz/file/abc#secret!key',
                        'links':[{'url':'https://drive.google.com/file/d/sample','offset':0,'length':3}]},
        {'type':'image','imageId':'img1'},{'type':'header','text':'Header'}, {'type':'file','fileId':'file1'},
        {'type':'embed','embedId':'e1'}, {'type':'url_embed','urlEmbedId':'u1'}],
        'imageMap':{'img1':image()},'fileMap':{'file1':attachment()},
        'embedMap':{'e1':{'serviceProvider':'youtube','contentId':'abc'}},
        'urlEmbedMap':{'u1':{'type':'html.card','html':'<iframe src="https://example.test/embed?a=1&amp;b=2"></iframe>'}}})
    parsed=parse_post(value)
    assert [b['type'] for b in parsed.blocks]==['p','image','header','file','embed','embed']
    assert [a.id for a in parsed.assets]==['img1','file1']
    assert len(parsed.links)==5
    assert any(link.url.endswith('#secret!key') for link in parsed.links)
    assert parsed.links[0].occurrences[0]['block_index']==1
    assert Post.from_dict(parsed.to_dict())==parsed
    assert value['body']['blocks'][0]['text'].startswith('See ')


@pytest.mark.parametrize('kind,body,assets,links',[
    ('image',{'text':'hi','images':[image(),image('img2')]},2,0),
    ('file',{'text':'password: sample','files':[attachment(),attachment('f2','psd')]},2,0),
    ('text',{'text':'https://a.test/one https://b.test/two'},0,2),
    ('video',{'text':'hi','video':{'serviceProvider':'vimeo','videoId':'123'}},0,1),
    ('entry',{'html':'<p>Hello</p><a href="https://downloads.fanbox.cc/images/post/1/original.png"><img src="https://downloads.fanbox.cc/images/post/1/w/1200/thumb.jpg"></a><a href="https://a.test/">link</a>'},1,2),
])
def test_six_formats(kind,body,assets,links):
    result=parse_post(post(kind,body))
    assert result.access=='accessible' and len(result.assets)==assets and len(result.links)==links
    if kind=='entry': assert result.assets[0].url.endswith('original.png')


def test_restricted_not_missing_body_and_cover():
    value=post();value['body']=None;value['cover']={'type':'image','url':'https://pixiv.pximg.net/c/1200x630_90_a2_g5/fanbox/public/cover.jpg'}
    result=parse_post(value)
    assert result.access=='restricted' and result.assets[0].kind=='cover' and '/c/' not in result.assets[0].url
    assert not result.blocks
    del value['body']
    assert require_post(value,detail=False)
    with pytest.raises(FanboxError):parse_post(value)


def test_unknown_missing_and_filtered_content():
    value=post('article',{'blocks':[{'type':'image','imageId':'gone'},{'type':'future','x':1},
                                  {'type':'embed','embedId':'new'}],'embedMap':{'new':{'serviceProvider':'unknown','contentId':'x'}}})
    parsed=parse_post(value)
    assert {'missing_asset','unknown_block','unknown_embed'}<=set(parsed.warnings)
    assert parsed.blocks[1]['raw']['x']==1
    assert 'unknown_post_type' in parse_post(post('future',{'payload':1})).warnings
    with pytest.raises(FanboxError):parse_post(post('article',{}))
    with pytest.raises(FanboxError):parse_post(post('image',{}))
    with pytest.raises(FanboxError):parse_post(post('text',{'text':123}))
    value=post('image',{'text':'https://a.test/','images':[image()]})
    options=normalize_options({'content':{'body':False,'links':False,'raw_snapshot':False,'image_quality':'thumbnail'},
                              'filters':{'resource_types':{'image':False}}})
    parsed=parse_post(value,options)
    assert not parsed.links and parsed.source is None and parsed.blocks[0]['text']==''
    assert parsed.assets[0].variant=='thumbnail' and not parsed.assets[0].selected


def test_resource_boundaries_and_names():
    a=image();a['originalUrl']='https://127.0.0.1/private'
    assert 'unsafe_asset_url' in parse_post(post('image',{'images':[a]})).warnings
    a=image();a.pop('thumbnailUrl')
    assert 'missing_thumbnail' in parse_post(post('image',{'images':[a]}),{'content':{'image_quality':'thumbnail'}}).warnings
    assert category('PSD')=='source' and category('future')=='other'
    value=post('file',{'files':[attachment()]})
    result=parse_post(value,{'filters':{'attachment_name':{'exclude_enabled':True,'exclude':['ORIGINAL']}}})
    assert result.assets[0].skip_reason=='keyword_excluded'


def test_links_preserve_occurrences_and_html_attributes():
    assert list(text_links('https://a.test/one https://a.test/a(b)). https://mega.nz/#!abc'))==[
        'https://a.test/one','https://a.test/a(b)','https://mega.nz/#!abc']
    collector=LinkCollector('https://www.fanbox.cc/@sample/posts/1')
    collector.add('/@other',source='body');collector.add('/@other',source='comment',comment_id='1')
    assert len(collector.links)==1 and len(collector.links[0].occurrences)==2
    assert clean_link('javascript:alert(1)','https://a.test') is None
    assert clean_link('//drive.google.com/a?x=1&amp;y=2','https://a.test')=='https://drive.google.com/a?x=1&y=2'
    assert clean_link('https://name:secret@a.test/','https://a.test') is None
    html=HtmlContent('<script>secret</script><style>secret</style><p>visible<br>text</p><iframe src="https://a.test/a"></iframe>')
    assert 'secret' not in html.text and html.references==['https://a.test/a']


@pytest.mark.parametrize('provider', ['youtube','vimeo','soundcloud','twitter','google_forms','gist','fanbox'])
def test_supported_embed_providers(provider):
    assert embed_url({'serviceProvider':provider,'contentId':'sample'}).startswith('https://')
    assert embed_url({'serviceProvider':'future','contentId':'sample'}) is None


@pytest.mark.parametrize('override,reason',[
    ({'include_paid':False},'fee_type'),({'fee':{'enabled':True,'op':'<=','value':499}},'fee_range'),
    ({'fee':{'enabled':True,'op':'=','value':499}},'fee_range'),
    ({'post_id':{'enabled':True,'op':'>','value':'1'}},'post_id'),
    ({'post_id':{'enabled':True,'op':'<','value':'1'}},'post_id'),
    ({'title':{'include_enabled':True,'include':['no-match']}},'keyword_required'),
    ({'title':{'exclude_enabled':True,'exclude':['work']}},'keyword_excluded'),
    ({'published':{'enabled':True,'start':'2026-10-21T00:00:00+09:00','end':'2026-10-22T00:00:00+09:00'}},'published_at'),
])
def test_filters(override,reason):
    assert post_reason(post(),normalize_options({'filters':override}))==reason


def test_filters_equal_time_and_or_semantics():
    options=normalize_options({'filters':{'title':{'include_enabled':True,'include':['absent','WORK']},
        'published':{'enabled':True,'start':'2026-10-20T10:00:00+09:00','end':'2026-10-20T10:00:00+09:00'}}})
    assert post_reason(post(),options) is None


@pytest.mark.parametrize('value',[
    [], '[]','{bad', {'unknown':1}, {'network':{'file_concurrency':4}}, {'network':{'api_interval_seconds':float('nan')}},
    {'content':{'comments':'no'}},{'filters':{'max_posts':0}},{'filters':{'post_id':{'value':'１'}}},
    {'content':{'body_formats':['exe']}},{'filters':{'title':{'include':[1]}}},
    {'quota':{'timezone':'NoSuch/Zone'}},{'naming':{'images':'a\nb'}},{'schema_version':2},
    {'filters':{'published':{'enabled':True}}}, {'filters':{'published':{'start':'2026-10-01'}}},
])
def test_invalid_options(value):
    with pytest.raises(FanboxError):normalize_options(value)


def test_config_copy_boolean_dates_and_schema_size():
    one=normalize_options({'content':{'comments':'false'}});one['filters']['title']['include'].append('x')
    assert not normalize_options()['filters']['title']['include']
    assert one['content']['comments'] is False
    assert normalize_options({'content':{'comments':'true'}})['content']['comments'] is True
    assert normalize_options({'filters':{'published':{'start':0}}})['filters']['published']['start'].startswith('1970-01-01')
    assert json.loads(options_json())['schema_version']==1
    with pytest.raises(FanboxError):normalize_options(' '*65537)


def test_legacy_58_keys_match_source_and_import():
    from pathlib import Path
    # The reference checkout is local/ignored; CI uses the maintained explicit key set.
    assert len(LEGACY_KEYS)==58
    plugin={'saveText':False,'saveLink':True,'textFormat':'txt','downloadThread':2,
            'idRangeInput':9007199254740993,'postDateStart':1514764800000,'postDateEnd':1893456000000,
            'bgDisplay':True,'bgOpacity':60,'bgPositionY':'center','unifiedURL':True,
            'whatIsNewFlag':'x','totalDownloadLimitByte':999,'totalDownloadLimit':10,
            'userSetName':'fanbox/{user}/{index}','future':1}
    options,report=import_plugin_settings(plugin)
    assert options['naming']['layout']=='legacy_full'
    assert options['content']['body_formats']==['txt'] and not options['content']['body']
    assert options['content']['raw_snapshot'] is False
    assert options['filters']['post_id']['value']=='9007199254740993'
    assert options['quota']['limit_gib']==10
    assert {r['key']:r['status'] for r in report}['totalDownloadLimitByte']=='derived'
    assert options['compat']['original_ui']['bgDisplay'] is True
    with pytest.raises(FanboxError):import_plugin_settings({'other-unknown':1})
