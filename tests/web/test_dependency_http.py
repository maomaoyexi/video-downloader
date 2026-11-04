"""依赖管理的真实回环 HTTP：鉴权、类型和维护互斥。"""
from dataclasses import replace
import json
import threading
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tests.helpers.web import make_dependencies
from video_downloader.web.handler import HttpService, create_handler


class DependencyHttpTests(unittest.TestCase):
    def setUp(self):
        self.module = Mock()
        self.state = {"available": True, "running": False, "action": None, "groups": []}
        self.module.snapshot.side_effect = lambda **kwargs: {
            key: value for key, value in self.state.items()
            if kwargs.get("include_groups", True) or key != "groups"
        }
        self.module.check.return_value = {"ok": True}
        self.module.update.return_value = {"ok": True}
        self.module.cancel.return_value = {"ok": True}
        self.start = Mock(return_value={"ok": True})
        self.tool = Mock(return_value={"ok": True})
        self.inspect = Mock(return_value={"ok": True})
        self.playlist = Mock(return_value={"ok": True})
        self.dependencies = replace(make_dependencies(threading.Event()), dependency_manager=self.module,
                                    maintenance_lock=threading.RLock(), start_download=self.start,
                                    handle_tool_action=self.tool, inspect_live_url=self.inspect,
                                    fetch_bili_playlist=self.playlist)
        self.service = HttpService(lambda: create_handler(self.dependencies), port=0)
        self.url = self.service.start()

    def tearDown(self):
        self.service.stop()

    def request(self, path, payload=None, token=True):
        headers = {"Content-Type": "application/json", "Origin": self.url}
        if token:
            headers["X-Session-Token"] = "test-token"
        request = Request(self.url + path, headers=headers,
                          data=None if payload is None else json.dumps(payload).encode())
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            body = error.read()
            try:
                value = json.loads(body)
            except ValueError:
                value = {"error": body.decode("utf-8", errors="replace")}
            return error.code, value

    def test_status_and_actions_require_the_existing_session(self):
        for path, payload in (("/api/dependencies", None), ("/api/dependencies/check", {}),
                              ("/api/dependencies/update", {}),
                              ("/api/dependencies/cancel", {})):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, payload, token=False)[0], 403)
        self.module.check.assert_not_called()
        self.module.update.assert_not_called()

    def test_status_and_simple_actions_cross_the_module_interface(self):
        self.assertEqual(self.request("/api/dependencies"), (200, self.state))
        self.assertEqual(self.request("/api/dependencies/check", {})[0], 200)
        self.module.check.assert_called_once_with()
        self.assertEqual(self.request("/api/dependencies/update", {})[0], 200)
        self.module.update.assert_called_once_with()
        self.assertEqual(self.request("/api/dependencies/cancel", {})[0], 200)
        self.module.cancel.assert_called_once_with()

    def test_summary_poll_keeps_status_and_preserves_the_legacy_detailed_route(self):
        self.state.update(groups=[{"id": "core", "state": "missing"}], missing_count=1,
                          missing_files=["dependency/ffmpeg.exe"], recovery_required=True)
        status, summary = self.request("/api/dependencies?summary=1")
        self.assertEqual(status, 200)
        self.assertNotIn("groups", summary)
        self.assertEqual(summary["missing_count"], 1)
        self.assertEqual(summary["missing_files"], ["dependency/ffmpeg.exe"])
        self.assertTrue(summary["recovery_required"])
        self.module.snapshot.assert_called_once_with(include_groups=False)
        self.assertEqual(self.request("/api/dependencies"), (200, self.state))
        self.assertEqual(self.request("/api/dependencies?summary=0"), (200, self.state))

    def test_summary_queries_still_require_a_session_and_reject_unexpected_parameters(self):
        self.assertEqual(self.request("/api/dependencies?summary=1", token=False)[0], 403)
        for query in ("summary=", "summary=true", "summary=1&summary=0", "summary=1&path=example"):
            with self.subTest(query=query):
                self.assertEqual(self.request("/api/dependencies?" + query)[0], 400)
        self.module.snapshot.assert_not_called()

    def test_removed_selection_and_override_parameters_cannot_start_work(self):
        for path in ("check", "update", "cancel"):
            for changes in ({"groups": ["core"]}, {"full": True}, {"replace_changed": True}, {"url": "https://example.invalid/a.zip"}):
                with self.subTest(path=path, changes=changes):
                    self.assertEqual(self.request("/api/dependencies/" + path, changes)[0], 400)
        self.module.check.assert_not_called()
        self.module.update.assert_not_called()

    def test_removed_selected_install_route_is_unavailable(self):
        self.assertEqual(self.request("/api/dependencies/install", {"groups": ["core"]})[0], 404)
        self.module.install.assert_not_called()

    def test_install_blocks_new_download_and_exit_but_keeps_poll_and_cancel(self):
        self.state.update(running=True, action="install")
        for path, payload in (("/api/start", {"url": "https://example.com/video"}), ("/api/exit", {})):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, payload)[0], 409)
        self.start.assert_not_called()
        self.assertEqual(self.request("/api/dependencies")[0], 200)
        self.assertEqual(self.request("/api/dependencies/cancel", {})[0], 200)

    def test_read_only_check_does_not_block_download(self):
        self.state.update(running=True, action="check")
        self.assertEqual(self.request("/api/start", {"url": "https://example.com/video"})[0], 200)
        self.start.assert_called_once()

    def test_pending_recovery_blocks_new_work_but_allows_explicit_repair(self):
        self.state.update(recovery_required=True)
        self.assertEqual(self.request("/api/start", {"url": "https://example.com/video"})[0], 409)
        self.assertEqual(self.request("/api/dependencies/update", {})[0], 200)
        self.module.update.assert_called_once()

    def test_tool_aliases_cannot_bypass_pending_recovery(self):
        self.state.update(recovery_required=True)
        for action in ("update-ytdlp", "clean-temp"):
            with self.subTest(action=action):
                self.assertEqual(self.request("/api/tool", {"action": action})[0], 409)
        self.dependencies.handle_tool_action.assert_not_called()

    def test_dependency_probes_wait_for_install_or_recovery(self):
        for state in ({"running": True, "action": "install"}, {"running": False, "recovery_required": True}):
            self.state.update(state)
            for path in ("/api/live/inspect", "/api/bili-playlist"):
                with self.subTest(state=state, path=path):
                    self.assertEqual(self.request(path, {"url": "https://example.com/video"})[0], 409)
        self.dependencies.inspect_live_url.assert_not_called()
        self.dependencies.fetch_bili_playlist.assert_not_called()

    def test_install_admission_and_task_start_share_one_guard(self):
        entered, release, started = threading.Event(), threading.Event(), threading.Event()
        results = {}
        def install(*args, **kwargs):
            entered.set()
            release.wait(3)
            self.state.update(running=True, action="install")
            return {"ok": True}
        self.module.update.side_effect = install
        def start_request():
            started.set()
            results["start"] = self.request("/api/start", {"url": "https://example.com/video"})
        installer = threading.Thread(target=lambda: results.update(install=self.request("/api/dependencies/update", {})))
        downloader = threading.Thread(target=start_request)
        try:
            installer.start()
            self.assertTrue(entered.wait(2))
            downloader.start()
            self.assertTrue(started.wait(2))
        finally:
            release.set()
            installer.join(5)
            if downloader.ident is not None:
                downloader.join(5)
        self.assertEqual(results["install"][0], 200)
        self.assertEqual(results["start"][0], 409)
        self.start.assert_not_called()
