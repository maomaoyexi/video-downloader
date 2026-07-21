import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from video_downloader.state.app_state import AppState
from video_downloader.core.validation import validate_config
from video_downloader.core.constants import DEFAULT_CONFIG
from video_downloader.services.storage import StorageService


class StorageServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state = AppState()
        self.logs = []
        self.events = []
        self.storage = StorageService(
            tool_dir=Path(self.temp_dir.name),
            app_state=self.state,
            validate_config=validate_config,
            log=lambda message, level="info": self.logs.append((message, level)),
            emit_event=lambda event_type, data=None: self.events.append((event_type, data)),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_config_round_trip(self):
        self.state.replace_config(DEFAULT_CONFIG)
        self.state.update_config({"THREADS": 8})
        self.storage.save_config()
        restored = AppState()
        storage = StorageService(
            Path(self.temp_dir.name),
            restored,
            validate_config,
            lambda message, level="info": None,
            lambda event_type, data=None: None,
        )
        storage.load_config()
        self.assertEqual(restored.config_snapshot()["THREADS"], 8)

    def test_config_replace_failure_preserves_existing_file(self):
        self.state.replace_config(DEFAULT_CONFIG)
        self.storage.save_config()
        config_file = Path(self.temp_dir.name) / "settings.ini"
        original = config_file.read_bytes()
        self.state.update_config({"THREADS": 8})
        with patch("video_downloader.services.storage.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                self.storage.save_config()
        self.assertEqual(config_file.read_bytes(), original)
        self.assertEqual(list(Path(self.temp_dir.name).glob("settings.ini.*.tmp")), [])

    def test_config_snapshot_is_taken_inside_storage_lock(self):
        self.state.replace_config(DEFAULT_CONFIG)
        started = threading.Event()

        def save():
            started.set()
            self.storage.save_config()

        with self.state.config_lock:
            thread = threading.Thread(target=save)
            thread.start()
            self.assertTrue(started.wait(1))
            self.state.update_config({"THREADS": 8})
        thread.join(2)
        self.assertFalse(thread.is_alive())
        restored = AppState()
        StorageService(
            Path(self.temp_dir.name),
            restored,
            validate_config,
            lambda message, level="info": None,
            lambda event_type, data=None: None,
        ).load_config()
        self.assertEqual(restored.config_snapshot()["THREADS"], 8)

    def test_bad_ini_falls_back_to_defaults_and_warns(self):
        self.state.replace_config(DEFAULT_CONFIG)
        self.state.update_config({"THREADS": 8})
        config_file = Path(self.temp_dir.name) / "settings.ini"
        config_file.write_text("[settings\nthreads = 8", encoding="utf-8")
        loaded = self.storage.load_config()
        self.assertEqual(loaded, DEFAULT_CONFIG)
        self.assertTrue(any(level == "warn" and "已回退默认设置" in message for message, level in self.logs))

    def test_preset_round_trip(self):
        self.state.replace_config(DEFAULT_CONFIG)
        self.state.update_config({"RESOLUTION": "1080"})
        self.assertTrue(self.storage.save_preset("高清")["ok"])
        self.state.update_config({"RESOLUTION": "720"})
        result = self.storage.load_preset("高清")
        self.assertTrue(result["ok"])
        self.assertEqual(self.state.config_snapshot()["RESOLUTION"], "1080")
        self.assertTrue(self.storage.delete_preset("高清")["ok"])
        self.assertEqual(self.storage.load_presets(), {})

    def test_preset_replace_failure_preserves_existing_file(self):
        self.state.replace_config(DEFAULT_CONFIG)
        self.assertTrue(self.storage.save_preset("原预设")["ok"])
        preset_file = Path(self.temp_dir.name) / "presets.json"
        original = preset_file.read_bytes()
        with patch("video_downloader.services.storage.os.replace", side_effect=OSError("replace failed")):
            result = self.storage.save_preset("新预设")
        self.assertIn("error", result)
        self.assertEqual(preset_file.read_bytes(), original)
        self.assertEqual(list(Path(self.temp_dir.name).glob("presets.json.*.tmp")), [])

    def test_load_preset_save_failure_rolls_back_config(self):
        self.state.replace_config(DEFAULT_CONFIG)
        preset_file = Path(self.temp_dir.name) / "presets.json"
        preset = dict(DEFAULT_CONFIG)
        preset["THREADS"] = 8
        preset_file.write_text(json.dumps({"并发": preset}), encoding="utf-8")
        before = self.state.config_snapshot()
        with patch.object(self.storage, "save_config", side_effect=OSError("save failed")):
            result = self.storage.load_preset("并发")
        self.assertIn("error", result)
        self.assertEqual(self.state.config_snapshot(), before)
        self.assertTrue(any(level == "error" and "加载失败" in message for message, level in self.logs))

    def test_concurrent_preset_saves_keep_all_entries(self):
        self.state.replace_config(DEFAULT_CONFIG)
        barrier = threading.Barrier(9)
        results = []

        def save(index):
            barrier.wait()
            results.append(self.storage.save_preset(f"预设{index}"))

        threads = [threading.Thread(target=save, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(2)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertTrue(all(result.get("ok") for result in results))
        self.assertEqual(set(self.storage.load_presets()), {f"预设{index}" for index in range(8)})
        self.assertEqual(list(Path(self.temp_dir.name).glob("presets.json.*.tmp")), [])

    def test_history_limit_and_event(self):
        for index in range(505):
            self.storage.add_history(str(index), "", "YouTube")
        history = self.storage.load_history()
        self.assertEqual(len(history), 500)
        self.assertEqual(history[0]["url"], "504")
        self.assertEqual(self.events[-1][0], "history")
        self.assertEqual(len(self.events[-1][1]), 50)

    def test_clear_history_emits_empty_list(self):
        self.storage.add_history("url", "title", "YouTube")
        self.assertTrue(self.storage.clear_history()["ok"])
        self.assertEqual(self.storage.load_history(), [])
        self.assertEqual(self.events[-1], ("history", []))

    def test_add_history_records_filepath(self):
        self.storage.add_history("url", "title", "YouTube", "success", "C:/vids/a.mp4")
        self.assertEqual(self.storage.load_history()[0]["filepath"], "C:/vids/a.mp4")
        self.storage.add_history("url2", "t2", "YouTube")
        self.assertNotIn("filepath", self.storage.load_history()[0])

    def test_find_cover_returns_sibling_image(self):
        video = Path(self.temp_dir.name) / "YouTube" / "clip [abcdef].mp4"
        video.parent.mkdir(parents=True)
        video.with_suffix(".jpg").write_bytes(b"JPEG")
        data, mime = self.storage.find_cover(str(video))
        self.assertEqual(data, b"JPEG")
        self.assertEqual(mime, "image/jpeg")

    def test_find_cover_missing_returns_none(self):
        video = Path(self.temp_dir.name) / "no-thumb.mp4"
        self.assertEqual(self.storage.find_cover(str(video)), (None, None))
        self.assertEqual(self.storage.find_cover(""), (None, None))

    def test_find_cover_rejects_path_outside_tool_dir(self):
        outside = Path(self.temp_dir.name).parent / "evil.mp4"
        outside.with_suffix(".jpg").write_bytes(b"SECRET")
        try:
            self.assertEqual(self.storage.find_cover(str(outside)), (None, None))
        finally:
            outside.with_suffix(".jpg").unlink()


if __name__ == "__main__":
    unittest.main()
