"""Lifecycle failure injection plus real FFmpeg/yt-dlp/HTTP integration."""
from __future__ import annotations
from tests.helpers import PROJECT_ROOT

import io
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from video_downloader.core.paths import AppPaths
from video_downloader.core.validation import validate_config
from video_downloader.live import process
from video_downloader.live.engines.bililive import BililiveEngine, EngineUnavailable, cookie_from_file, validate_install
from video_downloader.live.engines.ytdlp import YtDlpEngine
from video_downloader.live.events import BrecEvents
from video_downloader.live.integrity import IntegrityChecker
from video_downloader.live.runner import LiveRunner
from video_downloader.live.session import LiveSession, RecordingStore, atomic_json, media_files, redact_command, recover_interrupted

ROOT = PROJECT_ROOT


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def session(self):
        return LiveSession(self.root, "Bilibili", "live_edge", "https://user:pw@live.bilibili.com/3?token=secret")

    def runner(self):
        return LiveRunner(AppPaths(self.root), ".exe", log=Mock(), progress=Mock(), publish_process=Mock(return_value=True),
                          clear_process=Mock(), force_kill=Mock(), emit_event=Mock())

    def test_journal_is_atomic_and_redacts_credentials(self):
        s = self.session()
        _, part = s.part("test", ["app", "--cookie", "SESSDATA=secret", "--http-basic-pass=password",
                                  "https://name:pw@host/live?signature=secret"])
        text = (s.root / "session.json").read_text(encoding="utf-8")
        self.assertNotIn("secret", text)
        self.assertNotIn("password", text)
        self.assertEqual(s.data["url"], "https://live.bilibili.com/3")
        self.assertFalse((s.root / "session.json.tmp").exists())
        s.event("test", value=1)
        self.assertEqual(json.loads((s.root / "events.jsonl").read_text())["value"], 1)

    def test_transient_windows_share_violation_keeps_atomic_journal(self):
        target=self.root/'session.json'
        atomic_json(target,{'state':'old'})
        replace=os.replace
        attempts=[]
        def temporarily_locked(source,destination):
            attempts.append(1)
            if len(attempts)<3:
                self.assertEqual(json.loads(target.read_text()),{'state':'old'})
                raise PermissionError('sharing violation')
            return replace(source,destination)
        with patch('video_downloader.live.session.os.replace',side_effect=temporarily_locked):
            atomic_json(target,{'state':'new'})
        self.assertEqual(json.loads(target.read_text()),{'state':'new'})
        self.assertFalse(target.with_suffix('.json.tmp').exists())

    def test_part_retries_never_reuse_previous_directory(self):
        s = self.session()
        one, _ = s.part("yt-dlp", [])
        two, _ = s.part("yt-dlp", [], "watchdog")
        self.assertNotEqual(one, two)
        self.assertEqual(two.name, "part-002")
        self.assertEqual(s.data["retries"][0]["reason"], "watchdog")

    def test_restart_marks_abandoned_session_failed_and_preserves_media(self):
        s = self.session()
        part, _ = s.part("yt-dlp", [])
        file = part / "keep.flv"
        file.write_bytes(b"media")
        self.assertEqual(recover_interrupted(self.root), 0)
        s.data["owner_pid"] = None
        s.save()
        self.assertEqual(recover_interrupted(self.root), 1)
        self.assertEqual(json.loads((s.root / "integrity-report.json").read_text())["conclusion"], "failed")
        self.assertEqual(file.read_bytes(), b"media")

    def test_report_store_rejects_traversal_and_restores_recent_outcomes(self):
        s = self.session()
        s.part("yt-dlp", [])
        s.finish("user", {"files":[], "conclusion":"failed"})
        store = RecordingStore(self.root)
        self.assertIsNone(store.report("../cookies.txt"))
        self.assertIsNone(store.report("a" * 32))
        self.assertEqual(store.report(s.root.name)["conclusion"], "failed")
        self.assertEqual(store.recent()[0]["stop_reason"], "user")

    def test_authenticated_http_reports_and_invalid_job_id(self):
        from dataclasses import replace
        from tests.helpers.web import make_dependencies
        from video_downloader.web.handler import HttpService, create_handler
        s = self.session()
        s.finish("user", {"files":[], "conclusion":"failed"})
        store = RecordingStore(self.root)
        deps = replace(make_dependencies(threading.Event()), list_live_recordings=store.recent, get_live_report=store.report)
        service = HttpService(lambda:create_handler(deps),port=0)
        service.start()
        self.addCleanup(service.stop)
        opener = build_opener(ProxyHandler({}))
        with opener.open(Request(service.url+'/api/live/recordings',headers={'X-Session-Token':'test-token'}),timeout=3) as response:
            self.assertEqual(json.load(response)['recordings'][0]['job_id'],s.root.name)
        with opener.open(Request(service.url+'/api/live/report?job_id='+s.root.name,headers={'X-Session-Token':'test-token'}),timeout=3) as response:
            self.assertEqual(json.load(response)['conclusion'],'failed')
        for path,headers,code in [('/api/live/report?job_id='+s.root.name,{},403),
                                 ('/api/live/report?job_id=../cookies.txt',{'X-Session-Token':'test-token'},404)]:
            with self.assertRaises(HTTPError) as error:
                opener.open(Request(service.url+path,headers=headers),timeout=3)
            self.assertEqual(error.exception.code,code)

    def test_installer_rejects_unverified_archive_before_creating_destination(self):
        from scripts.install_bililive import install
        archive=self.root/'bad.zip'
        archive.write_bytes(b'unverified')
        with self.assertRaises(ValueError):
            install(archive,self.root/'installed')
        self.assertFalse((self.root/'installed').exists())

    def test_task_slots_remain_held_during_live_finalization(self):
        from tests.helpers.download import create_executor
        executor, _ = create_executor(self.root)
        handle = executor._download_manager.begin("single")
        executor._live_runner = Mock()
        executor.kill_process_tree = Mock()
        result = executor.stop_download()
        self.assertTrue(result["stopping"])
        self.assertTrue(executor._download_manager.snapshot()["running"])
        executor.kill_process_tree.assert_not_called()
        executor._finish(handle, None)

    def test_live_twitcasting_password_recovery_preserves_task_and_mode(self):
        from tests.helpers.download import create_executor
        executor, callbacks = create_executor(self.root)
        executor._on_finished=Mock()
        executor._wait_for_password=Mock(return_value='secret')
        handle=executor._download_manager.begin('single')
        failed={'status':'fail','title':'live','output':'','report':'failed.json',
                'error_lines':['ERROR: use --video-password for this stream']}
        success={'status':'success','title':'live','output':'recording.mp4','report':'report.json'}
        with patch('video_downloader.services.download_executor.LiveRunner') as runner:
            runner.return_value.run.side_effect=[failed,success]
            executor._run_single(handle,['yt-dlp','url'],'url','TwitCasting',True)
            command=runner.return_value.run.call_args.args[0]
            self.assertEqual(command[command.index('--video-password')+1],'secret')
            self.assertEqual(runner.return_value.run.call_args.kwargs['mode'],'live_edge')
        self.assertEqual(callbacks['add_history'].call_args.args[3],'success')
        executor._on_finished.assert_called_once_with(handle)

    def test_task_outcomes_preserve_stopped_timeout_and_gaps(self):
        from tests.helpers.tasks import make_manager, wait_until
        for outcome, expected in [("stopped","stopped"), ("timeout","timed_out"), ("gaps","partial"), ("earliest","partial"), ("fail","failed")]:
            manager, _, _, _ = make_manager()
            class Executor:
                def __init__(self, callbacks, done):
                    self.callbacks, self.done = callbacks, done
                def start_download(self, url, **kwargs):
                    self.callbacks.add_history(url,"live","Bilibili",outcome,"fixture.flv")
                    self.done(None)
                    return {"ok":True}
                def stop_download(self):
                    return {"ok":True}
            manager._executor_factory = lambda task,state,dm,callbacks,done:Executor(callbacks,done)
            try:
                manager.submit(["https://live.bilibili.com/3"])
                self.assertTrue(wait_until(lambda: manager.list_tasks() and manager.list_tasks()[0]["status"]==expected))
            finally:
                manager.stop()

    def test_ytdlp_isolates_output_without_changing_live_mode(self):
        cmd = YtDlpEngine(["yt-dlp", "--output", "old", "--paths=old", "--download-archive", "archive", "--live-from-start", "url"]).command(self.root)
        self.assertNotIn("old", cmd)
        self.assertNotIn("archive", cmd)
        self.assertIn("--live-from-start", cmd)
        self.assertIn("--no-simulate", cmd)

    def test_config_all_live_settings_validate_bounds(self):
        for key, low, high in [("LIVE_MAX_RETRIES", 0, 5), ("LIVE_WATCHDOG_SECONDS", 10, 600),
                               ("LIVE_MIN_FREE_MB", 64, 102400), ("LIVE_ESTIMATED_BITRATE_KBPS", 128, 100000)]:
            self.assertFalse(validate_config({key: low})[1])
            self.assertFalse(validate_config({key: high})[1])
            self.assertTrue(validate_config({key: high + 1})[1])
        for method in ("auto", "yt-dlp", "bililive-recorder"):
            self.assertFalse(validate_config({"LIVE_STREAM_METHOD": method})[1])

    def test_missing_or_modified_recorder_fails_validation(self):
        with self.assertRaises(EngineUnavailable):
            validate_install(self.root)
        (self.root / "file.dll").write_bytes(b"tampered")
        atomic_json(self.root / "manifest.json", {"version": "2.20.0", "files": {"file.dll": "bad"}})
        with self.assertRaises(EngineUnavailable):
            validate_install(self.root)

    def test_cookie_file_keeps_only_bilibili_and_ignores_expired(self):
        path = self.root / "cookies.txt"
        path.write_text("# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tFALSE\t9999999999\tSESSDATA\tx\n"
                        ".evilbilibili.com\tTRUE\t/\tFALSE\t9999999999\twrong\tx\n"
                        ".bilibili.com\tTRUE\t/\tFALSE\t1\texpired\tx\n")
        self.assertEqual(cookie_from_file(path), "SESSDATA=x")

    def test_unsupported_specialist_settings_are_explicit_fallbacks(self):
        for config in ({"PROXY_ENABLED": 1}, {"AUDIO_MODE": "2"}, {"CODEC": "h264"},
                       {"USE_COOKIES": 1, "COOKIE_MODE": 2}, {"_custom_live_args": "--verbose"}):
            runner = self.runner()
            runner.session = self.session()
            engine = runner._engine(["yt-dlp"], "Bilibili", "https://live.bilibili.com/3", config)
            self.assertIsInstance(engine, YtDlpEngine)
            self.assertIn("已降级", runner.log.call_args.args[0])

    def test_disk_preflight_failure_still_writes_report_without_spawning(self):
        runner = self.runner()
        with patch("video_downloader.live.runner.shutil.disk_usage", return_value=SimpleNamespace(free=1)), patch.object(process, "spawn") as spawn:
            result = runner.run(["app"], url="url", platform="Twitch", mode="live_edge", config={}, cancel=threading.Event())
        spawn.assert_not_called()
        report = json.loads(Path(result["report"]).read_text())
        self.assertEqual(report["stop_reason"], "disk_full")
        self.assertEqual(report["conclusion"], "failed")

    def test_cancel_before_spawn_still_writes_report(self):
        cancel = threading.Event()
        cancel.set()
        runner = self.runner()
        with patch.object(process, "spawn") as spawn:
            result = runner.run(["app"], url="url", platform="Twitch", mode="live_edge", config={}, cancel=cancel)
        spawn.assert_not_called()
        self.assertEqual(result["stop_reason"], "user")
        self.assertTrue(Path(result["report"]).exists())

    def test_disk_full_journal_failure_stops_child_before_releasing_process(self):
        runner = self.runner()
        proc = SimpleNamespace(stdout=io.BytesIO(b'LIVE_META:{"title":"fixture"}\n'), returncode=None)
        proc.poll = lambda: proc.returncode
        spawned = threading.Event()
        cleared_while_alive = []
        runner.clear_process = lambda child: cleared_while_alive.append(child.poll() is None)
        original_open = Path.open

        def open_file(path, mode="r", *args, **kwargs):
            if spawned.is_set() and path.is_relative_to(self.root) and any(flag in mode for flag in "wax"):
                raise OSError(28, "fixture disk full")
            return original_open(path, mode, *args, **kwargs)

        def spawn(*args, **kwargs):
            spawned.set()
            return proc

        def stop(child, force_kill):
            child.returncode = 1
            return True

        with patch.object(Path, "open", open_file), patch.object(process, "spawn", side_effect=spawn), \
             patch.object(process, "stop", side_effect=stop):
            with self.assertRaises(OSError):
                runner.run(["fixture"], url="fixture", platform="fixture", mode="live_edge",
                           config={}, cancel=threading.Event())
        self.assertIsNotNone(proc.poll(), "journal failure must not leave the recording child alive")
        self.assertEqual(cleared_while_alive, [False])

    def test_exit_zero_without_media_is_never_success(self):
        runner = self.runner()
        proc = SimpleNamespace(stdout=io.BytesIO(), poll=lambda: 0, wait=lambda timeout: 0, returncode=0)
        with patch.object(process, "spawn", return_value=proc):
            result = runner.run(["app"], url="url", platform="Twitch", mode="live_edge", config={}, cancel=threading.Event())
        self.assertEqual(result["status"], "fail")

    def test_generic_media_rename_cannot_create_a_late_per_file_comment_anchor(self):
        runner = self.runner()
        proc = SimpleNamespace(stdout=io.BytesIO(), poll=lambda: 0, wait=lambda timeout: 0, returncode=0)
        def spawn(*a, **kwargs):
            directory = runner.session.media / 'part-001'
            partial = directory / 'recording.mp4.part'
            partial.write_bytes(b'fixture')
            partial.rename(directory / 'recording.mp4')
            return proc
        lines, done = queue.Queue(), threading.Event()
        lines.put('LIVE_META:{"title":"fixture"}'); done.set()
        with patch.object(process, 'spawn', side_effect=spawn), patch.object(runner, '_reader', return_value=(lines, done, Mock())):
            result = runner.run(['app'], url='url', platform='fixture', mode='live_edge', config={}, cancel=threading.Event())
        report = json.loads(Path(result['report']).read_text(encoding='utf-8'))
        self.assertIn('media_started_at', runner.session.data['parts'][0])
        self.assertNotIn('anchor_utc', report['files'][0])
        self.assertFalse(runner.session.data['parts'][0]['media_anchors'])

    def test_crash_retries_are_bounded_and_keep_all_parts(self):
        runner = self.runner()
        def spawn(*a, **k):
            return SimpleNamespace(stdout=io.BytesIO(), poll=lambda: 9, wait=lambda timeout: 9, returncode=9)
        cancel = threading.Event()
        cancel.wait = Mock(return_value=False)
        with patch.object(process, "spawn", side_effect=spawn):
            result = runner.run(["app"], url="url", platform="Twitch", mode="live_edge", config={"LIVE_MAX_RETRIES": 2}, cancel=cancel)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(len(runner.session.data["parts"]), 3)
        self.assertEqual(runner.session.data["exit_codes"], [9, 9, 9])

    def test_graceful_stop_then_force_only_on_timeout(self):
        proc, kill = Mock(), Mock()
        proc.poll.return_value = None
        with patch.object(process, "interrupt") as interrupt:
            self.assertTrue(process.stop(proc, kill))
            interrupt.assert_called_once_with(proc)
        kill.assert_not_called()
        proc.wait.side_effect = subprocess.TimeoutExpired("app", 10)
        with patch.object(process, "interrupt"):
            self.assertFalse(process.stop(proc, kill))
        kill.assert_called_once_with(proc)

    def test_process_signal_failure_and_already_exited(self):
        proc = SimpleNamespace(pid=123, poll=lambda:0)
        kill = Mock()
        self.assertTrue(process.stop(proc, kill))
        process.interrupt(proc)
        kill.assert_not_called()
        if os.name == "nt":
            proc.poll = lambda:None
            with patch.object(process.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
                with self.assertRaises(OSError):
                    process.interrupt(proc)

    def test_posix_signal_uses_isolated_process_group(self):
        with patch.object(process.os, "name", "posix"), patch.object(process.os, "killpg", create=True) as kill:
            self.assertEqual(process.hidden_options(console=True), {"start_new_session":True})
            self.assertEqual(process.hidden_options(), {})
            process.interrupt(SimpleNamespace(pid=123, poll=lambda:None))
            kill.assert_called_once()

    def test_report_does_not_claim_segment_completeness(self):
        checker = IntegrityChecker("probe", "ffmpeg")
        valid = {"valid": True, "warnings": [], "path": "test"}
        with patch.object(checker, "inspect", return_value=valid):
            for mode, conclusion in [("live_edge", "complete"), ("catch_up", "from_earliest_available")]:
                report = checker.report(["test"], reason="ended", exit_codes=[0], mode=mode)
                self.assertEqual(report["conclusion"], conclusion)
                self.assertFalse(report["segment_completeness_verified"])
            for kw in ({"retries": 1}, {"forced": True}, {"webhook_complete": False}):
                self.assertEqual(checker.report(["test"], reason="ended", exit_codes=[0], mode="live_edge", **kw)["conclusion"], "gaps")
            self.assertEqual(checker.report(["test"], reason="crash", exit_codes=[9], mode="live_edge")["conclusion"], "failed")

    def test_metadata_reader_preserves_cr_lines_and_final_unterminated_line(self):
        lines, done, thread = LiveRunner._reader(SimpleNamespace(stdout=io.BytesIO(b"first\rsecond\nlast")))
        self.assertTrue(done.wait(1))
        thread.join()
        self.assertEqual([lines.get_nowait() for _ in range(lines.qsize())], ["first", "second", "last"])

    def test_reader_queue_is_bounded(self):
        lines, done, thread = LiveRunner._reader(SimpleNamespace(stdout=io.BytesIO(b"message\n" * 3000)))
        self.assertTrue(done.wait(1))
        thread.join()
        self.assertLessEqual(lines.qsize(), 512)

    def test_runner_user_timeout_watchdog_and_disk_full_stop_paths(self):
        for trigger in ("user", "timeout", "watchdog", "disk_full"):
            with self.subTest(trigger=trigger):
                runner = self.runner()
                counter = iter(range(0, 10000, 100))
                runner.clock = lambda: next(counter)
                cancel = threading.Event()
                proc = SimpleNamespace(stdout=Mock(), returncode=None)
                proc.poll = lambda: proc.returncode
                proc.wait = lambda timeout: proc.returncode
                lines, done = queue.Queue(), threading.Event()
                done.set()
                lines.put('LIVE_META:{"title":"fixture"}')
                reader = Mock()
                def publish(p):
                    if trigger == "user":
                        cancel.set()
                    return True
                runner.publish_process = publish
                def stop(p, kill):
                    p.returncode = 0
                    return True
                config = {"LIVE_MAX_RETRIES":0, "LIVE_WATCHDOG_SECONDS":10,
                          "LIVE_DOWNLOAD_TIMEOUT":1 if trigger == "timeout" else 0}
                free = [SimpleNamespace(free=10**15), SimpleNamespace(free=0 if trigger == "disk_full" else 10**15), SimpleNamespace(free=10**15)]
                def spawn(cmd, **kwargs):
                    if trigger == "timeout":
                        (Path(cmd[cmd.index("-P") + 1]) / "recording.flv").write_bytes(b"media")
                    return proc
                with patch.object(process, "spawn", side_effect=spawn), patch.object(process, "stop", side_effect=stop), \
                     patch.object(runner, "_reader", return_value=(lines, done, reader)), \
                     patch("video_downloader.live.runner.shutil.disk_usage", side_effect=free):
                    result = runner.run(["app"], url="url", platform="Twitch", mode="live_edge", config=config, cancel=cancel)
                events_file=runner.session.root/'events.jsonl'
                self.assertEqual(result["stop_reason"], trigger,
                                 events_file.read_text(encoding='utf-8') if events_file.exists() else runner.log.call_args_list)
                self.assertTrue(Path(result["report"]).exists())

    def test_brec_startup_fallback_and_crash_after_media(self):
        for has_media in (False, True):
            runner = self.runner()
            engine = Mock(name="brec")
            engine.name, engine.events = "bililive-recorder", None
            def command(directory):
                if has_media:
                    (directory / "record.flv").write_bytes(b"media")
                return ["brec"]
            engine.command = command
            codes = iter([9, 0])
            def spawn(*a, **k):
                rc = next(codes)
                return SimpleNamespace(stdout=io.BytesIO(), poll=lambda:rc, wait=lambda timeout:rc, returncode=rc)
            cancel = threading.Event()
            cancel.wait = Mock(return_value=False)
            with patch.object(runner, "_engine", return_value=engine), patch.object(process, "spawn", side_effect=spawn):
                result = runner.run(["app"], url="url", platform="Bilibili", mode="live_edge", config={}, cancel=cancel)
            self.assertEqual(len(runner.session.data["parts"]), 1 if has_media else 2)
            self.assertEqual(result["status"], "fail")

    def test_brec_command_auth_api_stop_and_cleanup(self):
        s = self.session()
        with patch("video_downloader.live.engines.bililive.BrecEvents") as events:
            events.return_value.url = "http://127.0.0.1:1234/token"
            engine = BililiveEngine("brec", s, 3, cookie="SESSDATA=secret")
            cmd = engine.command(s.media)
            self.assertIn("--mode", cmd)
            self.assertIn("--danmaku", cmd)
            self.assertIn("SESSDATA=secret", cmd)
            self.assertNotIn("secret", str(redact_command(cmd)))
            with patch.object(engine, "request") as request:
                engine.stop_recording()
                self.assertEqual(request.call_args_list[0].kwargs["data"], {"autoRecord":False})
                self.assertEqual(request.call_args_list[1].args, ("/api/room/3/stop",))
            response = Mock()
            response.__enter__ = Mock(return_value=SimpleNamespace(read=lambda:b'{"roomId":3}'))
            response.__exit__ = Mock(return_value=None)
            engine.opener.open = Mock(return_value=response)
            self.assertEqual(engine.request("/api/room/3", method="GET")["roomId"], 3)
            engine.close()
            events.return_value.close.assert_called_once()

    def test_valid_install_checks_binary_version(self):
        import hashlib
        binary = self.root / "BililiveRecorder.Cli.exe"
        binary.write_bytes(b"fixture")
        atomic_json(self.root / "manifest.json", {"version":"2.20.0", "files":{binary.name:hashlib.sha256(b"fixture").hexdigest()}})
        with patch("video_downloader.live.engines.bililive.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=b"2.20.0+build")):
            self.assertEqual(validate_install(self.root), binary)
        with patch("video_downloader.live.engines.bililive.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=b"3.0.0")):
            with self.assertRaises(EngineUnavailable):
                validate_install(self.root)

    def test_inspection_unavailable_probe_missing_file_and_incompatible_concat(self):
        checker = IntegrityChecker("missing", "missing")
        file = self.root / "media.flv"
        file.write_bytes(b"bad")
        self.assertFalse(checker.inspect(file)["valid"])
        self.assertIn("missing_file", checker.inspect(self.root / "missing.flv")["errors"])
        report = {"files":[{"valid":True,"streams":[{"codec_name":"h264"}]},
                           {"valid":True,"streams":[{"codec_name":"h265"}]}],"warnings":[]}
        checker.concatenate(self.session(),report)
        self.assertIn("concat_incompatible_tracks_parts_retained", report["warnings"])


class WebhookTests(unittest.TestCase):
    setUp = RecordingTests.setUp
    session = RecordingTests.session

    def receiver(self):
        s = self.session()
        receiver = BrecEvents(s, s.media, 3)
        self.addCleanup(receiver.close)
        return receiver

    def payload(self, kind, event_id="id", **fields):
        return {"EventId": event_id, "EventType": kind, "EventData": {"RoomId": 3, **fields}}

    def test_out_of_order_and_duplicate_events(self):
        r = self.receiver()
        r.accept(self.payload("SessionEnded", "end"))
        r.accept(self.payload("FileClosed", "closed", RelativePath="a.flv", Duration=1, FileSize=10))
        r.accept(self.payload("FileOpening", "opening", RelativePath="a.flv"))
        r.accept(self.payload("FileClosed", "closed", RelativePath="a.flv"))
        self.assertEqual(len(r.seen), 3)
        self.assertEqual(r.opened, r.closed)
        self.assertTrue(r.session_ended.is_set())

    def test_native_file_intervals_detect_reconnect_gap(self):
        r = self.receiver()
        self.assertFalse(r.timeline_has_gap())
        r.accept(self.payload("FileClosed", "one", RelativePath="1.flv", Duration=10,
                              FileOpenTime="2026-10-24T00:00:00+00:00", FileCloseTime="2026-10-24T00:00:10+00:00"))
        self.assertFalse(r.timeline_has_gap())
        r.accept(self.payload("FileClosed", "two", RelativePath="2.flv", Duration=10,
                              FileOpenTime="2026-10-24T00:01:10+00:00", FileCloseTime="2026-10-24T00:01:20+00:00"))
        self.assertTrue(r.timeline_has_gap())
        r.accept(self.payload("Error", "error"))
        r.accept(self.payload("StreamEnded", "stream"))
        self.assertTrue(r.failed.is_set())
        self.assertTrue(r.stream_ended.is_set())

    def test_wrong_room_traversal_and_unknown_event(self):
        r = self.receiver()
        for fields in ({"RelativePath": "../outside.flv"}, {"RoomId": 4}, {"RelativePath": str(self.root / "outside.flv")}):
            with self.assertRaises(ValueError):
                r.accept(self.payload("FileClosed", **fields))
        r.accept(self.payload("FutureEvent"))
        self.assertEqual(len(r.seen), 1)

    def test_actual_http_token_body_limit_and_events(self):
        r = self.receiver()
        opener = build_opener(ProxyHandler({}))
        data = json.dumps(self.payload("SessionEnded")).encode()
        request = Request(r.url, data=data, headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=3) as response:
            self.assertEqual(response.status, 204)
        self.assertTrue(r.session_ended.is_set())
        for url, body, headers, status in [
            (r.url + "wrong", data, {"Content-Type": "application/json"}, 403),
            (r.url, b"x" * 65537, {"Content-Type": "application/json"}, 413),
            (r.url, b"not json", {"Content-Type": "application/json"}, 400),
            (r.url, data, {"Content-Type": "text/plain"}, 415),
            (r.url, data, {"Content-Type": "application/json", "Origin": "http://evil"}, 403)]:
            with self.assertRaises(HTTPError) as error:
                opener.open(Request(url, data=body, headers=headers), timeout=3)
            self.assertEqual(error.exception.code, status)


def executable(name):
    bundled = ROOT / "dependency" / (name + (".exe" if os.name == "nt" else ""))
    return str(bundled) if bundled.is_file() else shutil.which(name)


@unittest.skipUnless(executable("ffmpeg") and executable("ffprobe") and executable("yt-dlp"), "external media tools not installed")
class RealMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.ffmpeg, cls.ffprobe, cls.ytdlp = (executable(n) for n in ("ffmpeg", "ffprobe", "yt-dlp"))
        cls.media = cls.root / "source.mp4"
        subprocess.run([cls.ffmpeg, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "8", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-g", "20", "-c:a", "aac", str(cls.media)],
                       check=True, capture_output=True, timeout=30, cwd=cls.root, **process.hidden_options())
        subprocess.run([cls.ffmpeg, "-v", "error", "-y", "-i", str(cls.media), "-c", "copy", "-f", "hls", "-hls_time", "2",
                        "-hls_list_size", "0", str(cls.root / "stream.m3u8")], check=True, capture_output=True, timeout=30, **process.hidden_options())
        subprocess.run([cls.ffmpeg, "-v", "error", "-y", "-i", str(cls.media), "-c", "copy", "-f", "hls", "-hls_time", "2",
                        "-hls_list_size", "0", "-hls_segment_type", "fmp4", str(cls.root / "fragmented.m3u8")],
                       check=True, capture_output=True, timeout=30, cwd=cls.root, **process.hidden_options())
        shutil.copyfile(cls.root / "init.mp4", cls.root / "init-second.mp4")
        cls.checker = IntegrityChecker(cls.ffprobe, cls.ffmpeg)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_container_tracks_packets_and_boundary_decode(self):
        result = self.checker.inspect(self.media)
        self.assertTrue(result["valid"], result)
        self.assertAlmostEqual(result["duration"], 8, delta=.2)
        self.assertEqual(len(result["timestamps"]), 2)

    def test_empty_missing_track_and_truncated_files(self):
        empty = self.root / "empty.mp4"
        empty.touch()
        self.assertIn("empty_file", self.checker.inspect(empty)["errors"])
        truncated = self.root / "truncated.mp4"
        truncated.write_bytes(self.media.read_bytes()[:100])
        self.assertFalse(self.checker.inspect(truncated)["valid"])
        audio = self.root / "audio.m4a"
        subprocess.run([self.ffmpeg, "-v", "error", "-y", "-i", str(self.media), "-vn", "-c:a", "copy", str(audio)],
                       check=True, capture_output=True, **process.hidden_options())
        self.assertFalse(self.checker.inspect(audio)["valid"])
        self.assertTrue(self.checker.inspect(audio, expected="a")["valid"])

    def test_concat_real_compatible_parts_retains_sources(self):
        session = LiveSession(self.root / "concat", "test", "live_edge", "url")
        paths = []
        for _ in range(2):
            directory, _ = session.part("test", [])
            file = directory / "part.mp4"
            shutil.copyfile(self.media, file)
            paths.append(file)
        report = self.checker.report(paths, reason="ended", exit_codes=[1, 0], mode="live_edge", retries=1)
        self.checker.concatenate(session, report)
        self.assertTrue(report["joined"]["valid"])
        self.assertAlmostEqual(report["joined"]["duration"], 16, delta=.3)
        self.assertTrue(all(p.exists() for p in paths))
        self.assertEqual(report["conclusion"], "gaps")

    def test_live_audio_export_and_catch_up_outcome(self):
        for audio_mode, mode in [("2","live_edge"), ("0","catch_up")]:
            paths = AppPaths(self.root / ("audio-run" + audio_mode))
            paths.executable = lambda name,suffix:Path({"ffmpeg":self.ffmpeg,"ffprobe":self.ffprobe}[name])
            runner = LiveRunner(paths, ".exe", log=Mock(), progress=Mock(), publish_process=lambda p:True,
                                clear_process=Mock(), force_kill=lambda p:p.kill(), emit_event=Mock())
            engine = Mock()
            engine.name, engine.events = "fixture", None
            engine.command = lambda directory:[self.ffmpeg,"-v","error","-nostdin","-y","-i",str(self.media),"-c","copy",str(directory/"recording.mkv")]
            with patch.object(runner,"_engine",return_value=engine):
                result=runner.run(["fixture"],url="fixture",platform="fixture",mode=mode,
                                  config={"AUDIO_MODE":audio_mode,"AUDIO_FORMAT":"mp3"},cancel=threading.Event())
            report=json.loads(Path(result["report"]).read_text())
            if audio_mode=="2":
                self.assertTrue(report["audio_exports"][0]["valid"])
            else:
                self.assertEqual(result["status"],"earliest")

    def serve(self, scenario):
        root = self.root
        class Handler(BaseHTTPRequestHandler):
            hits = 0
            def log_message(self, *args):
                pass
            def do_GET(self):
                name = self.path.split("?", 1)[0].lstrip("/")
                if scenario == "disconnect" and name == "stream1.ts":
                    self.close_connection = True
                    return
                if scenario == "token_expired" or (scenario == "missing_segment" and name == "stream1.ts"):
                    self.send_error(403 if scenario == "token_expired" else 404)
                    return
                if name == "stream.m3u8":
                    body = (root / name).read_bytes()
                    if scenario == "multiple_init_maps":
                        body = (root / "fragmented.m3u8").read_bytes().replace(
                            b'fragmented1.m4s', b'#EXT-X-MAP:URI="init-second.mp4"\nfragmented1.m4s')
                    if scenario == "sequence_jump":
                        body = body.replace(b"stream1.ts", b"stream2.ts")
                    if scenario == "sliding_window":
                        Handler.hits += 1
                        # A real live-style manifest advances, then emits ENDLIST.
                        lines = body.decode().splitlines()
                        chunks = [(lines[i], lines[i+1]) for i in range(len(lines)-1) if lines[i].startswith('#EXTINF')]
                        upto = min(len(chunks), Handler.hits + 1)
                        start = max(0, upto - 3)
                        body = ('#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:'+str(start)+'\n'+
                                ''.join(a+'\n'+b+'\n' for a,b in chunks[start:upto])+
                                ('#EXT-X-ENDLIST\n' if upto==len(chunks) else '')).encode()
                else:
                    file = root / name
                    if not file.is_relative_to(root) or not file.is_file():
                        self.send_error(404)
                        return
                    body = file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl" if name.endswith("m3u8") else "video/mp2t")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(lambda: thread.join(timeout=.1))
        return f"http://127.0.0.1:{server.server_port}/stream.m3u8"

    def test_real_hls_good_missing_segment_token_and_sequence_jump(self):
        for scenario in ("good", "missing_segment", "token_expired", "sequence_jump", "sliding_window", "disconnect", "multiple_init_maps"):
            with self.subTest(scenario=scenario):
                url = self.serve(scenario)
                paths = AppPaths(self.root / scenario)
                paths.executable = lambda name, suffix: Path({"ffmpeg":self.ffmpeg, "ffprobe":self.ffprobe}[name])
                runner = LiveRunner(paths, ".exe", log=Mock(), progress=Mock(), publish_process=lambda p:True,
                                    clear_process=Mock(), force_kill=lambda p:p.kill(), emit_event=Mock())
                command = [self.ytdlp, "--ignore-config", "--no-cache-dir", "--proxy", "", "--retries", "0",
                           "--fragment-retries", "0", "--abort-on-unavailable-fragment", "--ffmpeg-location", str(Path(self.ffmpeg).parent), url]
                result = runner.run(command, url=url, platform="fixture", mode="live_edge",
                                    config={"LIVE_MAX_RETRIES":0}, cancel=threading.Event())
                report = json.loads(Path(result["report"]).read_text())
                if scenario in {"good", "sliding_window"}:
                    self.assertEqual(report["conclusion"], "complete", report)
                else:
                    self.assertNotEqual(report["conclusion"], "complete", report)

    def test_primary_output_prefers_verified_part_after_recording_retry(self):
        paths = AppPaths(self.root / "verified-primary-output")
        paths.executable = lambda name, suffix: Path({"ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe}[name])
        runner = LiveRunner(paths, ".exe", log=Mock(), progress=Mock(), publish_process=lambda child: True,
                            clear_process=Mock(), force_kill=Mock(), emit_event=Mock())
        outputs = []

        def spawn(command, **kwargs):
            output = Path(command[command.index("-P") + 1]) / "recording.mp4"
            if outputs:
                shutil.copyfile(self.media, output)
                code = 0
            else:
                output.write_bytes(b"corrupt recording fixture")
                code = 9
            outputs.append(output)
            return SimpleNamespace(stdout=io.BytesIO(), poll=lambda: code,
                                   wait=lambda timeout: code, returncode=code)

        cancel = threading.Event()
        cancel.wait = Mock(return_value=False)
        with patch.object(process, "spawn", side_effect=spawn):
            result = runner.run(["fixture"], url="fixture", platform="fixture", mode="live_edge",
                                config={"LIVE_MAX_RETRIES": 1}, cancel=cancel)
        report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
        self.assertEqual([file["valid"] for file in report["files"]], [False, True], report)
        self.assertEqual(result["output"], str(outputs[1]))
        self.assertEqual(result["status"], "gaps")
        self.assertTrue(all(output.is_file() for output in outputs))

    @unittest.skipUnless(os.name == "nt", "Windows console integration")
    def test_actual_hidden_console_ctrl_c_closes_media(self):
        target = self.root / "stopped.mkv"
        proc = process.spawn([self.ffmpeg, "-v", "error", "-y", "-re", "-stream_loop", "-1", "-i", str(self.media),
                              "-c", "copy", str(target)], cwd=str(self.root))
        try:
            time.sleep(1.5)
            self.assertTrue(process.stop(proc, lambda p:p.kill(), timeout=10))
            self.assertTrue(self.checker.inspect(target)["valid"])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
