import json
import io
import queue
import threading
import time
import tempfile
import unittest
from dataclasses import replace
from contextlib import redirect_stderr
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

from video_downloader.state.app_state import AppState
from video_downloader.web.handler import HttpHandlerDependencies, HttpService, create_handler


from tests.helpers.web import FakeDownloadManager, FakeUpdater, make_dependencies


class HttpServiceTests(unittest.TestCase):
    def test_audio_converter_routes_validate_fields_and_ignore_client_codec(self):
        converter = Mock(return_value={"ok": True, "total": 1})
        stop = Mock(return_value={"ok": True})
        self.service.stop()
        self.dependencies = replace(self.dependencies, audio_convert=converter, stop_audio_tool=stop)
        self.service = HttpService(lambda: create_handler(self.dependencies), port=0)
        self.service.start()
        self.url = f"http://127.0.0.1:{self.service.port}"
        payload = {"dir": "中文 目录", "output_format": "alac", "codec": "injected", "del_src": False}
        status, body, _ = self.request('/api/audio-convert', method='POST', payload=payload)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['ok'])
        self.assertNotIn('codec', converter.call_args.kwargs)
        self.assertEqual(converter.call_args.args, ('中文 目录',))
        for invalid in ({"dir": 1}, {"recursive": "false"}, {"del_src": "false"}, {"bitrate": True}):
            with self.assertRaises(HTTPError) as error:
                self.request('/api/audio-convert', method='POST', payload=invalid)
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            self.request('/api/audio-convert', method='POST', payload=payload, token=False)
        self.assertEqual(error.exception.code, 403)
        self.request('/api/audio-stop', method='POST', payload={})
        stop.assert_called_once_with()

    def test_comment_reexport_requires_auth_and_valid_json_fields(self):
        export = Mock(return_value={"ok": True, "comments": {"status": "partial"}})
        self.service.stop()
        self.dependencies = replace(self.dependencies, export_live_comments=export)
        self.service = HttpService(lambda: create_handler(self.dependencies), port=0)
        self.service.start()
        self.url = f"http://127.0.0.1:{self.service.port}"
        payload={"job_id":"a"*32,"settings":{"LIVE_DANMAKU_OFFSET_MS":200}}
        status, body, _ = self.request('/api/live/comments-export', method='POST', payload=payload)
        self.assertEqual(status, 200)
        export.assert_called_once_with('a'*32, payload['settings'])
        for invalid in ({"job_id":1}, {"job_id":"a"*32,"settings":[]}):
            with self.assertRaises(HTTPError) as error:
                self.request('/api/live/comments-export', method='POST', payload=invalid)
            self.assertEqual(error.exception.code,400)
        with self.assertRaises(HTTPError) as error:
            self.request('/api/live/comments-export', method='POST', payload=payload, token=False)
        self.assertEqual(error.exception.code,403)

    def test_network_test_status_start_cancel_and_scoped_apply_routes(self):
        diagnostic = Mock()
        diagnostic.snapshot.return_value = {"running":False, "phase":"completed"}
        diagnostic.start.return_value = {"ok":True}
        diagnostic.cancel.return_value = {"ok":True}
        diagnostic.apply.return_value = {"ok":True}
        self.dependencies = replace(self.dependencies, network_diagnostics=diagnostic)
        self.service.stop()
        self.service = HttpService(lambda: create_handler(self.dependencies), port=0)
        self.url = self.service.start()
        status, body, _ = self.request("/api/network-test")
        self.assertEqual(json.loads(body)["phase"], "completed")
        for path in ("start", "cancel"):
            self.assertEqual(self.request("/api/network-test/" + path, method="POST", payload={})[0], 200)
        self.request("/api/network-test/apply", method="POST", payload={
            "mode":"reliable", "result_id":"measured-id", "settings":{"TASK_MAX_PARALLEL":999}})
        diagnostic.apply.assert_called_once_with("reliable", "measured-id")

    def test_network_test_routes_require_token_and_typed_mode(self):
        diagnostic = Mock()
        self.dependencies = replace(self.dependencies, network_diagnostics=diagnostic)
        self.service.stop()
        self.service = HttpService(lambda: create_handler(self.dependencies), port=0)
        self.url = self.service.start()
        with self.assertRaises(HTTPError) as error:
            self.request("/api/network-test/start", method="POST", payload={}, token=False)
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/network-test/apply", method="POST", payload={"mode":[], "result_id":"id"})
        self.assertEqual(error.exception.code, 400)
        diagnostic.start.assert_not_called()
        diagnostic.apply.assert_not_called()

    def test_task_password_route_accepts_explicit_skip_and_scoped_prompt(self):
        status, body, _ = self.request("/api/submit-password", method="POST", payload={
            "task_id": "task-1", "item_id": "item-1", "request_id": "prompt-1",
            "url": "https://twitcasting.tv/user/movie/1", "password": "", "skip": True,
        })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["request_id"], "prompt-1")

    def test_task_password_route_rejects_invalid_item_id_and_skip_types(self):
        for change in ({"item_id": []}, {"skip": "true"}):
            with self.assertRaises(HTTPError) as error:
                self.request("/api/submit-password", method="POST", payload={
                    "task_id": "task-1", "url": "url", "password": "password", **change,
                })
            self.assertEqual(error.exception.code, 400)

    def setUp(self):
        self.exit_event = threading.Event()
        self.dependencies = make_dependencies(self.exit_event)
        self.service = HttpService(lambda: create_handler(self.dependencies), port=0)
        self.url = self.service.start()

    def tearDown(self):
        self.service.stop()

    def request(self, path, method="GET", payload=None, token=True, content_type="application/json", raw_data=None):
        headers = {"Host": f"127.0.0.1:{self.service.port}"}
        if token:
            headers["X-Session-Token"] = "test-token"
        if content_type is not None:
            headers["Content-Type"] = content_type
        data = raw_data if raw_data is not None else None if payload is None else json.dumps(payload).encode()
        request = Request(self.url + path, data=data, headers=headers, method=method)
        with urlopen(request, timeout=2) as response:
            return response.status, response.read(), response.headers

    def test_port_zero_starts_on_assigned_port_and_stops(self):
        self.assertGreater(self.service.port, 0)
        self.assertEqual(self.url, f"http://127.0.0.1:{self.service.port}")
        self.service.stop()
        self.assertIsNone(self.service.port)

    def test_root_and_config_routes_use_injected_dependencies(self):
        status, body, _ = self.request("/", token=False)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"token=test-token")
        status, body, _ = self.request("/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "version": "1.9.5",
            "config": {"output_dir": "downloads"},
        })

    def test_current_command_route_uses_injected_dependency(self):
        status, body, headers = self.request("/api/current-command")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["command"], "yt-dlp https://example.com")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_help_error_manual_serves_fixed_document(self):
        from video_downloader.web.rendering import read_error_manual
        expected = read_error_manual()
        self.assertIsNotNone(expected)
        status, body, headers = self.request("/api/help/error-manual")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), expected)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_help_error_manual_requires_token_before_reading(self):
        with patch("video_downloader.web.handler.read_error_manual") as read:
            with self.assertRaises(HTTPError) as error:
                self.request("/api/help/error-manual", token=False)
            self.assertEqual(error.exception.code, 403)
            read.assert_not_called()

    def test_help_error_manual_reports_missing_document_without_local_path(self):
        with patch("video_downloader.web.handler.read_error_manual", return_value=None):
            with self.assertRaises(HTTPError) as error:
                self.request("/api/help/error-manual")
        self.assertEqual(error.exception.code, 404)
        result = json.loads(error.exception.read())
        self.assertIn("完整错误手册暂不可用", result["error"])
        self.assertNotIn("E:\\", result["error"])
        self.assertNotIn("C:\\", result["error"])

    def test_help_error_manual_rejects_client_file_or_url_parameters(self):
        with patch("video_downloader.web.handler.read_error_manual") as read:
            for query in ("path=..%2Fsettings.ini", "url=https%3A%2F%2Fexample.com", "path="):
                with self.subTest(query=query), self.assertRaises(HTTPError) as error:
                    self.request("/api/help/error-manual?" + query)
                self.assertEqual(error.exception.code, 400)
            read.assert_not_called()

    def test_expected_browser_disconnect_does_not_print_traceback(self):
        stderr = io.StringIO()
        try:
            raise ConnectionAbortedError(10053, "client disconnected")
        except ConnectionAbortedError:
            with redirect_stderr(stderr):
                self.service._server.handle_error(None, ("127.0.0.1", 12345))
        self.assertEqual(stderr.getvalue(), "")

    def test_unexpected_server_error_is_still_reported(self):
        stderr = io.StringIO()
        try:
            raise RuntimeError("unexpected")
        except RuntimeError:
            with redirect_stderr(stderr):
                self.service._server.handle_error(None, ("127.0.0.1", 12345))
        self.assertIn("unexpected", stderr.getvalue())

    def test_api_rejects_missing_token(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/config", token=False)
        self.assertEqual(raised.exception.code, 403)

    def test_api_rejects_non_ascii_token_without_dropping_connection(self):
        for path, headers in (
            ("/api/config", {"X-Session-Token": "invalid-\u00e9"}),
            ("/api/config?token=invalid-%E9%9B%AA", {}),
        ):
            with self.subTest(path=path):
                request = Request(self.url + path, headers=headers)
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request, timeout=2)
                self.assertEqual(raised.exception.code, 403)
        self.assertEqual(self.request("/api/config")[0], 200)

    def test_cover_route_serves_found_image(self):
        status, body, headers = self.request("/api/cover?path=known")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"JPEGDATA")
        self.assertEqual(headers["Content-Type"], "image/jpeg")

    def test_cover_route_returns_404_when_missing(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/cover?path=missing")
        self.assertEqual(raised.exception.code, 404)

    def test_post_route_and_exit_event(self):
        status, body, _ = self.request("/api/start", method="POST", payload={"url": "https://example.com"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"url": "https://example.com"})
        self.request("/api/exit", method="POST", payload={})
        self.assertTrue(self.exit_event.wait(1))

    def test_start_routes_forward_one_time_custom_args(self):
        status, body, _ = self.request("/api/start", method="POST", payload={
            "url": "https://example.com",
            "custom_args": "--retries 20",
        })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["custom_args"], "--retries 20")

        status, body, _ = self.request("/api/start-urls", method="POST", payload={
            "urls": ["https://example.com/1"],
            "custom_args": "--sleep-requests 1",
        })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["custom_args"], "--sleep-requests 1")

    def test_start_forwards_live_mode(self):
        status, body, _ = self.request("/api/start", method="POST", payload={
            "url": "https://live.bilibili.com/1",
            "live_mode": "live_edge",
        })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["live_mode"], "live_edge")

    def test_live_watch_routes(self):
        status, body, _ = self.request("/api/live/watch-jobs")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"jobs": []})
        status, body, _ = self.request("/api/live/watch-cancel", method="POST", payload={"id": "job-1"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["id"], "job-1")

    def test_task_routes(self):
        status, body, _ = self.request("/api/tasks")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"tasks": []})
        status, body, _ = self.request("/api/tasks/cancel", method="POST", payload={"id": "t1"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["id"], "t1")
        status, body, _ = self.request("/api/tasks/clear", method="POST", payload={})
        self.assertEqual(status, 200)

    def test_task_prompt_routing(self):
        status, body, _ = self.request(
            "/api/submit-password", method="POST",
            payload={"url": "https://example.com", "password": "pw", "task_id": "t1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["task_id"], "t1")
        status, body, _ = self.request(
            "/api/archive-choice", method="POST",
            payload={"request_id": "r1", "redownload": True, "task_id": "t1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["task_id"], "t1")

    def test_live_inspect_and_capabilities_routes(self):
        status, body, _ = self.request("/api/live/inspect", method="POST", payload={"url": "https://example.com"})
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["is_live_target"])
        status, body, _ = self.request("/api/live/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"platforms": {}})

    def test_start_rejects_oversized_custom_args(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/start", method="POST", payload={
                "url": "https://example.com",
                "custom_args": "x" * 4001,
            })
        self.assertEqual(raised.exception.code, 400)

    def test_download_subtitles_route_uses_injected_dependency(self):
        status, body, _ = self.request("/api/download-subtitles", method="POST", payload={
            "urls": ["https://youtube.com/watch?v=abc"],
            "subtitle_type": "manual",
            "subtitle_langs": "zh.*",
        })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "args": [["https://youtube.com/watch?v=abc"], "manual", "zh.*"]
        })

    def test_download_subtitles_route_rejects_non_string_urls(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/download-subtitles", method="POST", payload={"urls": [123]})
        self.assertEqual(raised.exception.code, 400)

    def test_withny_archive_route_uses_injected_dependency(self):
        status, body, _ = self.request("/api/start-withny-archive", method="POST", payload={})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True, "kind": "withny-archive"})

    def test_withny_live_route_uses_injected_dependency(self):
        status, body, _ = self.request("/api/start-withny-live", method="POST", payload={})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True, "kind": "withny-live"})

    def test_post_rejects_unsupported_media_type(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/start", method="POST", raw_data=b'{}', content_type="text/plain")
        self.assertEqual(raised.exception.code, 415)
        self.assertIn("Content-Type", json.loads(raised.exception.read())["error"])

    def test_post_rejects_invalid_json_and_non_object_json(self):
        with self.assertRaises(HTTPError) as malformed:
            self.request("/api/start", method="POST", raw_data=b'{')
        self.assertEqual(malformed.exception.code, 400)
        with self.assertRaises(HTTPError) as non_object:
            self.request("/api/start", method="POST", raw_data=b'[]')
        self.assertEqual(non_object.exception.code, 400)

    def test_post_rejects_invalid_field_type(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/start", method="POST", payload={"url": 123})
        self.assertEqual(raised.exception.code, 400)
        self.assertIn("url", json.loads(raised.exception.read())["error"])

    def test_sse_client_queue_is_bounded_and_drops_oldest_event(self):
        client = queue.Queue(maxsize=2)
        self.dependencies.app_state.add_sse_client(client, lambda: {"type": "ready"})
        self.dependencies.app_state.publish({"type": "first"})
        self.dependencies.app_state.publish({"type": "latest"})
        self.assertEqual(client.maxsize, 2)
        self.assertEqual(client.get_nowait()["type"], "first")
        self.assertEqual(client.get_nowait()["type"], "latest")

    def test_ready_is_enqueued_before_concurrent_broadcast(self):
        state = self.dependencies.app_state
        client = queue.Queue(maxsize=2)
        snapshot_started = threading.Event()
        allow_snapshot = threading.Event()

        def ready_event():
            snapshot_started.set()
            allow_snapshot.wait(1)
            return {"type": "ready"}

        register = threading.Thread(target=state.add_sse_client, args=(client, ready_event))
        register.start()
        self.assertTrue(snapshot_started.wait(1))
        publish = threading.Thread(target=state.publish, args=({"type": "progress"},))
        publish.start()
        allow_snapshot.set()
        register.join(1)
        publish.join(1)
        self.assertEqual(client.get_nowait()["type"], "ready")
        self.assertEqual(client.get_nowait()["type"], "progress")

    def test_save_config_failure_restores_previous_config(self):
        self.service.stop()
        dependencies = make_dependencies(self.exit_event)
        dependencies = replace(dependencies, save_config=Mock(side_effect=OSError("disk full")))
        self.service = HttpService(lambda: create_handler(dependencies), port=0)
        self.url = self.service.start()
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/save-config", method="POST", payload={"output_dir": "changed"})
        self.assertEqual(raised.exception.code, 500)
        self.assertEqual(dependencies.app_state.config_snapshot(), {"output_dir": "downloads"})

    def test_save_config_rejects_fractional_integer_without_changing_saved_settings(self):
        from video_downloader.core.constants import DEFAULT_CONFIG
        from video_downloader.core.validation import validate_config
        from video_downloader.services.storage import StorageService

        with tempfile.TemporaryDirectory() as directory:
            self.service.stop()
            state = self.dependencies.app_state
            state.replace_config(DEFAULT_CONFIG)
            storage = StorageService(Path(directory), state, validate_config, lambda *args: None, lambda *args: None)
            dependencies = replace(self.dependencies, validate_config=validate_config, save_config=storage.save_config)
            self.service = HttpService(lambda: create_handler(dependencies), port=0)
            self.url = self.service.start()
            self.assertEqual(self.request("/api/save-config", method="POST", payload={"THREADS": "8"})[0], 200)
            with self.assertRaises(HTTPError) as raised:
                self.request("/api/save-config", method="POST", payload={"THREADS": 2.5})
            self.assertEqual(raised.exception.code, 400)
            self.assertIn("THREADS", json.loads(raised.exception.read())["error"])
            self.assertEqual(json.loads(self.request("/api/config")[1])["config"]["THREADS"], 8)
            storage.load_config()
            self.assertEqual(json.loads(self.request("/api/config")[1])["config"]["THREADS"], 8)

    def test_reset_config_failure_restores_previous_config(self):
        self.service.stop()
        dependencies = make_dependencies(self.exit_event)
        dependencies = replace(
            dependencies,
            default_config={"output_dir": "default"},
            save_config=Mock(side_effect=OSError("disk full")),
        )
        self.service = HttpService(lambda: create_handler(dependencies), port=0)
        self.url = self.service.start()
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/reset-config", method="POST", payload={})
        self.assertEqual(raised.exception.code, 500)
        self.assertEqual(dependencies.app_state.config_snapshot(), {"output_dir": "downloads"})

    def test_sse_sends_ready_event(self):
        prompt = {"request_id": "pending", "url": "url", "count": 1, "expires_at": 123456}
        self.dependencies.app_state.archive_prompt = prompt
        request = Request(
            self.url + "/api/events?token=test-token",
            headers={"Host": f"127.0.0.1:{self.service.port}"},
        )
        with urlopen(request, timeout=2) as response:
            line = response.readline()
        self.assertTrue(line.startswith(b"data: "))
        event = json.loads(line.removeprefix(b"data: "))
        self.assertEqual(event["type"], "ready")
        self.assertEqual(event["data"]["generation"], 1)
        self.assertEqual(event["data"]["archive_prompt"], prompt)

    def test_stop_terminates_connected_sse_handler(self):
        request = Request(
            self.url + "/api/events?token=test-token",
            headers={"Host": f"127.0.0.1:{self.service.port}"},
        )
        response = urlopen(request, timeout=2)
        self.assertTrue(response.readline().startswith(b"data: "))
        started = time.monotonic()
        self.service.stop()
        elapsed = time.monotonic() - started
        response.close()
        self.assertLess(elapsed, 2)
        deadline = time.monotonic() + 2
        while self.dependencies.app_state.has_sse_clients() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.dependencies.app_state.has_sse_clients())


    def test_archive_choice_route_preserves_explicit_skip_and_redownload(self):
        for redownload in (False, True):
            status, body, _ = self.request("/api/archive-choice", method="POST", payload={
                "request_id": "choice-1", "redownload": redownload,
            })
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {"request_id": "choice-1", "redownload": redownload})

    def test_archive_choice_requires_boolean_decision_and_request_id(self):
        for payload in ({"request_id": "id", "redownload": "false"}, {"request_id": "id", "redownload": 1}, {"redownload": True}):
            with self.assertRaises(HTTPError) as error:
                self.request("/api/archive-choice", method="POST", payload=payload)
            self.assertEqual(error.exception.code, 400)

    def test_archive_choice_rejects_unauthenticated_requests(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/archive-choice", method="POST", token=False, payload={"request_id": "id", "redownload": True})
        self.assertEqual(error.exception.code, 403)

    def test_download_covers_route_uses_injected_dependency(self):
        status, body, _ = self.request("/api/download-covers", method="POST", payload={
            "urls": ["https://youtube.com/watch?v=abc"],
        })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "args": [["https://youtube.com/watch?v=abc"]]
        })

    def test_download_covers_route_rejects_non_string_urls(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/download-covers", method="POST", payload={"urls": [123]})
        self.assertEqual(raised.exception.code, 400)

if __name__ == "__main__":
    unittest.main()
