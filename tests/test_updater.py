import hashlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

from video_downloader.services import updater as updater_module
from video_downloader.services.updater import UpdaterService


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
                updater_module.sys, "executable", os.path.join(temp_root, "视频下载工具v2.1.0-GUI.exe")
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
                updater_module.sys, "executable", os.path.join(temp_root, "视频下载工具v2.1.0-GUI.exe")
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
