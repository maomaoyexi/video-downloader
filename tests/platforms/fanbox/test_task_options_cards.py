import copy
import io
from urllib.parse import urlsplit

import pytest
from PIL import Image

from video_downloader.platforms.fanbox.archive import ArchiveApplication
from video_downloader.platforms.fanbox.client import FanboxClient
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.fan_cards import render_card
from video_downloader.platforms.fanbox.filters import post_reason
from video_downloader.platforms.fanbox.options import normalize_options
from video_downloader.platforms.fanbox.urls import validate_api_url
from .test_archive_io import Body
from .test_controller import setup_controller
from .test_content import post
from .test_scan import FakeTransport


def support():
    return {'plan':{'creatorId':'sample','user':{'name':'作者'},'title':'Support','fee':500,'coverImageUrl':None},
            'supportStartDatetime':'2026-10-01T00:00:00+09:00',
            'supporterCardImageUrl':'https://downloads.fanbox.cc/card.png',
            'supportTransactions':[{'supporter':{'name':'PRIVATE_USERNAME'},'paidAmount':999}]}


class Cards:
    def __init__(self,fail=False):self.calls=[];self.fail=fail
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def get_json(self,url):
        self.calls.append(url);path=urlsplit(url).path
        if path=='/plan.listSupporting':return {'body':{'plans':[{'creatorId':'sample'},{'creatorId':'sample'}]}}
        assert path=='/legacy/support/creator'
        if self.fail:raise FanboxError('not_found','No active support')
        return {'body':support()}


def test_card_only_uses_support_api_and_archive_transfer(tmp_path):
    image=io.BytesIO();Image.new('RGB',(80,50),'blue').save(image,format='PNG')
    transport=Cards();events=[]
    app=ArchiveApplication(tmp_path,transport_factory=lambda *a,**k:transport,
        binary_factory=lambda *a,**k:Body(image.getvalue()),publish=events.append)
    job=app.create('https://sample.fanbox.cc',{'fan_cards':{'only':True,'scope':'all_supporting','show_username':False},
        'network':{'api_interval_seconds':0,'file_start_interval_seconds':0}})
    preview=app.run(job['id'],preview=True)
    assert preview['status']=='preview_ready' and not transport.calls
    result=app.run(job['id'])
    assert result['status']=='completed' and result['counts']['fan_cards']==1
    state=app.repository.job(job['id']);card=state['fan_cards'][0]
    with Image.open(tmp_path/card['path']) as saved:assert saved.size==(1280,800) and saved.format=='PNG'
    assert (tmp_path/result['output']).is_file()
    assert 'PRIVATE_USERNAME' not in repr(state)
    assert [urlsplit(url).path for url in transport.calls]==['/plan.listSupporting','/legacy/support/creator']
    assert any(e['type']=='fanbox_log' and '粉丝卡保存完成' in e['data']['msg'] for e in events)


def test_missing_card_fails_without_claiming_success(tmp_path):
    app=ArchiveApplication(tmp_path,transport_factory=lambda *a,**k:Cards(True),binary_factory=lambda *a,**k:Body())
    job=app.create('https://sample.fanbox.cc',{'fan_cards':{'only':True},'network':{'api_interval_seconds':0}})
    result=app.run(job['id'])
    assert result['status']=='failed' and result['counts']['fan_cards_failed']==1 and not result['output']


@pytest.mark.parametrize('only',[False,True])
def test_no_supporting_cards_preserves_other_accessible_posts(tmp_path,only):
    class NoCards(Cards):
        def get_json(self,url):
            if urlsplit(url).path=='/plan.listSupporting':return {'body':{'plans':[]}}
            return FakeTransport([[post('text',{'text':'accessible body'})]]).get_json(url)
    app=ArchiveApplication(tmp_path,transport_factory=lambda *a,**k:NoCards(),binary_factory=lambda *a,**k:Body())
    job=app.create('https://sample.fanbox.cc',{'fan_cards':{'enabled':True,'only':only,'scope':'all_supporting'},
        'network':{'api_interval_seconds':0}})
    result=app.run(job['id'])
    assert result['status']==('failed' if only else 'partial')
    assert result['counts']['fan_cards_failed']==1
    assert bool(result['output']) is not only
    if not only:assert len(app.repository.job(job['id'])['archives'])==1


def test_card_schema_and_url_boundary():
    transport=Cards();client=FanboxClient(transport)
    assert client.supporting_creators()==['sample']
    assert client.fan_card('sample',show_username=False)['username']==''
    with pytest.raises(FanboxError):client.fan_card('other')
    assert validate_api_url('https://api.fanbox.cc/legacy/support/creator?creatorId=sample')
    for path in ('/legacy/support/creator/extra','//legacy/support/creator','/legacy/../support/creator'):
        with pytest.raises(FanboxError):validate_api_url('https://api.fanbox.cc'+path)


def test_card_image_rejects_html_and_oversized_background(tmp_path):
    card=FanboxClient(Cards()).fan_card('sample')
    path=tmp_path/'background';path.write_text('<html>secret</html>')
    with pytest.raises(FanboxError) as error:render_card(tmp_path/'card.png',card,path)
    assert error.value.code=='invalid_payload' and not (tmp_path/'card.png').exists()


def test_per_task_snapshot_isolated_from_defaults_and_replay(setup_controller):
    app,controller,config,launches,*_=setup_controller
    saved=copy.deepcopy(config)
    options=normalize_options({'filters':{'fee':{'enabled':True,'minimum':300,'maximum':1000}},'fan_cards':{'only':True}})
    data={'url':'https://sample.fanbox.cc','request_id':'isolated-options','options':options}
    result=controller.create(data);state=app.repository.job(result['job']['id'])
    assert state['options']['fan_cards']['enabled'] and config==saved
    assert controller.create(data)['replayed'] and len(launches)==1
    changed=copy.deepcopy(data);changed['options']['filters']['fee']['maximum']=1200
    with pytest.raises(FanboxError) as error:controller.create(changed)
    assert error.value.code=='request_conflict'
    assert len(controller.history('https://sample.fanbox.cc/posts')['runs'])==1
    assert controller.logs(state['id'])=={'logs':[]}


@pytest.mark.parametrize('amount,expected',[(0,'fee_range'),(300,None),(500,None),(1000,None),(1001,'fee_range')])
def test_fee_interval_is_inclusive(amount,expected):
    options=normalize_options({'filters':{'fee':{'enabled':True,'minimum':300,'maximum':1000}}})
    assert post_reason({'feeRequired':amount,'id':'1','title':''},options)==expected


def test_invalid_fee_interval_and_date_bounds():
    with pytest.raises(FanboxError):normalize_options({'filters':{'fee':{'minimum':1000,'maximum':300}}})
    options=normalize_options({'filters':{'published':{'enabled':True,'start':'2026-10-01T00:00:00Z','end':'2026-10-31T23:59:59Z'}}})
    value={'feeRequired':0,'id':'1','title':'','publishedDatetime':'2026-10-31T23:59:59Z'}
    assert post_reason(value,options) is None
    value['publishedDatetime']='2026-11-01T00:00:00Z'
    assert post_reason(value,options)=='published_at'
