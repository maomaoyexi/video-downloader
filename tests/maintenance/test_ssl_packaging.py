"""冻结构建必须携带构建解释器 SSL 模块依赖的证书策略资源。"""
import runpy
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from video_downloader.core.constants import VERSION


class SslPackagingTests(unittest.TestCase):
    def run_spec(self, root):
        hooks = ModuleType("PyInstaller.utils.hooks")
        hooks.collect_submodules = Mock(return_value=[])
        hooks.collect_data_files = Mock(return_value=[("public-ca.pem", "certifi")])
        hooks.collect_all = Mock(return_value=([], [], []))
        analysis = Mock(return_value=SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[]))
        spec = Path(__file__).resolve().parents[2] / f"视频下载工具{VERSION.split()[0]}-GUI.spec"
        modules = {"PyInstaller": ModuleType("PyInstaller"),
                   "PyInstaller.utils": ModuleType("PyInstaller.utils"),
                   "PyInstaller.utils.hooks": hooks}
        with patch.dict(sys.modules, modules), patch.object(sys, "path", list(sys.path)):
            runpy.run_path(str(spec), init_globals={
                "SPECPATH": str(root), "Analysis": analysis, "PYZ": Mock(), "EXE": Mock(),
            })
        return analysis.call_args.kwargs["datas"]

    def test_runtime_certificate_policy_is_bundled_next_to_frozen_ssl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdlib = root / "stdlib"
            stdlib.mkdir()
            policy = stdlib / "codex-rejected-cas.pem"
            policy.write_bytes(b"synthetic policy fixture; not used for a TLS connection")
            with patch.object(ssl, "__file__", str(stdlib / "ssl.py")):
                data = self.run_spec(root)
            self.assertIn((str(policy), "."), data)
            self.assertIn(("public-ca.pem", "certifi"), data)

    def test_interpreter_without_extra_policy_keeps_normal_certificate_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(ssl, "__file__", str(root / "ssl.py")):
                data = self.run_spec(root)
            self.assertFalse(any("codex-rejected-cas.pem" in str(source) for source, _ in data))
            self.assertIn(("public-ca.pem", "certifi"), data)


if __name__ == "__main__":
    unittest.main()
