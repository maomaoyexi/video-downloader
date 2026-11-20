import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from video_downloader.live.inspect import LiveInspector
from video_downloader.live.preferences import parse_platform_modes, resolve_platform_mode
from video_downloader.live.probe import (
    BilibiliProbe,
    LiveProbe,
    LiveStatus,
    ProbeError,
    ProbeService,
    TwitCastingProbe,
    YtDlpProbe,
)
from video_downloader.live.urls import TargetKind, classify_target
from video_downloader.live.wait import LiveWatchService, WatchJobStore, WatchStatus


class UrlClassifierTests(unittest.TestCase):
    def test_youtube_channel_event_and_archive(self):
        self.assertEqual(classify_target("https://www.youtube.com/@a/live").kind, TargetKind.CHANNEL)
        event = classify_target("https://www.youtube.com/live/abc123")
        self.assertEqual(event.kind, TargetKind.EVENT)
        self.assertEqual(event.stable_id, "abc123")
        self.assertEqual(classify_target("https://youtu.be/abc123").kind, TargetKind.EVENT)
        self.assertEqual(classify_target("https://www.youtube.com/watch?v=abc123").kind, TargetKind.EVENT)
        self.assertEqual(classify_target("https://www.youtube.com/@a/streams").kind, TargetKind.LIST)

    def test_bilibili_room_and_short_link(self):
        target = classify_target("https://live.bilibili.com/123")
        self.assertEqual(target.kind, TargetKind.CHANNEL)
        self.assertEqual(target.stable_id, "123")
        short = classify_target("https://b23.tv/abc")
        self.assertTrue(short.needs_expand)

    def test_twitch(self):
        self.assertEqual(classify_target("https://www.twitch.tv/xqc").kind, TargetKind.CHANNEL)
        self.assertEqual(classify_target("https://www.twitch.tv/videos/123").kind, TargetKind.ARCHIVE)
        self.assertEqual(classify_target("https://www.twitch.tv/directory").kind, TargetKind.LIST)

    def test_niconico_nicochannel_twitcasting_x_withny(self):
        self.assertEqual(classify_target("https://live.nicovideo.jp/watch/lv123").kind, TargetKind.EVENT)
        self.assertEqual(classify_target("https://nicochannel.jp/ch/live/sm1").kind, TargetKind.EVENT)
        self.assertEqual(classify_target("https://nicochannel.jp/ch/lives").kind, TargetKind.LIST)
        self.assertEqual(classify_target("https://twitcasting.tv/user").kind, TargetKind.CHANNEL)
        self.assertEqual(classify_target("https://twitcasting.tv/user/movie/123").kind, TargetKind.EVENT)
        self.assertEqual(classify_target("https://x.com/i/spaces/abc").kind, TargetKind.EVENT)
        self.assertEqual(classify_target("https://withny.com/@user").kind, TargetKind.CHANNEL)

    def test_unknown_url_is_not_watchable(self):
        target = classify_target("https://example.com/video/1")
        self.assertEqual(target.kind, TargetKind.UNKNOWN)
        self.assertFalse(target.can_watch)


class ProbeTests(unittest.TestCase):
    def test_bilibili_live(self):
        def http_json(url, **kwargs):
            return {
                "code": 0,
                "data": {
                    "room_id": 123,
                    "live_status": 1,
                    "live_time": "2026-10-23 20:00:00",
                    "title": "test",
                    "uname": "streamer",
                },
            }

        target = classify_target("https://live.bilibili.com/123")
        probe = BilibiliProbe(http_json=http_json).probe(target)
        self.assertEqual(probe.status, LiveStatus.LIVE)
        self.assertIn("bilibili:123:", probe.stream_instance_key)
        self.assertEqual(probe.title, "test")

    def test_bilibili_offline_and_rate_limit(self):
        def offline(url, **kwargs):
            return {"code": 0, "data": {"room_id": 123, "live_status": 0}}

        target = classify_target("https://live.bilibili.com/123")
        self.assertEqual(BilibiliProbe(http_json=offline).probe(target).status, LiveStatus.OFFLINE)

        def limited(url, **kwargs):
            return {"code": -352, "message": "风控"}

        with self.assertRaises(ProbeError) as raised:
            BilibiliProbe(http_json=limited).probe(target)
        self.assertTrue(raised.exception.retryable)

    def test_twitcasting_live(self):
        def http_json(url, **kwargs):
            return {"is_live": True, "movie": {"id": 99, "title": "live", "user": {"name": "u"}}}

        target = classify_target("https://twitcasting.tv/u")
        probe = TwitCastingProbe(http_json=http_json).probe(target)
        self.assertEqual(probe.status, LiveStatus.LIVE)
        self.assertEqual(probe.stable_id, "99")

    def test_ytdlp_upcoming_and_error_mapping(self):
        def runner(command, timeout):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    "id": "abc",
                    "live_status": "is_upcoming",
                    "release_timestamp": 2000,
                    "title": "soon",
                    "uploader": "u",
                }),
                stderr="",
            )

        target = classify_target("https://www.youtube.com/live/abc")
        probe = YtDlpProbe("yt-dlp", runner=runner).probe(target)
        self.assertEqual(probe.status, LiveStatus.UPCOMING)
        self.assertEqual(probe.scheduled_start, 2000)

        def offline_runner(command, timeout):
            return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: This channel is not live")

        with self.assertRaises(ProbeError) as raised:
            YtDlpProbe("yt-dlp", runner=offline_runner).probe(target)
        self.assertEqual(raised.exception.status, LiveStatus.OFFLINE)

    def test_probe_service_wraps_provider_errors(self):
        class Broken:
            def probe(self, target, timeout=20.0):
                raise ProbeError("network", retryable=True)

        target = classify_target("https://live.bilibili.com/1")
        service = ProbeService(ytdlp_path="", providers={"Bilibili": Broken()})
        probe = service.probe(target)
        self.assertEqual(probe.status, LiveStatus.ERROR)
        self.assertTrue(probe.retryable)


