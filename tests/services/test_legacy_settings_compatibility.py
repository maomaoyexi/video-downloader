"""失效控件下线后，旧设置和预设仍能往返，且不会改变当前下载策略。"""
import configparser

from video_downloader.core.command import build_ytdlp_cmd
from video_downloader.core.validation import validate_config
from video_downloader.services.storage import StorageService
from video_downloader.state.app_state import AppState


LEGACY_VALUES = {
    "MERGE_MODE": 0,
    "ENABLE_LOG": 0,
    "MP3_BITRATE": 128,
    "DEL_WAV_AFTER_CONVERT": 1,
}


def test_legacy_settings_survive_current_setting_and_preset_roundtrip(tmp_path):
    parser = configparser.ConfigParser(interpolation=None)
    parser["settings"] = {key: str(value) for key, value in LEGACY_VALUES.items()}
    with (tmp_path / "settings.ini").open("w", encoding="utf-8") as stream:
        parser.write(stream)
    state = AppState()
    storage = StorageService(tmp_path, state, validate_config, lambda *args: None, lambda *args: None)
    loaded = storage.load_config()
    assert {key: loaded[key] for key in LEGACY_VALUES} == LEGACY_VALUES

    updated, errors = validate_config({"AUDIO_MODE": "2", "AUDIO_FORMAT": "m4a"}, loaded)
    assert not errors
    state.replace_config(updated)
    storage.save_config()
    assert storage.save_preset("legacy-compatible")["ok"] is True

    state.replace_config(validate_config({})[0])
    restored = storage.load_preset("legacy-compatible")
    assert restored["ok"] is True
    assert {key: restored["config"][key] for key in LEGACY_VALUES} == LEGACY_VALUES
    assert restored["config"]["AUDIO_MODE"] == "2"
    assert restored["config"]["AUDIO_FORMAT"] == "m4a"
    assert {key: storage.load_config()[key] for key in LEGACY_VALUES} == LEGACY_VALUES


def test_legacy_merge_setting_does_not_override_current_audio_mode(tmp_path):
    url = "https://www.youtube.com/watch?v=compatibility"
    merged, errors = validate_config(dict(LEGACY_VALUES, AUDIO_MODE="0", USE_COOKIES=0))
    assert not errors
    command = build_ytdlp_cmd(url, merged, tmp_path, ".exe")
    assert "--merge-output-format" in command

    separated, errors = validate_config(dict(LEGACY_VALUES, MERGE_MODE=1, AUDIO_MODE="1", USE_COOKIES=0))
    assert not errors
    command = build_ytdlp_cmd(url, separated, tmp_path, ".exe")
    assert "--merge-output-format" not in command
    assert "--remux-video" not in command
