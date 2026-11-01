"""RPlay CLI uses the same saved settings and recording lifecycle as WebUI."""

import os
import subprocess
import threading

from .rplay import AuthWorkspace, sanitize_output
from video_downloader.core.command import build_ytdlp_cmd
from video_downloader.core.platform import is_live_url
from video_downloader.core.validation import validate_config
from video_downloader.live import process
from video_downloader.live.modes import resolve_mode
from video_downloader.live.preferences import resolve_platform_mode
from video_downloader.live.runner import LiveRunner
from video_downloader.services.storage import StorageService
from video_downloader.state.app_state import AppState


def _kill(proc):
    if proc.poll() is None:
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill','/F','/T','/PID',str(proc.pid)],capture_output=True,
                               timeout=5,**process.hidden_options())
            else:
                import signal
                os.killpg(proc.pid,signal.SIGKILL)
        except (OSError,subprocess.TimeoutExpired):
            pass
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def _live(command, url, paths, suffix, config, mode):
    cancel=threading.Event()
    result={}
    runner=LiveRunner(paths,suffix,log=lambda text,level:print(sanitize_output(text),flush=True),
                      progress=lambda *args:None,publish_process=lambda proc:True,
                      clear_process=lambda proc:None,force_kill=_kill,emit_event=lambda *args:None)
    def record():
        try:
            result.update(runner.run(command,url=url,platform='Rplay',mode=mode,config=config,cancel=cancel))
        except Exception:
            result['status']='fail'
    # Ctrl+C reaches the CLI thread; the recording worker follows the shared
    # graceful-stop/finalization path before its credential workspace is closed.
    worker=threading.Thread(target=record,name='rplay-cli-recording')
    worker.start()
    cancelled=False
    while worker.is_alive():
        try:
            worker.join(.25)
        except KeyboardInterrupt:
            cancelled=True
            cancel.set()
    if result.get('report'):
        print('录制报告: '+result['report'])
    if cancelled:
        return 130
    return 0 if result.get('conclusion') in {'complete','from_earliest_available'} else 1


def download(url, paths, suffix):
    workspace=AuthWorkspace(paths)
    proc=None
    try:
        storage=StorageService(paths.app_dir,AppState(),validate_config,
                               lambda text,level:print(sanitize_output(text)),lambda *args:None)
        config=storage.load_config()
        config['PLATFORM']='Rplay'
        for name in ['yt-dlp','ffmpeg','ffprobe']:
            if not paths.executable(name,suffix).is_file():
                raise ValueError('缺少依赖 '+name)
        live=is_live_url(url,'Rplay')
        requested=resolve_platform_mode('Rplay',config.get('LIVE_MODE'),config.get('LIVE_PLATFORM_MODES'))
        mode=resolve_mode('Rplay',requested).value if live else None
        command=build_ytdlp_cmd(url,config,paths.app_dir,suffix,is_live=live,
                               platform_override='Rplay',live_mode=mode,rplay_auth_dir=workspace.directory(config))
        if live:
            return _live(command,url,paths,suffix,config,mode)
        proc=subprocess.Popen(command,cwd=str(paths.app_dir),env=paths.subprocess_env(),
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                              encoding='utf8',errors='replace',**process.hidden_options(console=True))
        try:
            for line in proc.stdout:
                print(sanitize_output(line),end='',flush=True)
            return 0 if proc.wait()==0 else 1
        finally:
            if proc.poll() is None:
                process.stop(proc,_kill)
            proc.stdout.close()
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print('Rplay 下载失败: '+sanitize_output(str(exc)))
        return 1
    finally:
        workspace.close()
