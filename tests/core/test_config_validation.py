import unittest

from video_downloader.core.constants import DEFAULT_SUBTITLE_LANGS
from video_downloader.core.validation import validate_config


class ConfigValidationTests(unittest.TestCase):
    def test_fractional_numbers_do_not_silently_change_integer_settings(self):
        for key, value, previous in (
            ("THREADS", 4.9, 4),
            ("TASK_MAX_PARALLEL", 2.5, 2),
            ("LIVE_DANMAKU_OFFSET_MS", -0.5, 0),
            ("DOWNLOAD_SUBTITLES", 0.5, 0),
            ("PROXY_ENABLED", 1.5, 0),
        ):
            with self.subTest(key=key):
                config, errors = validate_config({key: value})
                self.assertTrue(any(key in error for error in errors), errors)
                self.assertEqual(config[key], previous)

    def test_task_live_parallel_default_and_bounds(self):
        self.assertEqual(validate_config({})[0]["TASK_LIVE_PARALLEL"], 2)
        for value in (2, 5):
            config, errors = validate_config({"TASK_LIVE_PARALLEL": value})
            self.assertEqual(errors, [])
            self.assertEqual(config["TASK_LIVE_PARALLEL"], value)
        for value in (0, 1, 6, "bad"):
            config, errors = validate_config({"TASK_LIVE_PARALLEL": value})
            self.assertTrue(errors)
            self.assertEqual(config["TASK_LIVE_PARALLEL"], 2)

    def test_task_parallel_defaults_and_download_limits(self):
        defaults, _ = validate_config({})
        self.assertEqual(defaults["TASK_MAX_PARALLEL"], 2)
        self.assertEqual(defaults["TASK_MIXED_PARALLEL"], 1)
        self.assertEqual(defaults["TASK_DOWNLOAD_PARALLEL"], 1)
        for key in ("TASK_MAX_PARALLEL", "TASK_DOWNLOAD_PARALLEL"):
            for value in (1, 5):
                self.assertEqual(validate_config({key:value})[1], [])
            for value in (0, 6):
                self.assertTrue(validate_config({key:value})[1])
        for value in (-1, float("inf"), float("nan")):
            self.assertTrue(validate_config({"TASK_DOWNLOAD_SPEED_LIMIT":value})[1])
        self.assertEqual(validate_config({"TASK_DOWNLOAD_SPEED_LIMIT":0.3})[0]["TASK_DOWNLOAD_SPEED_LIMIT"], 0.3)
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

    def test_live_mode_accepts_known_values(self):
        for value in ("auto", "catch_up", "live_edge", "wait"):
            validated, errors = validate_config({"LIVE_MODE": value})
            self.assertEqual(errors, [])
            self.assertEqual(validated["LIVE_MODE"], value)

    def test_live_mode_rejects_unknown_value_and_keeps_default(self):
        validated, errors = validate_config({"LIVE_MODE": "from_start"})
        self.assertTrue(any("LIVE_MODE" in error for error in errors))
        self.assertEqual(validated["LIVE_MODE"], "auto")

    def test_live_platform_modes_is_json_object(self):
        validated, errors = validate_config({"LIVE_PLATFORM_MODES": '{"YouTube":"catch_up"}'})
        self.assertEqual(errors, [])
        self.assertEqual(validated["LIVE_PLATFORM_MODES"], '{"YouTube":"catch_up"}')
        _, errors = validate_config({"LIVE_PLATFORM_MODES": "not-json"})
        self.assertTrue(any("LIVE_PLATFORM_MODES" in error for error in errors))

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

    def test_po_token_toggle_is_boolean(self):
        validated, errors = validate_config({"YOUTUBE_PO_TOKEN_ENABLED": 2})
        self.assertTrue(any("YOUTUBE_PO_TOKEN_ENABLED" in error for error in errors))
        self.assertEqual(validated["YOUTUBE_PO_TOKEN_ENABLED"], 0)

    def test_upstream_modes_migrate_to_existing_live_domain(self):
        for old, expected in {"wait":"wait", "from_start":"catch_up", "current":"live_edge"}.items():
            config, errors = validate_config({"LIVE_RECORD_MODE":old})
            self.assertEqual(errors, [])
            self.assertEqual(config["LIVE_MODE"], expected)
            self.assertNotIn("LIVE_RECORD_MODE", config)

    def test_live_record_mode_rejects_unknown_value(self):
        validated, errors = validate_config({"LIVE_RECORD_MODE": "invalid"})
        self.assertTrue(any("LIVE_RECORD_MODE" in error for error in errors))
        self.assertEqual(validated["LIVE_MODE"], "auto")

    def test_upstream_settings_do_not_replace_explicit_live_mode_or_scheduler(self):
        config, errors = validate_config({"LIVE_MODE":"live_edge", "LIVE_RECORD_MODE":"from_start", "LIVE_WATCH_INTERVAL":45})
        self.assertEqual(errors, [])
        self.assertEqual(config["LIVE_MODE"], "live_edge")
        self.assertNotIn("LIVE_WATCH_INTERVAL", config)

    def test_default_ytdlp_args_allow_up_to_4000_characters(self):
        value = "x" * 4000
        validated, errors = validate_config({"YTDLP_DEFAULT_ARGS": value})
        self.assertEqual(errors, [])
        self.assertEqual(validated["YTDLP_DEFAULT_ARGS"], value)
        _, errors = validate_config({"YTDLP_DEFAULT_ARGS": "x" * 4001})
        self.assertTrue(any("YTDLP_DEFAULT_ARGS" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
