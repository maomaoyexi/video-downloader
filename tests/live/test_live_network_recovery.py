"""Opt-in wall-clock network outage test using actual live HLS and FFmpeg."""
from tests.helpers import PROJECT_ROOT
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from video_downloader.core.paths import AppPaths
from video_downloader.live.runner import LiveRunner

ROOT=PROJECT_ROOT


def verified_recovery_files(report, session):
    # The first part is created after the fixture's monotonic beginning.
    # A new part >=20s later cannot start before the all-endpoint 503 window.
    # It may start during the outage and wait: valid media then requires recovery.
    parts = session["parts"]
    cutoff = parts[0]["started_at"] + 20
    recovery_parts = [part for part in parts[1:] if part["started_at"] >= cutoff]
    return [file for file in report["files"] if file["valid"] and any(
        Path(file["path"]).is_relative_to(Path(part["directory"])) for part in recovery_parts)]


@pytest.mark.skipif(os.environ.get('LIVE_EXTENDED_TESTS')!='1',reason='set LIVE_EXTENDED_TESTS=1 for 145-second outage acceptance')
def test_real_live_hls_survives_90_second_complete_endpoint_outage(tmp_path):
    ffmpeg=ROOT/'dependency/ffmpeg.exe'
    ffprobe=ROOT/'dependency/ffprobe.exe'
    source=tmp_path/'source';source.mkdir()
    producer=subprocess.Popen([str(ffmpeg),'-v','error','-nostdin','-y','-re','-f','lavfi','-i',
        'testsrc2=size=160x90:rate=10','-re','-f','lavfi','-i','anoisesrc=seed=42:r=48000',
        '-t','170','-c:v','libx264','-preset','ultrafast','-g','20','-c:a','aac',
        '-f','hls','-hls_time','2','-hls_list_size','6','-hls_flags','delete_segments+program_date_time',
        str(source/'live.m3u8')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    cancel=threading.Event();server=None;timer=None
    try:
        deadline=time.monotonic()+15
        while not (source/'live.m3u8').exists() and time.monotonic()<deadline:time.sleep(.1)
        assert (source/'live.m3u8').exists()
        beginning=time.monotonic()
        hits={'offline':0,'before':0,'after':0}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                elapsed=time.monotonic()-beginning
                if 20<=elapsed<110:
                    hits['offline']+=1;self.send_error(503);return
                path=source/Path(self.path.split('?')[0]).name
                if not path.is_file():self.send_error(404);return
                hits['before' if elapsed<20 else 'after']+=1
                body=path.read_bytes()
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:self.wfile.write(body)
                except ConnectionError:pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        url=f'http://127.0.0.1:{server.server_port}/live.m3u8'
        paths=AppPaths(tmp_path/'app')
        paths.executable=lambda name,suffix:ROOT/'dependency'/(name+suffix)
        runner=LiveRunner(paths,'.exe',log=Mock(),progress=Mock(),publish_process=lambda p:True,
                          clear_process=Mock(),force_kill=lambda p:p.kill(),emit_event=Mock())
        engine=SimpleNamespace(name='network-fixture',events=None,close=lambda:None,stop_recording=lambda:None,
            command=lambda directory:[str(ffmpeg),'-v','warning','-nostdin','-y','-rw_timeout','2000000',
                '-reconnect','1','-reconnect_streamed','1','-reconnect_on_network_error','1',
                '-reconnect_on_http_error','503','-reconnect_delay_max','2','-reconnect_delay_total_max','120',
                '-i',url,'-c','copy',str(directory/'recording.mkv')])
        timer=threading.Timer(145,cancel.set);timer.start()
        with patch.object(runner,'_engine',return_value=engine):
            result=runner.run(['fixture'],url=url,platform='fixture',mode='live_edge',
                config={'LIVE_MIN_FREE_MB':64,'LIVE_MAX_RETRIES':5,'LIVE_WATCHDOG_SECONDS':60},cancel=cancel)
        import json
        report=json.loads(Path(result['report']).read_text(encoding='utf8'))
        session=json.loads(Path(result['report']).with_name('session.json').read_text(encoding='utf8'))
        assert all(hits[k]>0 for k in hits),hits
        assert report['conclusion']=='gaps',report
        assert verified_recovery_files(report,session),report
        assert result['output'] and Path(result['output']).is_file()
        print('OUTAGE_90S_ACCEPTANCE',hits,report['conclusion'],[(f['duration'],f['valid']) for f in report['files']])
    finally:
        if timer:timer.cancel()
        if server:server.shutdown();server.server_close()
        producer.kill();producer.wait(timeout=5)
