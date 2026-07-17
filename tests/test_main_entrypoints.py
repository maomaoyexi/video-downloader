import ast
import unittest
from pathlib import Path


MAIN_SCRIPT = Path(__file__).parents[1] / "视频下载工具v1.9.5-GUI.py"


class MainEntrypointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(MAIN_SCRIPT.read_text(encoding="utf-8"))

    def function(self, name):
        matches = [node for node in self.tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
        return matches[-1]

    def test_start_download_is_thin_executor_wrapper(self):
        function = self.function("start_download")
        self.assertEqual(len(function.body), 1)
        call = function.body[0].value
        self.assertEqual(ast.unparse(call.func), "download_executor.start_download")

    def test_stop_download_is_thin_executor_wrapper(self):
        function = self.function("stop_download")
        self.assertEqual(len(function.body), 1)
        call = function.body[0].value
        self.assertEqual(ast.unparse(call.func), "download_executor.stop_download")

    def test_batch_entrypoint_keeps_read_and_save_then_delegates(self):
        function = self.function("batch_txt_download")
        calls = [ast.unparse(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)]
        self.assertIn("read_urls_file", calls)
        self.assertIn("save_config", calls)
        self.assertIn("download_executor.batch_download", calls)

    def test_request_exit_uses_shared_event(self):
        function = self.function("request_exit")
        calls = [ast.unparse(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)]
        self.assertIn("exit_event.set", calls)

    def test_http_service_is_composed_with_port_zero(self):
        function = self.function("create_http_service")
        returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
        expression = ast.unparse(returns[-1].value)
        self.assertIn("HttpService", expression)
        self.assertIn("port=0", expression)

    def test_broadcast_paths_use_shared_bounded_publish(self):
        for name in ("add_log", "emit_event", "update_progress", "broadcast_download_state", "request_exit"):
            function = self.function(name)
            calls = [ast.unparse(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)]
            self.assertIn("app_state.publish", calls)

    def test_main_starts_initial_idle_timer(self):
        function = self.function("main")
        statements = [ast.unparse(node) for node in function.body]
        server_start = next(index for index, statement in enumerate(statements) if "server_instance.start()" in statement)
        idle_start = next(index for index, statement in enumerate(statements) if statement == "start_idle_timer()")
        self.assertGreater(idle_start, server_start)


if __name__ == "__main__":
    unittest.main()