class PreferencesAndInspectTests(unittest.TestCase):
    def test_platform_mode_preferences(self):
        modes = parse_platform_modes('{"YouTube":"catch_up","Twitch":"bad","Bilibili":"live_edge"}')
        self.assertEqual(modes, {"YouTube": "catch_up", "Bilibili": "live_edge"})
        self.assertEqual(resolve_platform_mode("YouTube", "auto", modes), "catch_up")
        self.assertEqual(resolve_platform_mode("Twitch", "auto", modes), "auto")
        self.assertEqual(resolve_platform_mode("YouTube", "live_edge", modes), "live_edge")

    def _inspector(self, probe):
        class FakeProbe:
            def probe(self, target, **kwargs):
                return probe

        return LiveInspector(FakeProbe(), clock=lambda: 1000.0)

    def test_offline_supported_platform_recommends_wait(self):
        probe = LiveProbe("Bilibili", TargetKind.CHANNEL, "1", LiveStatus.OFFLINE)
        result = self._inspector(probe).inspect("https://live.bilibili.com/1")
        self.assertTrue(result["is_live_target"])
        self.assertTrue(result["can_wait"])
        self.assertEqual(result["recommended_mode"], "wait")
        self.assertNotIn("error", result)

    def test_live_started_shows_duration_and_modes(self):
        probe = LiveProbe(
            "YouTube", TargetKind.EVENT, "abc", LiveStatus.LIVE,
            started_at=900.0, title="live", uploader="u",
            catch_up_available=True, catch_up_reason="已验证 DASH",
        )
        result = self._inspector(probe).inspect("https://youtube.com/live/abc", "auto")
        self.assertEqual(result["status"], "live")
        self.assertEqual(result["live_duration_seconds"], 100)
        self.assertEqual(result["recommended_mode"], "catch_up")
        self.assertTrue(any(mode["value"] == "catch_up" and mode["available"] for mode in result["modes"]))

    def test_catch_up_unavailable_downgrades_with_warning(self):
        probe = LiveProbe("Bilibili", TargetKind.CHANNEL, "1", LiveStatus.LIVE, started_at=900.0)
        result = self._inspector(probe).inspect("https://live.bilibili.com/1", "catch_up")
        self.assertEqual(result["effective_mode"], "live_edge")
        self.assertTrue(result["downgraded"])
        self.assertIn("不支持追开播", result["warning"])

    def test_offline_unsupported_wait_returns_error(self):
        probe = LiveProbe("Bilibili", TargetKind.CHANNEL, "1", LiveStatus.OFFLINE)
        result = self._inspector(probe).inspect("https://withny.com/@user")
        self.assertFalse(result["can_wait"])
        self.assertIn("withny-dl", result["error"])

    def test_non_live_target_does_not_probe(self):
        class ExplodingProbe:
            def probe(self, target, **kwargs):
                raise AssertionError("should not probe")

        result = LiveInspector(ExplodingProbe(), clock=lambda: 1000.0).inspect(
            "https://example.com/video/1"
        )
        self.assertFalse(result["is_live_target"])


