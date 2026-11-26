import subprocess
from unittest.mock import Mock

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
    monkeypatch.setattr(tools.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(tools.subprocess, "run", run)
    return service, run, log


def completed(returncode=0, *, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


@pytest.mark.parametrize("status", ["403: rate limit exceeded", "429: Too Many Requests"])
def test_rate_limit_reuses_portable_proxy_for_release_lookup_and_update(updater, status, tmp_path):
    service, run, log = updater
    latest = "https://github.com/yt-dlp/yt-dlp/releases/latest"
    tag_url = "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.11.23"
    proxy = "http://127.0.0.1:3128"
    portable_config = tmp_path / "dependency" / "yt-dlp.conf"
    portable_config.write_text(f"--proxy {proxy}\n", encoding="utf-8")
    requests = []

    def run_with_portable_proxy(command, **kwargs):
        args = command[1:]
        if "--version" in args:
            return completed(stdout="2026.10.26\n")
        assert "--ignore-config" not in args
        assert portable_config.read_text(encoding="utf-8") == f"--proxy {proxy}\n"
        if args == ["-U"]:
            requests.append("api")
            return completed(100, stderr=f"ERROR: Unable to obtain version info (HTTP Error {status}); visit {latest}")
        if args[-1] == latest:
            requests.append("release")
            assert "--simulate" in args and "--no-update" in args
            return completed(1, stdout=f"[redirect] Following redirect to {tag_url}\n",
                             stderr=f"ERROR: Unsupported URL: {tag_url}")
        assert args == ["--update-to", "stable@2026.11.23"]
        requests.append("update")
        return completed(stdout="Updated yt-dlp to stable@2026.11.23\n")

    run.side_effect = run_with_portable_proxy

    assert service.update_ytdlp() == {"ok": True}
    assert requests == ["api", "release", "update"]
    log.assert_any_call("[yt-dlp] 更新完成", "success")


@pytest.mark.parametrize("version", ["2026.11.23", "2026.11.24", "2026.11.24.010101dev"])
def test_fallback_preserves_current_or_newer_versions_and_other_channels(updater, version):
    service, run, log = updater
    run.side_effect = [
        completed(100, stderr=("ERROR: Unable to obtain version info (HTTP Error 403: rate limit exceeded); "
                               "visit https://github.com/yt-dlp/yt-dlp/releases/latest")),
        completed(1, stdout="[redirect] Following redirect to https://github.com/yt-dlp/yt-dlp/releases/tag/2026.11.23\n"),
        completed(stdout=version),
    ]

    assert service.update_ytdlp() == {"ok": True}
    assert run.call_count == 3
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
    service, run, _ = updater
    run.return_value = result

    assert service.update_ytdlp() == {"ok": True}
    assert run.call_count == 1


def test_unexpected_release_redirect_keeps_original_error_and_releases_maintenance(updater):
    service, run, log = updater
    error = ("ERROR: Unable to obtain version info (HTTP Error 403: rate limit exceeded); "
             "visit https://github.com/yt-dlp/yt-dlp/releases/latest")
    run.side_effect = [
        completed(100, stderr=error),
        completed(1, stdout="[redirect] Following redirect to https://github.com/other/yt-dlp/releases/tag/2026.11.23\n"),
        completed(stdout="yt-dlp is up to date"),
    ]

    assert service.update_ytdlp() == {"ok": True}
    assert run.call_count == 2
    log.assert_any_call(f"[yt-dlp] 更新失败: {error}", "error")
    assert service.update_ytdlp() == {"ok": True}
