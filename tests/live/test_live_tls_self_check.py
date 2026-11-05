"""TLS 自检须初始化真实默认上下文，不能只确认 CA 文件存在。"""
import ssl
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from video_downloader.live.danmaku.dependencies import self_check


class LiveTlsSelfCheckTests(unittest.TestCase):
    def setUp(self):
        # 其他自检沿用实际协议/序列化库；凭据保护只处理本测试自有字节。
        support = SimpleNamespace(
            decompress_session=lambda value: value[2:],
            protect=lambda value, decrypt=False: value[::-1],
        )
        auth = patch("video_downloader.platforms.rplay.auth_support", return_value=support)
        auth.start()
        self.addCleanup(auth.stop)

    def assert_existing_checks_remain(self, result):
        for key in (
            "live_comment_export", "live_comment_transport", "live_comment_niconico",
            "subtitle_roundtrip", "managed_yaml", "tls_certificates", "rplay_session_decoder",
        ):
            self.assertIn(key, result)
            self.assertTrue(result[key], key)

    def test_healthy_default_context_is_exercised_with_verification_enabled(self):
        with patch("ssl.create_default_context", wraps=ssl.create_default_context) as create:
            result = self_check()
        self.assertTrue(result["tls_context"])
        create.assert_called_once_with()
        self.assert_existing_checks_remain(result)

    def test_missing_default_context_resource_reports_false_despite_existing_ca_bundle(self):
        with patch("ssl.create_default_context", side_effect=FileNotFoundError(2, "No such file or directory")):
            result = self_check()
        self.assertFalse(result["tls_context"])
        self.assertTrue(result["tls_certificates"])
        self.assert_existing_checks_remain(result)

    def test_ssl_initialization_error_reports_false_without_aborting_other_checks(self):
        with patch("ssl.create_default_context", side_effect=ssl.SSLError("synthetic TLS failure")):
            result = self_check()
        self.assertFalse(result["tls_context"])
        self.assert_existing_checks_remain(result)

    def test_context_without_hostname_verification_is_not_healthy(self):
        context = SimpleNamespace(check_hostname=False, verify_mode=ssl.CERT_REQUIRED)
        with patch("ssl.create_default_context", return_value=context) as create:
            result = self_check()
        self.assertFalse(result["tls_context"])
        create.assert_called_once_with()

    def test_context_without_required_certificates_is_not_healthy(self):
        context = SimpleNamespace(check_hostname=True, verify_mode=ssl.CERT_NONE)
        with patch("ssl.create_default_context", return_value=context) as create:
            result = self_check()
        self.assertFalse(result["tls_context"])
        create.assert_called_once_with()

    def test_tls_initialization_is_checked_even_when_another_dependency_is_missing(self):
        health = {"live_comment_export": False, "live_comment_transport": True,
                  "live_comment_niconico": True}
        with patch("video_downloader.live.danmaku.dependencies.health", return_value=dict(health)), \
                patch("ssl.create_default_context", wraps=ssl.create_default_context) as create:
            result = self_check()
        self.assertTrue(result["tls_context"])
        create.assert_called_once_with()
        for key, expected in health.items():
            self.assertEqual(result[key], expected)


if __name__ == "__main__":
    unittest.main()
