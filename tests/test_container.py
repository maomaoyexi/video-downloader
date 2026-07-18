"""测试 AppContainer 依赖注入容器。"""
import unittest
from pathlib import Path

from video_downloader.container import AppContainer, WiredApp


class AppContainerTests(unittest.TestCase):
    def setUp(self):
        self.container = AppContainer(tool_dir=Path("."), exe_suffix=".exe")

    def test_wire_returns_wired_app(self):
        app = self.container.wire()
        self.assertIsInstance(app, WiredApp)

    def test_wired_app_has_all_attributes(self):
        app = self.container.wire()
        self.assertIsNotNone(app.http_service)
        self.assertIsNotNone(app.load_config)
        self.assertIsNotNone(app.check_deps)
        self.assertIsNotNone(app.request_exit)
        self.assertIsNotNone(app.app_state)
        self.assertIsNotNone(app.updater)
        self.assertIsNotNone(app.log)
        self.assertIsNotNone(app.cancel_idle_timer)
        self.assertIsNotNone(app.start_idle_timer)
        self.assertIsNotNone(app.main)

    def test_wired_app_http_service_starts_and_stops(self):
        app = self.container.wire()
        url = app.http_service.start()
        self.assertIsNotNone(url)
        self.assertIn("http://127.0.0.1:", url)
        app.http_service.stop()

    def test_log_writes_to_app_state(self):
        app = self.container.wire()
        app.log("test message", "info")
        self.assertGreater(len(app.app_state.log_history), 0)
        last_entry = app.app_state.log_history[-1]
        self.assertEqual(last_entry["msg"], "test message")
        self.assertEqual(last_entry["level"], "info")

    def test_check_deps_returns_expected_keys(self):
        app = self.container.wire()
        deps = app.check_deps()
        for key in ["yt-dlp", "ffmpeg", "ffprobe"]:
            self.assertIn(key, deps)

    def test_request_exit_sets_exit_condition(self):
        app = self.container.wire()
        # request_exit 不应抛出异常
        app.request_exit()

    def test_load_config_populates_app_state(self):
        app = self.container.wire()
        app.load_config()
        config = app.app_state.config_snapshot()
        self.assertIsInstance(config, dict)
        self.assertIn("PLATFORM", config)


if __name__ == "__main__":
    unittest.main()
