import subprocess
from unittest.mock import MagicMock, Mock

import pytest

from tests.helpers.tools import ImmediateThread, create_service
from video_downloader.services import tools


@pytest.fixture
def updater(tmp_path, monkeypatch):
    binary = tmp_path / "dependency" / "yt-dlp.exe"
    binary.parent.mkdir()
    binary.touch()
    log = Mock()
    service = create_service(tmp_path, log=log)
    run = Mock()
    fetch = MagicMock()
    response = fetch.return_value.__enter__.return_value
    response.geturl.return_value = "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.11.23"
    monkeypatch.setattr(tools.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(tools.subprocess, "run", run)
    monkeypatch.setattr(tools, "urlopen", fetch)
    return service, run, fetch, log


def completed(returncode=0, *, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


@pytest.mark.parametrize("status", ["403: rate limit exceeded", "429: Too Many Requests"])
def test_rate_limit_retries_with_official_stable_tag(updater, status):
    service, run, fetch, log = updater
    run.side_effect = [
        completed(100, stderr=(f"ERROR: Unable to obtain version info (HTTP Error {status}); "
                               "visit https://github.com/yt-dlp/yt-dlp/releases/latest")),
        completed(stdout="2026.10.26\n"),
        completed(stdout="Updated yt-dlp to stable@2026.11.23\n"),
    ]

    assert service.update_ytdlp() == {"ok": True}
    assert [call.args[0][1:] for call in run.call_args_list] == [
        ["-U"], ["--ignore-config", "--version"],
        ["--ignore-config", "--update-to", "stable@2026.11.23"],
    ]
    request = fetch.call_args.args[0]
    assert request.full_url == "https://github.com/yt-dlp/yt-dlp/releases/latest"
    assert request.get_method() == "HEAD"
    log.assert_any_call("[yt-dlp] 更新完成", "success")


@pytest.mark.parametrize("version", ["2026.11.23", "2026.11.24", "2026.11.24.010101dev"])
def test_fallback_preserves_current_or_newer_versions_and_other_channels(updater, version):
    service, run, _, log = updater
    run.side_effect = [
        completed(100, stderr=("ERROR: Unable to obtain version info (HTTP Error 403: rate limit exceeded); "
                               "visit https://github.com/yt-dlp/yt-dlp/releases/latest")),
        completed(stdout=version),
    ]

    assert service.update_ytdlp() == {"ok": True}
    assert run.call_count == 2
    if version.endswith("dev"):
        assert any(call.args[1] == "error" for call in log.call_args_list)
    else:
        log.assert_any_call(f"[yt-dlp] 当前版本 {version} 已达到官方稳定版 2026.11.23", "success")


@pytest.mark.parametrize("result", [
    completed(stdout="yt-dlp is up to date"),
    completed(100, stderr="ERROR: Unable to fetch checksums (HTTP Error 403: Forbidden)"),
    completed(100, stderr=("ERROR: Unable to obtain version info (HTTP Error 403: rate limit exceeded); "
                           "visit https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest")),
])
def test_normal_update_and_unrelated_failures_use_existing_path(updater, result):
    service, run, fetch, _ = updater
    run.return_value = result

    assert service.update_ytdlp() == {"ok": True}
    assert run.call_count == 1
    fetch.assert_not_called()


def test_unexpected_release_redirect_keeps_original_error_and_releases_maintenance(updater):
    service, run, fetch, log = updater
    error = ("ERROR: Unable to obtain version info (HTTP Error 403: rate limit exceeded); "
             "visit https://github.com/yt-dlp/yt-dlp/releases/latest")
    run.return_value = completed(100, stderr=error)
    response = fetch.return_value.__enter__.return_value
    response.geturl.return_value = "https://github.com/other/yt-dlp/releases/tag/2026.11.23"

    assert service.update_ytdlp() == {"ok": True}
    assert run.call_count == 1
    log.assert_any_call(f"[yt-dlp] 更新失败: {error}", "error")
    assert service.update_ytdlp() == {"ok": True}
