import unittest

from video_downloader.core.constants import DEFAULT_SUBTITLE_LANGS
from video_downloader.core.validation import validate_config


class ConfigValidationTests(unittest.TestCase):
    def test_disabled_proxy_accepts_empty_port(self):
        validated, errors = validate_config({"PROXY_ENABLED": 0, "PROXY_PORT": ""})
        self.assertEqual(errors, [])
        self.assertEqual(validated["PROXY_PORT"], "")

    def test_enabled_proxy_rejects_empty_port(self):
        validated, errors = validate_config({"PROXY_ENABLED": 1, "PROXY_PORT": ""})
        self.assertTrue(any("PROXY_PORT" in err for err in errors),
                        f"Expected PROXY_PORT error in {errors}")
        self.assertEqual(validated["PROXY_PORT"], "7890")

    def test_enabled_proxy_rejects_invalid_address(self):
        validated, errors = validate_config({
            "PROXY_ENABLED": 1,
            "PROXY_ADDR": "http://user@example.com/path",
        })
        self.assertTrue(any("PROXY_ADDR" in err for err in errors),
                        f"Expected PROXY_ADDR error in {errors}")
        self.assertEqual(validated["PROXY_ADDR"], "127.0.0.1")

    def test_subtitle_defaults_are_disabled_and_use_chinese_languages(self):
        validated, errors = validate_config({})
        self.assertEqual(errors, [])
        self.assertEqual(validated["DOWNLOAD_SUBTITLES"], 0)
        self.assertEqual(validated["SUBTITLE_TYPE"], "all")
        self.assertEqual(validated["SUBTITLE_LANGS"], DEFAULT_SUBTITLE_LANGS)

    def test_subtitle_type_rejects_unknown_value(self):
        validated, errors = validate_config({"SUBTITLE_TYPE": "invalid"})
        self.assertTrue(any("SUBTITLE_TYPE" in error for error in errors))
        self.assertEqual(validated["SUBTITLE_TYPE"], "all")

    def test_subtitle_toggle_rejects_invalid_boolean(self):
        validated, errors = validate_config({"DOWNLOAD_SUBTITLES": 2})
        self.assertTrue(any("DOWNLOAD_SUBTITLES" in error for error in errors))
        self.assertEqual(validated["DOWNLOAD_SUBTITLES"], 0)

    def test_subtitle_languages_are_limited_to_200_characters(self):
        validated, errors = validate_config({"SUBTITLE_LANGS": "x" * 201})
        self.assertTrue(any("SUBTITLE_LANGS" in error for error in errors))
        self.assertEqual(validated["SUBTITLE_LANGS"], DEFAULT_SUBTITLE_LANGS)


if __name__ == "__main__":
    unittest.main()
