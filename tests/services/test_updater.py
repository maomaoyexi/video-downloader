import hashlib
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from video_downloader.services import updater as updater_module
from video_downloader.services.updater import UpdaterService


MANUAL_UPDATE_URL = "https://github.com/maomaoyexi/video-downloader/releases/latest"


class FakeDownloadManager:
    def __init__(self, suspend_result=True):
        self.suspend_result = suspend_result
        self.suspended = False

    def suspend(self):
        self.suspended = self.suspend_result
        return self.suspend_result

    def resume(self):
        self.suspended = False

    def request_stop(self):
        raise AssertionError("测试中不应退出进程")


def create_updater(manager=None):
    return UpdaterService(
        download_manager=manager or FakeDownloadManager(),
        emit_event=lambda event_type, data=None: None,
        log=lambda message, level="info": None,
        broadcast_download_state=lambda: None,
        kill_process_tree=lambda process: None,
    )


class UpdaterServiceTests(unittest.TestCase):
    def test_check_responses_and_status_offer_official_manual_update_url(self):
        for scenario in ("network", "invalid_json", "current", "available", "checking"):
            with self.subTest(scenario=scenario):
                updater = create_updater()
                self.assertEqual(updater.snapshot()["manual_update_url"], MANUAL_UPDATE_URL)
                release = {
                    "tag_name": "v9.9.9" if scenario == "available" else "v1.0.0",
                    "html_url": "https://untrusted.invalid/manual-update",
                    "assets": [],
                }
                payload = None if scenario == "network" else "{" if scenario == "invalid_json" else json.dumps(release)
                updater._fetch_url = lambda *args, **kwargs: payload
                if scenario == "checking":
                    updater._check_lock.acquire()
                try:
                    result = updater.check_update()
                finally:
                    if scenario == "checking":
                        updater._check_lock.release()
                self.assertEqual(result["manual_update_url"], MANUAL_UPDATE_URL)
                self.assertEqual(updater.snapshot()["manual_update_url"], MANUAL_UPDATE_URL)
                if scenario in ("network", "invalid_json"):
                    self.assertTrue(result["error"])

    def test_update_refusals_include_official_manual_update_url(self):
        for scenario in ("downloading", "no_release", "source", "size", "digest", "download", "tasks"):
            with self.subTest(scenario=scenario):
                manager = FakeDownloadManager(suspend_result=scenario != "download")
                updater = create_updater(manager)
                if scenario != "no_release":
                    self.prepare_update(updater)
                if scenario == "downloading":
                    updater._update_status({"downloading": True})
                elif scenario == "source":
                    updater._update_status({"download_url": "https://untrusted.invalid/update.exe"})
                elif scenario == "size":
                    updater._update_status({"download_size": updater_module.MAX_UPDATE_SIZE + 1})
                elif scenario == "digest":
                    updater._update_status({"download_digest": "invalid"})
                elif scenario == "tasks":
                    updater._has_active_downloads = lambda: True
                with mock.patch.object(updater_module.threading, "Thread") as thread:
                    result = updater.do_update()
                self.assertTrue(result["error"])
                self.assertEqual(result["manual_update_url"], MANUAL_UPDATE_URL)
                thread.assert_not_called()
                if scenario == "tasks":
                    self.assertFalse(manager.suspended)

    def test_download_and_verification_failures_offer_manual_update_url(self):
        class ImmediateThread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

        for scenario in ("network", "size", "digest", "exe"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                updater = create_updater()
                content = b"MZ-update"
                self.prepare_update(updater, content)
                updater._emit_event = mock.Mock()
                updater._log = mock.Mock()
                temp_dir = os.path.join(directory, "update")

                def download(url, path, progress_callback=None):
                    if scenario == "network":
                        return False, "网络错误"
                    with open(path, "wb") as file:
                        file.write(content)
                    return True, {
                        "size": len(content) + (scenario == "size"),
                        "sha256": "0" * 64 if scenario == "digest" else hashlib.sha256(content).hexdigest(),
                    }

                updater._download_file = download
                updater._is_valid_exe = lambda path: scenario != "exe"
                with mock.patch.object(updater_module.tempfile, "mkdtemp", return_value=temp_dir), \
                        mock.patch.object(updater_module.threading, "Thread", ImmediateThread):
                    self.assertTrue(updater.do_update()["ok"])
                status = updater.snapshot()
                self.assertTrue(status["error"])
                self.assertEqual(status["manual_update_url"], MANUAL_UPDATE_URL)
                event_type, event = updater._emit_event.call_args.args
                self.assertEqual(event_type, "update_progress")
                self.assertEqual(event["error"], status["error"])
                self.assertEqual(event["manual_update_url"], MANUAL_UPDATE_URL)
                self.assertTrue(any(MANUAL_UPDATE_URL in call.args[0] for call in updater._log.call_args_list))
                self.assertFalse(status["downloading"])
                self.assertFalse(updater._download_manager.suspended)
                self.assertFalse(os.path.exists(temp_dir))

    def test_update_refuses_task_queue_and_releases_suspension(self):
        updater = create_updater()
        self.prepare_update(updater)
        updater._has_active_downloads = lambda: True
        result = updater.do_update()
        self.assertIn("任务队列", result["error"])
        self.assertFalse(updater._download_manager.suspended)

    def prepare_update(self, updater, content=b"MZ-update"):
        updater._update_status({
            "update_available": True,
            "latest_version": "v9.9.9",
            "download_url": "https://github.com/example.exe",
            "download_size": len(content),
            "download_digest": hashlib.sha256(content).hexdigest(),
        })

    def test_snapshot_returns_copy(self):
        updater = create_updater()
        snapshot = updater.snapshot()
        snapshot["checking"] = True
        self.assertFalse(updater.snapshot()["checking"])

    def test_release_info_prefers_gui_exe(self):
        updater = create_updater()
        release = updater._release_info({
            "tag_name": "v9.9.9",
            "body": "a" * 64 + "  tool-GUI.exe",
            "assets": [
                {"name": "cli.exe", "browser_download_url": "https://github.com/cli.exe", "size": 1},
                {"name": "tool-GUI.exe", "browser_download_url": "https://github.com/gui.exe", "size": 2},
            ],
        })
        self.assertEqual(release["download_url"], "https://github.com/gui.exe")
        self.assertEqual(release["download_size"], 2)
        self.assertEqual(release["download_digest"], "a" * 64)

    def test_check_update_uses_github_only(self):
        updater = create_updater()
        urls = []

        def fetch_url(url, timeout=10):
            urls.append(url)
            return '{"tag_name":"v2.0.0","assets":[]}'

        updater._fetch_url = fetch_url
        result = updater.check_update()
        self.assertFalse(result["has_update"])
        self.assertEqual(urls, ["https://api.github.com/repos/maomaoyexi/video-downloader/releases/latest"])

    def test_do_update_requires_available_release(self):
        updater = create_updater()
        self.assertEqual(updater.do_update()["error"], "没有可用的下载链接，请先检查更新")

    def test_do_update_rejects_invalid_digest(self):
        updater = create_updater()
        updater._update_status({
            "update_available": True,
            "download_url": "https://github.com/example.exe",
            "download_digest": "invalid",
        })
        self.assertIn("SHA-256", updater.do_update()["error"])

    def test_do_update_rejects_active_download(self):
        manager = FakeDownloadManager(suspend_result=False)
        updater = create_updater(manager)
        updater._update_status({
            "update_available": True,
            "download_url": "https://github.com/example.exe",
            "download_digest": "a" * 64,
        })
        self.assertEqual(updater.do_update()["error"], "请先停止当前下载任务再更新")

    def test_download_failure_removes_temp_directory(self):
        manager = FakeDownloadManager()
        updater = create_updater(manager)
        self.prepare_update(updater)
        temp_root = tempfile.mkdtemp()
        temp_dir = os.path.join(temp_root, "update")
        os.mkdir(temp_dir)
        updater._download_file = lambda url, path, progress_callback=None: (False, "网络错误")

        class ImmediateThread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

        try:
            with mock.patch.object(updater_module.tempfile, "mkdtemp", return_value=temp_dir), mock.patch.object(
                updater_module.threading, "Thread", ImmediateThread
            ):
                result = updater.do_update()
            self.assertTrue(result["ok"])
            self.assertFalse(os.path.exists(temp_dir))
            self.assertFalse(updater.snapshot()["downloading"])
            self.assertFalse(manager.suspended)
        finally:
            if os.path.isdir(temp_root):
                os.rmdir(temp_root)

    def test_download_thread_start_failure_rolls_back_state(self):
        manager = FakeDownloadManager()
        updater = create_updater(manager)
        self.prepare_update(updater)

        class FailingThread:
            def __init__(self, target, daemon):
                pass

            def start(self):
                raise RuntimeError("线程不可用")

        with mock.patch.object(updater_module.threading, "Thread", FailingThread):
            result = updater.do_update()
        self.assertIn("无法启动更新线程", result["error"])
        self.assertEqual(result["manual_update_url"], MANUAL_UPDATE_URL)
        self.assertFalse(updater.snapshot()["downloading"])
        self.assertFalse(manager.suspended)

    def test_windows_replace_bat_keeps_gbk_and_cleans_temp_directory(self):
        updater = create_updater()
        content = b"MZ-update"
        self.prepare_update(updater, content)
        temp_root = tempfile.mkdtemp()
        temp_dir = os.path.join(temp_root, "update")
        os.mkdir(temp_dir)

        def download_file(url, path, progress_callback=None):
            with open(path, "wb") as file:
                file.write(content)
            return True, {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}

        updater._download_file = download_file
        updater._is_valid_exe = lambda path: True
        targets = []

        class ControlledThread:
            def __init__(self, target, daemon):
                self.target = target
                targets.append(target)

            def start(self):
                if len(targets) == 1:
                    self.target()

        try:
            with mock.patch.object(updater_module.tempfile, "mkdtemp", return_value=temp_dir), mock.patch.object(
                updater_module.threading, "Thread", ControlledThread
            ), mock.patch.object(updater_module.sys, "frozen", True, create=True), mock.patch.object(
                updater_module.sys, "executable", os.path.join(temp_root, "视频下载工具v2.6.0-GUI.exe")
            ), mock.patch.object(updater_module.os, "name", "nt"):
                result = updater.do_update()
            self.assertTrue(result["ok"])
            bat_path = os.path.join(temp_dir, "_update_replace.bat")
            with open(bat_path, "r", encoding="gbk") as file:
                bat_content = file.read()
            self.assertIn("chcp 936 >nul", bat_content)
            self.assertIn("copy /y", bat_content)
            self.assertIn(f'del /q "{os.path.join(temp_dir, "_update_视频下载工具v9.9.9-GUI.exe")}"', bat_content)
            self.assertIn(f'rmdir "{temp_dir}"', bat_content)
            error_path = os.path.join(temp_dir, "_update_error.txt")
            self.assertEqual(bat_content.count(MANUAL_UPDATE_URL), 2)
            self.assertEqual(bat_content.count(r'start "" "%SystemRoot%\System32\notepad.exe"'), 2)
            self.assertGreaterEqual(bat_content.count(f'"{error_path}"'), 7)
            self.assertIn(f'del /q "{error_path}"', bat_content)
            self.assertIn("配套依赖包", bat_content)
            self.assertIn("settings.ini", bat_content)
            self.assertIn("download/", bat_content)
            self.assertNotIn("pause", bat_content)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_windows_handoff_thread_start_failure_cleans_and_rolls_back(self):
        manager = FakeDownloadManager()
        updater = create_updater(manager)
        content = b"MZ-update"
        self.prepare_update(updater, content)
        temp_root = tempfile.mkdtemp()
        temp_dir = os.path.join(temp_root, "update")
        os.mkdir(temp_dir)

        def download_file(url, path, progress_callback=None):
            with open(path, "wb") as file:
                file.write(content)
            return True, {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}

        updater._download_file = download_file
        updater._is_valid_exe = lambda path: True
        thread_count = 0

        class FailingHandoffThread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                nonlocal thread_count
                thread_count += 1
                if thread_count == 1:
                    self.target()
                else:
                    raise RuntimeError("线程不可用")

        try:
            with mock.patch.object(updater_module.tempfile, "mkdtemp", return_value=temp_dir), mock.patch.object(
                updater_module.threading, "Thread", FailingHandoffThread
            ), mock.patch.object(updater_module.sys, "frozen", True, create=True), mock.patch.object(
                updater_module.sys, "executable", os.path.join(temp_root, "视频下载工具v2.6.0-GUI.exe")
            ), mock.patch.object(updater_module.os, "name", "nt"):
                result = updater.do_update()
            self.assertTrue(result["ok"])
            self.assertFalse(os.path.exists(temp_dir))
            self.assertFalse(updater.snapshot()["update_done"])
            self.assertFalse(updater.snapshot()["downloading"])
            self.assertFalse(manager.suspended)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
