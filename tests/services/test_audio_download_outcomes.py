"""从下载入口验证额外音频输出的结果与已有媒体保留。"""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.helpers.download import DirectThread, create_executor


class AudioDownloadOutcomeTests(unittest.TestCase):
    def test_failed_audio_export_still_downloads_requested_subtitles(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
                    (root / name).touch()
                video = root / "video.mp4"
                video.write_bytes(b"retained downloaded video")
                subtitle = root / "video.en.vtt"
                executor, callbacks = create_executor(root)
                config = dict(executor._app_state.config_snapshot(), AUDIO_MODE="2", AUDIO_FORMAT="mp3",
                              DOWNLOAD_SUBTITLES=1)
                executor._app_state.config_snapshot = lambda: dict(config)
                callbacks["build_command"].side_effect = lambda url, **kwargs: (
                    ["yt-dlp", "--skip-download"] if kwargs.get("subtitle_only") else ["yt-dlp"])
                commands = []

                def spawn(command, **kwargs):
                    commands.append(command)
                    stream = stack.enter_context(tempfile.TemporaryFile())
                    if "--skip-download" in command:
                        subtitle.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nfixture\n", encoding="utf-8")
                        output, returncode = f"Writing video subtitles to: {subtitle}\n", 0
                    elif command[0] == "yt-dlp":
                        output, returncode = f'[Merger] Merging formats into "{video}"\n', 0
                    else:
                        output, returncode = "audio encoder failed\n", 1
                    stream.write(output.encode("utf-8"))
                    stream.seek(0)
                    return SimpleNamespace(stdout=stream, returncode=returncode,
                                           poll=lambda: returncode, args=command)

                with patch("video_downloader.services.download_executor.subprocess.Popen", side_effect=spawn), \
                        patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                    url = "https://www.youtube.com/watch?v=fixture"
                    urls = [url, "https://www.youtube.com/watch?v=second"] if batch else [url]
                    result = executor.batch_download(urls) if batch else executor.start_download(url)

                self.assertTrue(result["ok"])
                self.assertEqual(sum("--skip-download" in command for command in commands), len(urls))
                self.assertTrue(subtitle.is_file())
                self.assertEqual(video.read_bytes(), b"retained downloaded video")
                self.assertEqual(executor._app_state.batch_stats["ok"], 0)
                self.assertEqual(executor._app_state.batch_stats["fail"], len(urls))
                self.assertEqual(callbacks["add_history"].call_count, len(urls))
                self.assertEqual(callbacks["add_history"].call_args.args[3], "fail")
                self.assertFalse(executor._download_manager.snapshot()["running"])

    def test_cancel_during_audio_export_does_not_start_requested_subtitles(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
                    (root / name).touch()
                video = root / "video.mp4"
                video.write_bytes(b"retained downloaded video")
                executor, callbacks = create_executor(root)
                config = dict(executor._app_state.config_snapshot(), AUDIO_MODE="2", AUDIO_FORMAT="mp3",
                              DOWNLOAD_SUBTITLES=1)
                executor._app_state.config_snapshot = lambda: dict(config)

                def cancel_audio(*args, handle, **kwargs):
                    handle.cancel_event.set()
                    return False

                with tempfile.TemporaryFile() as stream:
                    stream.write(f'[Merger] Merging formats into "{video}"\n'.encode("utf-8"))
                    stream.seek(0)
                    downloaded = SimpleNamespace(stdout=stream, returncode=0, poll=lambda: 0, args=[])
                    with patch("video_downloader.services.download_executor.subprocess.Popen", return_value=downloaded) as spawned, \
                            patch("video_downloader.services.download_executor.threading.Thread", DirectThread), \
                            patch.object(executor, "_extract_audio_from_video", side_effect=cancel_audio), \
                            patch.object(executor, "_run_subtitle_sidecar") as subtitles:
                        url = "https://www.youtube.com/watch?v=fixture"
                        urls = [url, "https://www.youtube.com/watch?v=second"] if batch else [url]
                        result = executor.batch_download(urls) if batch else executor.start_download(url)

                self.assertTrue(result["ok"])
                self.assertEqual(spawned.call_count, 1)
                subtitles.assert_not_called()
                self.assertEqual(executor._app_state.batch_stats["ok"], 0)
                self.assertEqual(executor._app_state.batch_stats["fail"], 0)
                self.assertEqual(video.read_bytes(), b"retained downloaded video")
                self.assertFalse(executor._download_manager.snapshot()["running"])

    def test_audio_output_without_a_final_video_is_reported_as_failure(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
                    (root / name).touch()
                executor, _ = create_executor(root)
                config = dict(executor._app_state.config_snapshot(), AUDIO_MODE="2", AUDIO_FORMAT="mp3")
                executor._app_state.config_snapshot = lambda: dict(config)
                with tempfile.TemporaryFile() as stream:
                    downloaded = SimpleNamespace(stdout=stream, returncode=0, poll=lambda: 0, args=[])
                    with patch("video_downloader.services.download_executor.subprocess.Popen", return_value=downloaded), \
                            patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                        url = "https://www.youtube.com/watch?v=fixture"
                        result = executor.batch_download([url]) if batch else executor.start_download(url)
                self.assertTrue(result["ok"])
                self.assertEqual(executor._app_state.batch_stats["ok"], 0)
                self.assertEqual(executor._app_state.batch_stats["fail"], 1)

    def test_audio_output_preserves_apostrophes_in_downloaded_filename(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
                    (root / name).touch()
                video = root / "author's video.mp4"
                video.write_bytes(b"retained downloaded video")
                executor, callbacks = create_executor(root)
                config = dict(executor._app_state.config_snapshot(), AUDIO_MODE="2", AUDIO_FORMAT="mp3")
                executor._app_state.config_snapshot = lambda: dict(config)

                def spawn(command, **kwargs):
                    stream = stack.enter_context(tempfile.TemporaryFile())
                    if command[0] == "yt-dlp":
                        stream.write(f'[Merger] Merging formats into "{video}"\n'.encode("utf-8"))
                    else:
                        Path(command[-1]).write_bytes(b"exported audio")
                    stream.seek(0)
                    return SimpleNamespace(stdout=stream, returncode=0, poll=lambda: 0, args=command)

                with patch("video_downloader.services.download_executor.subprocess.Popen", side_effect=spawn), \
                        patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                    url = "https://www.youtube.com/watch?v=fixture"
                    result = executor.batch_download([url]) if batch else executor.start_download(url)

                self.assertTrue(result["ok"])
                self.assertTrue(video.with_suffix(".mp3").is_file())
                self.assertEqual(callbacks["add_history"].call_args.args[4], str(video))
                self.assertEqual(executor._app_state.batch_stats["ok"], 1)

    def test_audio_export_failure_is_not_reported_as_download_success(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
                    (root / name).touch()
                video = root / "video.mp4"
                video.write_bytes(b"retained downloaded video")
                executor, callbacks = create_executor(root)
                config = dict(executor._app_state.config_snapshot(), AUDIO_MODE="2", AUDIO_FORMAT="mp3")
                executor._app_state.config_snapshot = lambda: dict(config)

                def completed_process(output, returncode):
                    stream = stack.enter_context(tempfile.TemporaryFile())
                    stream.write(output.encode("utf-8"))
                    stream.seek(0)
                    return SimpleNamespace(stdout=stream, returncode=returncode,
                                           poll=lambda: returncode, args=[])

                downloaded = completed_process(f'[Merger] Merging formats into "{video}"\n', 0)
                audio_failed = completed_process("audio encoder failed\n", 1)
                with patch("video_downloader.services.download_executor.subprocess.Popen",
                           side_effect=[downloaded, audio_failed]), \
                        patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                    url = "https://www.youtube.com/watch?v=fixture"
                    result = executor.batch_download([url]) if batch else executor.start_download(url)

                self.assertTrue(result["ok"])
                self.assertEqual(executor._app_state.batch_stats["ok"], 0)
                self.assertEqual(executor._app_state.batch_stats["fail"], 1)
                self.assertEqual(callbacks["add_history"].call_args.args[3], "fail")
                self.assertEqual(video.read_bytes(), b"retained downloaded video")
                self.assertFalse(executor._download_manager.snapshot()["running"])