class WaitServiceTests(unittest.TestCase):
    def _probe(self, status, *, scheduled=None, title="t"):
        return LiveProbe(
            platform="Bilibili",
            target_kind=TargetKind.CHANNEL,
            stable_id="1",
            status=status,
            scheduled_start=scheduled,
            title=title,
        )

    def test_offline_then_live_triggers_once(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000.0]
            store = WatchJobStore(Path(directory) / "jobs.sqlite")
            probes = [self._probe(LiveStatus.OFFLINE), self._probe(LiveStatus.LIVE)]
            calls = []
            class FakeProbe:
                def probe(self, target, **kwargs):
                    return probes.pop(0)

            def on_live(job, probe):
                calls.append(job.id)
                return {"ok": True}

            service = LiveWatchService(
                store=store, probe_service=FakeProbe(), on_live=on_live,
                clock=lambda: now[0], jitter=lambda: 1.0, start_thread=False,
            )
            result = service.add("https://live.bilibili.com/1")
            self.assertTrue(result["waiting"])
            service.tick(wait=True)
            job = store.get(result["job"]["id"])
            self.assertEqual(job.status, WatchStatus.WAITING)
            next_probe = job.next_probe_at
            now[0] = next_probe + 1
            service.tick(now=now[0], wait=True)
            job = store.get(result["job"]["id"])
            self.assertEqual(job.status, WatchStatus.TRIGGERED)
            self.assertEqual(len(calls), 1)
            # 已触发任务不会再次启动
            service.tick(now=now[0] + 10000, wait=True)
            self.assertEqual(len(calls), 1)
            service.stop()

    def test_upcoming_schedules_near_window(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000.0]
            store = WatchJobStore(Path(directory) / "jobs.sqlite")
            probe = self._probe(LiveStatus.UPCOMING, scheduled=1600.0)

            class FakeProbe:
                def probe(self, target, **kwargs):
                    return probe

            service = LiveWatchService(
                store=store, probe_service=FakeProbe(), on_live=lambda job, probe: {"ok": True},
                clock=lambda: now[0], jitter=lambda: 1.0, start_thread=False,
            )
            result = service.add("https://live.bilibili.com/1")
            service.tick(wait=True)
            job = store.get(result["job"]["id"])
            self.assertEqual(job.status, WatchStatus.WAITING_NEAR)
            self.assertEqual(job.next_probe_at - now[0], 20.0)
            service.stop()

    def test_duplicate_and_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WatchJobStore(Path(directory) / "jobs.sqlite")

            class FakeProbe:
                def probe(self, target, **kwargs):
                    return LiveProbe("Bilibili", TargetKind.CHANNEL, "1", LiveStatus.OFFLINE)

            service = LiveWatchService(
                store=store, probe_service=FakeProbe(), on_live=lambda job, probe: {"ok": True},
                clock=lambda: 1000.0, jitter=lambda: 1.0, start_thread=False,
            )
            first = service.add("https://live.bilibili.com/1")
            second = service.add("https://live.bilibili.com/1")
            self.assertTrue(second.get("duplicate"))
            self.assertEqual(first["job"]["id"], second["job"]["id"])
            cancelled = service.cancel(first["job"]["id"])
            self.assertEqual(cancelled["job"]["status"], "cancelled")
            self.assertEqual(service.tick(wait=True), 0)
            service.stop()

    def test_restart_recovers_interrupted_probing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WatchJobStore(Path(directory) / "jobs.sqlite")

            class FakeProbe:
                def probe(self, target, **kwargs):
                    return LiveProbe("Bilibili", TargetKind.CHANNEL, "1", LiveStatus.OFFLINE)

            service = LiveWatchService(
                store=store, probe_service=FakeProbe(), on_live=lambda job, probe: {"ok": True},
                clock=lambda: 1000.0, jitter=lambda: 1.0, start_thread=False,
            )
            service.add("https://live.bilibili.com/1")
            # 模拟进程在 PROBING 状态崩溃
            store.recover_interrupted()
            recovered = store.list_recent()[0]
            self.assertEqual(recovered.status, WatchStatus.WAITING)
            service.stop()

    def test_probe_returning_live_after_stop_does_not_dispatch_and_can_resume(self):
        entered, release = threading.Event(), threading.Event()
        dispatched = []

        class SlowProbe:
            def probe(self, target, **kwargs):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test did not release the probe")
                return LiveProbe(target.platform, target.kind, target.stable_id, LiveStatus.LIVE)

        with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=1) as scheduler:
            store = WatchJobStore(Path(directory) / "jobs.sqlite")
            service = LiveWatchService(
                store=store, probe_service=SlowProbe(), on_live=lambda job, probe: dispatched.append(job.id),
                start_thread=False,
            )
            job = service.add("https://live.bilibili.com/1")["job"]
            tick = scheduler.submit(service.tick, wait=True)
            try:
                self.assertTrue(entered.wait(3))
                service.stop()
            finally:
                release.set()
            self.assertEqual(tick.result(timeout=3), 1)
            self.assertEqual(dispatched, [])
            reopened = LiveWatchService(
                store=store, probe_service=SlowProbe(), on_live=lambda job, probe: dispatched.append(job.id),
                start_thread=False,
            )
            try:
                self.assertTrue(reopened.add(job["url"])["duplicate"])
                self.assertEqual(reopened.list_jobs()[0]["id"], job["id"])
            finally:
                reopened.stop()


if __name__ == "__main__":
    unittest.main()
