import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from video_downloader.services.po_token_provider import PoTokenProviderService


class PoTokenProviderServiceTests(unittest.TestCase):
    def test_missing_dependencies_returns_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            service = PoTokenProviderService(Path(directory), Mock())
            result = service.ensure_running()
        self.assertIn("error", result)
        self.assertIn("deno", result["error"])
        self.assertIn("bgutil-ytdlp-pot-provider", result["error"])

    def test_existing_provider_is_reused_without_spawning_process(self):
        log = Mock()
        with tempfile.TemporaryDirectory() as directory:
            service = PoTokenProviderService(Path(directory), log)
            with patch.object(service, "_ping", return_value={"version": "1.3.2"}), patch(
                "video_downloader.services.po_token_provider.subprocess.Popen"
            ) as popen:
                result = service.ensure_running()
        self.assertEqual(result, {
            "ok": True,
            "version": "1.3.2",
            "reused": True,
            "base_url": "http://127.0.0.1:4416",
        })
        popen.assert_not_called()
        self.assertIn("已连接现有", log.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
