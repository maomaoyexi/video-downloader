"""损坏会话的类型边界不得阻止启动恢复和录制列表。"""
import json

import pytest

from video_downloader.live import session as live_session
from video_downloader.live.session import LiveSession, RecordingStore, recover_interrupted


@pytest.mark.parametrize("payload", [None, [], "invalid", 17])
def test_recovery_skips_non_object_session_without_changing_original(tmp_path, payload):
    directory = tmp_path / ("a" * 32)
    directory.mkdir()
    path = directory / "session.json"
    original = json.dumps(payload).encode("utf-8")
    path.write_bytes(original)

    assert recover_interrupted(tmp_path) == 0
    assert path.read_bytes() == original
    assert not (directory / "integrity-report.json").exists()


@pytest.mark.parametrize("payload", [None, [], "invalid", 17])
def test_recordings_list_skips_non_object_session_without_changing_original(tmp_path, payload):
    directory = tmp_path / ("a" * 32)
    directory.mkdir()
    path = directory / "session.json"
    original = json.dumps(payload).encode("utf-8")
    path.write_bytes(original)

    assert RecordingStore(tmp_path).recent() == []
    assert path.read_bytes() == original


def test_empty_session_object_is_ignored_and_preserved(tmp_path):
    directory = tmp_path / ("a" * 32)
    directory.mkdir()
    path = directory / "session.json"
    path.write_bytes(b"{}")

    assert recover_interrupted(tmp_path) == 0
    assert RecordingStore(tmp_path).recent() == []
    assert path.read_bytes() == b"{}"


def test_recovery_still_finalizes_abandoned_session_and_preserves_media(tmp_path, monkeypatch):
    recording = LiveSession(tmp_path, "fixture", "live_edge", "https://example.com/live")
    media = recording.media / "recording.ts"
    media.write_bytes(b"retained recording bytes")
    monkeypatch.setattr(live_session, "_process_exists", lambda pid: False)

    assert recover_interrupted(tmp_path) == 1

    state = json.loads((recording.root / "session.json").read_text(encoding="utf-8"))
    report = json.loads((recording.root / "integrity-report.json").read_text(encoding="utf-8"))
    assert state["state"] == "finished"
    assert state["stop_reason"] == "application_interrupted"
    assert report["files"][0]["path"] == str(media)
    assert report["files"][0]["valid"] is False
    assert media.read_bytes() == b"retained recording bytes"


def test_recordings_list_still_returns_valid_finished_session(tmp_path):
    recording = LiveSession(tmp_path, "fixture", "live_edge", "https://example.com/live")
    recording.finish("ended", {"files": [], "conclusion": "complete"})

    result = RecordingStore(tmp_path).recent()

    assert len(result) == 1
    assert result[0]["job_id"] == recording.root.name
    assert result[0]["conclusion"] == "complete"
    assert result[0]["stop_reason"] == "ended"


def test_container_initialization_skips_non_object_session(tmp_path):
    from video_downloader.container import AppContainer

    directory = tmp_path / "download" / ".live-jobs" / ("a" * 32)
    directory.mkdir(parents=True)
    path = directory / "session.json"
    path.write_bytes(b"[]")

    container = AppContainer(tmp_path)

    assert container._recordings.recent() == []
    assert path.read_bytes() == b"[]"
