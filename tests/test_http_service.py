import json
import queue
import threading
import time
import unittest
from dataclasses import replace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from video_downloader.state.app_state import AppState
from video_downloader.web.handler import HttpHandlerDependencies, HttpService, create_handler


class FakeDownloadManager:
    def snapshot(self):
        return {"running": False, "phase": "idle", "generation": 1}


class FakeUpdater:
    def is_checking(self):
        return False

    def start_check_thread(self, silent):
        pass

    def snapshot(self):
        return {"checking": False}

    def do_update(self):
        return {"ok": True}


def make_dependencies(exit_event):
    app_state = AppState()
    app_state.replace_config({"output_dir": "downloads"})
    value = lambda: {"ok": True}
    named_value = lambda name: {"name": name}
    return HttpHandlerDependencies(
        session_token="test-token",
        version="1.9.5",
        default_config={"output_dir": "downloads"},
        app_state=app_state,
        download_manager=FakeDownloadManager(),
        updater=FakeUpdater(),
        render_html_page=lambda token: f"token={token}".encode(),
        serve_static_file=lambda path: (None, None),
        check_deps=lambda: {"yt-dlp": True},
        load_presets=lambda: {"default": {}},
        load_history=lambda: [{"url": "example"}],
        cancel_idle_timer=lambda: None,
        start_idle_timer=lambda: None,
        start_download=lambda url, bili_parts=None: {"url": url},
        batch_txt_download=value,
        start_urls_download=lambda urls: {"urls": urls},
        stop_download=value,
        fetch_bili_playlist=lambda url: {"parts": [], "total": 0},
        save_preset=named_value,
        load_preset=named_value,
        delete_preset=named_value,
        clear_history=value,
        find_cover=lambda path: (b"JPEGDATA", "image/jpeg") if path == "known" else (None, None),
        validate_config=lambda data, current: (data, []),
        save_config=lambda: None,
        handle_tool_action=named_value,
        browse_folder=value,
        update_ytdlp=value,
        clean_temp=value,
        gen_url_template=value,
        wav_to_mp3=lambda *args: {"args": args},
        request_exit=exit_event.set,
    )


class HttpServiceTests(unittest.TestCase):
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

    def test_api_rejects_missing_token(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/config", token=False)
        self.assertEqual(raised.exception.code, 403)

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


if __name__ == "__main__":
    unittest.main()
