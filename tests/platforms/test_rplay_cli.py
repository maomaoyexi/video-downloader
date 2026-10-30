"""RPlay CLI shares saved auth settings and does not expose downloader secrets."""

import io
from unittest.mock import Mock, patch

import pytest

from video_downloader import cli
from video_downloader.core.paths import AppPaths
from video_downloader.platforms import rplay_cli

OID='a'*24


def paths(tmp_path):
    result=AppPaths(tmp_path)
    result.dependency_dir.mkdir()
    for name in ['yt-dlp','ffmpeg','ffprobe']:
        (result.dependency_dir/(name+'.exe')).touch()
    (tmp_path/'settings.ini').write_text('[settings]\nrplay_auth_source=firefox\nresolution=360\n',encoding='utf8')
    return result


def test_cli_dispatches_rplay_to_shared_adapter(tmp_path):
    with patch.object(cli,'_find_tool_dir',return_value=tmp_path),patch.object(rplay_cli,'download',return_value=0) as download:
        assert cli._cmd_download('https://rplay.live/play/'+OID)==0
    assert download.call_args.args[0].endswith(OID)


def test_vod_uses_saved_settings_cleans_credentials_and_redacts_output(tmp_path,capsys):
    app=paths(tmp_path)
    proc=Mock()
    proc.stdout=io.StringIO('https://pb.rplay.live/video?token=SECRET\nAuthorization: SECRET\n')
    proc.wait.return_value=0
    proc.poll.return_value=0
    with patch.object(rplay_cli.subprocess,'Popen',return_value=proc) as popen:
        assert rplay_cli.download('https://rplay.live/play/'+OID,app,'.exe')==0
    command=popen.call_args.args[0]
    from video_downloader.platforms.rplay import command_auth_options
    options=command_auth_options(command)
    from pathlib import Path
    assert options['auth']=='firefox' and not Path(options['auth_dir']).exists()
    assert 'rplay_resolution<=360' in command[command.index('-f')+1]
    assert 'SECRET' not in capsys.readouterr().out


def test_missing_dependencies_and_invalid_saved_live_mode_fail_safely(tmp_path):
    app=paths(tmp_path)
    (app.dependency_dir/'ffprobe.exe').unlink()
    assert rplay_cli.download('https://rplay.live/play/'+OID,app,'.exe')==1
    (app.dependency_dir/'ffprobe.exe').touch()
    (tmp_path/'settings.ini').write_text('[settings]\nlive_mode=catch_up\n',encoding='utf8')
    assert rplay_cli.download('https://rplay.live/live/'+OID,app,'.exe')==1


@pytest.mark.parametrize('conclusion,expected',[('complete',0),('gaps',1),('failed',1)])
def test_live_final_status_comes_from_integrity_report(tmp_path,conclusion,expected):
    app=paths(tmp_path)
    runner=Mock()
    runner.run.return_value={'conclusion':conclusion,'report':'TEST_REPORT'}
    with patch.object(rplay_cli,'LiveRunner',return_value=runner):
        assert rplay_cli.download('https://rplay.live/live/'+OID,app,'.exe')==expected
    assert runner.run.call_args.kwargs['mode']=='live_edge'
    assert runner.run.call_args.kwargs['config']['RPLAY_AUTH_SOURCE']=='firefox'


def test_live_ctrl_c_waits_for_recording_finalization(tmp_path):
    runner=Mock()
    def run(*args,**kw):
        assert kw['cancel'].wait(5)
        return {'conclusion':'complete'}
    runner.run.side_effect=run
    import threading
    real_join=threading.Thread.join
    calls=[]
    def join(thread,timeout):
        if not calls:
            calls.append(True)
            raise KeyboardInterrupt
        return real_join(thread,timeout)
    with patch.object(rplay_cli,'LiveRunner',return_value=runner),patch.object(threading.Thread,'join',join):
        assert rplay_cli._live(['yt-dlp'],'https://rplay.live/live/'+OID,AppPaths(tmp_path),'.exe',{},'live_edge')==130


def test_force_kill_falls_back_if_windows_tree_cleanup_fails():
    import os
    import subprocess
    if os.name!='nt':
        pytest.skip('Windows process tree')
    proc=Mock(pid=123,poll=Mock(return_value=None))
    with patch.object(rplay_cli.subprocess,'run',side_effect=subprocess.TimeoutExpired('taskkill',5)):
        rplay_cli._kill(proc)
    proc.kill.assert_called_once()
    proc.wait.assert_called_once_with(timeout=5)


def test_failed_live_worker_and_vod_interrupt_close_auth_and_processes(tmp_path):
    app=paths(tmp_path)
    with patch.object(rplay_cli,'LiveRunner',side_effect=None) as factory:
        factory.return_value.run.side_effect=RuntimeError('synthetic')
        assert rplay_cli.download('https://rplay.live/live/'+OID,app,'.exe')==1
    proc=Mock(poll=Mock(return_value=None))
    proc.stdout.__iter__=Mock(side_effect=KeyboardInterrupt)
    with patch.object(rplay_cli.subprocess,'Popen',return_value=proc),patch.object(rplay_cli.process,'stop') as stop:
        assert rplay_cli.download('https://rplay.live/play/'+OID,app,'.exe')==130
    stop.assert_called_once_with(proc,rplay_cli._kill)
    assert not list((app.download_dir/'.rplay-auth').glob('session-*'))
