"""回放真实执行器输出，校验估算进度与文件、阶段切换的边界。"""
import tempfile
import threading
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import Mock

from tests.helpers.download import CompletedProcess, create_executor


class DownloadProgressTests(unittest.TestCase):
    @staticmethod
    def progress_line(percent, stage="video", speed="1.0MiB/s", eta="00:30"):
        codecs = "none|mp4a" if stage == "audio" else "avc1|none"
        return (
            f"[download] {percent:.1f}% of Unknown at {speed} ETA {eta} "
            f"__VD_STAGE__{codecs}"
        )

    def replay(self, folder, outputs, *, batch=False, platform="YouTube", returncodes=None,
               retry=False):
        executor, callbacks = create_executor(Path(folder))
        done = threading.Event()
        done.set()
        readers = []
        for output in outputs:
            lines = Queue()
            for line in output:
                lines.put(line)
            readers.append((lines, done))
        executor._spawn = Mock(side_effect=[
            CompletedProcess(code) for code in (returncodes or [0] * len(outputs))
        ])
        executor._start_reader = Mock(side_effect=readers)
        executor._wait_for_password = Mock(return_value="fixture-password")
        if retry:
            executor._on_finished = Mock()
        handle = executor._download_manager.begin("batch" if batch else "single")
        count = 1 if retry else len(outputs)
        urls = [f"https://example.invalid/video/{index}" for index in range(count)]
        if batch:
            stats = {"total": len(urls), "current": 0, "ok": 0, "fail": 0, "skipped": 0}
            executor._run_batch(handle, urls, {"PLATFORM": platform}, stats)
        else:
            executor._run_single(handle, ["yt-dlp", urls[0]], urls[0], platform, False)
        progress = [
            call for call in callbacks["update_progress"].call_args_list
            if call.args and call.kwargs.get("stage") in {"video", "audio"}
            and not (len(call.args) > 1 and call.args[0] == 0)
        ]
        return executor, callbacks, progress

    def test_estimate_changes_do_not_decrease_progress_but_refresh_metrics(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as folder:
                _, _, progress = self.replay(folder, [[
                    self.progress_line(45),
                    self.progress_line(43, speed="2.0MiB/s", eta="00:40"),
                    self.progress_line(47),
                ]], batch=batch)
                self.assertEqual([call.args[0] for call in progress], [.45, .45, .47])
                self.assertEqual(progress[1].kwargs["speed"], "2.0MiB/s")
                self.assertEqual(progress[1].kwargs["eta"], "00:40")

    def test_media_stage_switch_resets_only_the_new_stage(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as folder:
                _, _, progress = self.replay(folder, [[
                    self.progress_line(85),
                    self.progress_line(5, "audio"),
                    self.progress_line(3, "audio"),
                    self.progress_line(8, "audio"),
                    self.progress_line(2),
                ]], batch=batch)
                self.assertEqual([call.args[0] for call in progress], [.85, .05, .05, .08, .02])
                self.assertEqual([call.kwargs["stage"] for call in progress],
                                 ["video", "audio", "audio", "audio", "video"])

    def test_new_file_with_same_stage_resets_progress(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as folder:
                _, _, progress = self.replay(folder, [[
                    "[download] Destination: first.mp4",
                    self.progress_line(90),
                    "[download] Destination: second.mp4",
                    self.progress_line(2),
                    self.progress_line(1),
                    self.progress_line(5),
                ]], batch=batch)
                self.assertEqual([call.args[0] for call in progress], [.9, .02, .02, .05])

    def test_repeated_destination_does_not_reset_the_same_file(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as folder:
                _, _, progress = self.replay(folder, [[
                    "[download] Destination: same.mp4",
                    self.progress_line(60),
                    "[download] Destination: same.mp4",
                    self.progress_line(58),
                ]], batch=batch)
                self.assertEqual([call.args[0] for call in progress], [.6, .6])

    def test_next_batch_item_starts_from_its_own_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, progress = self.replay(folder, [
                [self.progress_line(90), self.progress_line(88)],
                [self.progress_line(5), self.progress_line(3), self.progress_line(8)],
            ], batch=True)
            self.assertEqual([call.args[0] for call in progress], [.9, .9, .05, .05, .08])

    def test_independent_executors_do_not_share_a_progress_high_watermark(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, first = self.replay(folder, [[self.progress_line(90)]])
            _, _, second = self.replay(folder, [[self.progress_line(5), self.progress_line(3)]])
            self.assertEqual([call.args[0] for call in first], [.9])
            self.assertEqual([call.args[0] for call in second], [.05, .05])

    def test_new_process_retry_starts_from_its_own_progress(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as folder:
                executor, _, progress = self.replay(folder, [
                    [self.progress_line(90),
                     "ERROR: This video is protected by a password, use the --video-password option"],
                    [self.progress_line(5), self.progress_line(3)],
                ], batch=batch, platform="TwitCasting", returncodes=[1, 0], retry=True)
                self.assertEqual(executor._spawn.call_count, 2)
                self.assertEqual([call.args[0] for call in progress], [.9, .05, .05])

    def test_filename_and_diagnostic_percentages_are_not_download_progress(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as folder:
                _, _, progress = self.replay(folder, [[
                    "[download] Destination: 100% fun.mp4",
                    self.progress_line(45),
                    "WARNING: the title includes 99%",
                    self.progress_line(43),
                    '[Merger] Merging formats into "100% fun.mp4"',
                ]], batch=batch)
                self.assertEqual([call.args[0] for call in progress], [.45, .45])

    def test_external_downloader_and_plugin_progress_formats_remain_supported(self):
        for batch in (False, True):
            for prefix in ("[TwitCastingParallel]", "[TwitCastingParallel] [TwitCastingParallel]",
                           "custom-progress:"):
                with self.subTest(batch=batch, prefix=prefix), tempfile.TemporaryDirectory() as folder:
                    _, _, progress = self.replay(folder, [[
                        f"{prefix} 45.0% of 1.0MiB __VD_STAGE__avc1|none",
                        f"{prefix} 43.0% of 1.1MiB __VD_STAGE__avc1|none",
                        "[#aabbcc 500KiB/1MiB(48%) CN:4 DL:1MiB]",
                    ]], batch=batch)
                    self.assertEqual([call.args[0] for call in progress], [.45, .45, .48])


if __name__ == "__main__":
    unittest.main()
