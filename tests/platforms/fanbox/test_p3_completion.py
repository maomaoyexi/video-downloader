import copy

from video_downloader.platforms.fanbox.models import Asset
from dataclasses import asdict
from .test_controller import setup_controller,preview


def test_manifest_and_name_preview_do_not_expose_resource_credentials(setup_controller):
    app,controller,config,*_=setup_controller
    state=preview(app,controller)
    state['scan']['posts'][0]['assets']=[asdict(Asset('a','image','sample','png',
        'https://downloads.fanbox.cc/a.png?private=secret'))]
    app.repository.save_job(state)
    result=controller.manifest(state['id'])
    assert len(result['posts'])==35 and 'private=secret' not in repr(result)
    assert result['posts'][0]['assets'][0]['path'].endswith('.png')
    old=copy.deepcopy(config)
    names=controller.naming_preview({'options':{'naming':{'images':'custom/{index}-{name}'}},'url':'https://sample.fanbox.cc'})
    assert 'custom/' in names['files'][0] and names['files'][1].endswith('.zip') and config==old


def test_retry_only_failed_resources_keeps_existing_archives(setup_controller):
    app,controller,*_=setup_controller
    state=preview(app,controller)
    app.run(state['id']);state=app.repository.job(state['id'])
    for post in state['scan']['posts'][:2]:
        post['assets']=[asdict(Asset('a','other','file','bin','https://downloads.fanbox.cc/file.bin'))]
    state['files']={'1':{'a:original':{'status':'completed','path':'keep.bin'}},
                    '2':{'a:original':{'status':'failed','error':{'code':'network_error'}}}}
    keep=app.root/'keep.bin';keep.write_bytes(b'keep')
    app.repository.save_job(state);controller.list()
    controller.action({'id':state['id'],'action':'retry_failed','version':state['version']})
    retry=app.repository.job(state['id'])
    assert retry['selection']=={'asset_ids':['2:a:original'],'post_ids':['2']}
    assert app.run(state['id'])['status']=='completed'
    saved=app.repository.job(state['id'])
    assert len(saved['archives'])==35 and saved['files']['2']['a:original']['status']=='completed'
    assert keep.read_bytes()==b'keep'


def test_resume_uses_explicit_policy_without_mutating_defaults(setup_controller):
    app,controller,config,*_=setup_controller
    state=preview(app,controller);options=copy.deepcopy(state['options']);original=copy.deepcopy(config)
    options['content']['image_fallback']='allow';options['quota']['limit_gib']=12
    options['naming']['images']='must-not-change';options['naming']['conflict']='overwrite'
    controller.list()
    controller.action({'id':state['id'],'action':'continue','version':state['version'],'options':options})
    saved=app.repository.job(state['id'])
    assert saved['options']['content']['image_fallback']=='allow' and saved['options']['quota']['limit_gib']==12
    assert saved['options']['naming']['images']==state['options']['naming']['images']
    assert saved['options']['naming']['conflict']=='overwrite' and config==original
