import unittest

from video_downloader.config_validation import validate_config


class ConfigValidationTests(unittest.TestCase):
    def test_disabled_proxy_accepts_empty_port(self):
        validated, errors = validate_config({"PROXY_ENABLED": 0, "PROXY_PORT": ""})
        self.assertEqual(errors, [])
        self.assertEqual(validated["PROXY_PORT"], "")

    def test_enabled_proxy_rejects_empty_port(self):
        validated, errors = validate_config({"PROXY_ENABLED": 1, "PROXY_PORT": ""})
        self.assertIn("PROXY_PORT", errors)
        self.assertEqual(validated["PROXY_PORT"], "7890")

    def test_enabled_proxy_rejects_invalid_address(self):
        validated, errors = validate_config({
            "PROXY_ENABLED": 1,
            "PROXY_ADDR": "http://user@example.com/path",
        })
        self.assertIn("PROXY_ADDR", errors)
        self.assertEqual(validated["PROXY_ADDR"], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
