import io
import json
import runpy
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from video_downloader.core.constants import DEFAULT_CONFIG
from video_downloader.core.validation import validate_config
from video_downloader.platforms.fanbox import cli, runtime
from video_downloader.platforms.fanbox.auth import load_credentials
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.options import normalize_options, options_json
from video_downloader.services.storage import StorageService
from video_downloader.state.app_state import AppState
from .test_content import post
from .test_scan import FakeTransport


class ContextTransport(FakeTransport):
    def __enter__(self):return self
    def __exit__(self,*args):pass


def test_settings_and_presets_preserve_large_fanbox_json(tmp_path):
    state=AppState()
    storage=StorageService(tmp_path,state,validate_config,lambda *a:None,lambda *a:None)
    value=options_json({'filters':{'title':{'include':['Sample','日本語 💜']}}})
    config,errors=validate_config({'FANBOX_OPTIONS':value})
    assert not errors and len(config['FANBOX_OPTIONS'])>200
    state.replace_config(config);storage.save_config();storage.save_preset('FANBOX')
    assert storage.load_config()['FANBOX_OPTIONS']==config['FANBOX_OPTIONS']
    state.update_config({'FANBOX_OPTIONS':'{}'})
    assert storage.load_preset('FANBOX')['config']['FANBOX_OPTIONS']==config['FANBOX_OPTIONS']
    changed,errors=validate_config({'FANBOX_OPTIONS':'{"unexpected":1}'},config)
    assert errors and changed['FANBOX_OPTIONS']==config['FANBOX_OPTIONS']


def test_cli_scan_resume_and_summary_does_not_leak_content(tmp_path,monkeypatch,capsys):
    value=post();value['body']['text']='private-content https://example.test/a#private-key'
    transport=ContextTransport([[value]])
    monkeypatch.setattr(cli,'CurlTransport',lambda *a,**k:transport)
    output=tmp_path/'manifest.json'
    args=['https://sample.fanbox.cc/','--output',str(output),'--anonymous','--max-posts','1','--comments']
    assert cli.main(args,root=tmp_path)==0
    stdout=capsys.readouterr().out
    assert 'private-content' not in stdout and 'private-key' not in stdout
    assert json.loads(output.read_text())['posts'][0]['blocks'][0]['text'].startswith('private-content')
    transport.calls.clear()
    assert cli.main(args+['--resume'],root=tmp_path)==0
    assert not transport.calls


@pytest.mark.parametrize('extra', [
    ['--max-posts','0'],['--cookies','nonexistent-cookie-file'],['--options','missing-options'],
    ['--anonymous','--cookies','missing'],['--resume'],
])
def test_cli_bad_inputs_are_safe(tmp_path,capsys,extra):
    assert cli.main(['https://sample.fanbox.cc/','--output',str(tmp_path/'out.json')]+extra,root=tmp_path)==2
    assert json.loads(capsys.readouterr().out)['status']=='failed'


def test_cli_custom_options_plugin_and_partial(tmp_path,monkeypatch):
    options=tmp_path/'options.json';options.write_text('{"network":{"engine":"httpx"}}')
    plugin=tmp_path/'plugin.json';plugin.write_text('{"saveText":true,"textFormat":"txt"}')
    monkeypatch.setattr(cli,'HttpTransport',lambda *a,**k:ContextTransport([[post()]]))
    monkeypatch.setattr(cli,'CurlTransport',lambda *a,**k:ContextTransport([[post()]],details={'1':'challenge'}))
    base=['https://sample.fanbox.cc/','--output',str(tmp_path/'out.json'),'--anonymous']
    assert cli.main(base+['--options',str(options)],root=tmp_path)==0
    assert cli.main(base+['--import-plugin-settings',str(plugin)],root=tmp_path)==2
    assert cli.main(base+['--checkpoint',str(tmp_path/'out.json')],root=tmp_path)==2
    options.write_text('not-json')
    assert cli.main(base+['--options',str(options)],root=tmp_path)==2
    options.write_text(' '*65537)
    assert cli.main(base+['--options',str(options)],root=tmp_path)==2


def test_cli_interrupt_and_config_errors(tmp_path,monkeypatch):
    def interrupt(*a,**k):raise KeyboardInterrupt
    monkeypatch.setattr(cli,'CurlTransport',interrupt)
    assert cli.main(['https://sample.fanbox.cc/','--output',str(tmp_path/'out.json'),'--anonymous'],root=tmp_path)==130
    (tmp_path/'settings.ini').write_text('[broken')
    with pytest.raises(FanboxError):cli.read_config(tmp_path)
    (tmp_path/'settings.ini').write_text('[settings]\nthreads=999\n')
    with pytest.raises(FanboxError):cli.read_config(tmp_path)


def test_proxy_and_login_snapshot(tmp_path):
    config=dict(DEFAULT_CONFIG,PROXY_ENABLED=1)
    assert cli.proxy_from_config(config,normalize_options())=='http://127.0.0.1:7890'
    assert cli.proxy_from_config(config,normalize_options({'network':{'proxy_policy':'direct'}})) is None
    assert cli.credential_scope(load_credentials())=='anonymous'
    path=tmp_path/'cookies.txt';path.write_text('# Netscape HTTP Cookie File\n.fanbox.cc\tTRUE\t/\tTRUE\t0\tFANBOXSESSID\tprivate-value\n')
    assert 'private-value' not in cli.credential_scope(load_credentials(path))


def test_main_cli_route_and_module_help(monkeypatch):
    from video_downloader import cli as application_cli
    with patch.object(cli,'main',return_value=0) as scan:
        assert application_cli.run_cli(['--fanbox-scan','url','--output','out'])==0
        assert scan.call_args.args[0]==['url','--output','out']
    monkeypatch.setattr(sys,'argv',['fanbox','--help'])
    with pytest.raises(SystemExit) as exit_code:runpy.run_module('video_downloader.platforms.fanbox',run_name='__main__')
    assert exit_code.value.code==0


def test_runtime_health_missing_and_installer_command(monkeypatch):
    def missing(name):raise FanboxError('dependency_missing','missing')
    monkeypatch.setattr(runtime,'library',missing)
    assert runtime.health()=={'available':False}
    with patch.object(runtime.subprocess,'run') as run:
        runtime.install()
        command=run.call_args.args[0]
        assert '--require-hashes' in command and '--no-deps' in command
        assert 'https://pypi.org/simple' in command
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    with pytest.raises(FanboxError):runtime.install()


def test_runtime_import_failure_is_actionable(monkeypatch):
    with patch.object(runtime.importlib,'import_module',side_effect=ImportError):
        with pytest.raises(FanboxError,match='--install'):runtime.library('missing')
