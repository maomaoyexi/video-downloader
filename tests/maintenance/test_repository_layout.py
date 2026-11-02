"""Repository boundaries remain enforced even after an accidental forced add."""
from tests.helpers import PROJECT_ROOT
from pathlib import Path
import subprocess

import pytest

from scripts.check_repository_layout import violations, local_paths, git, GuardError, MAINTAINED_SCRIPTS


def test_tracked_tree_contains_no_local_plans_or_installed_dependencies():
    root = PROJECT_ROOT
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
    assert violations(files) == []


def test_guard_rejects_forced_adds_and_accepts_only_license_files():
    invalid = ['cookies.txt', 'Settings.INI', 'URLS.TXT', 'download/posts/image.png',
               '.AI/state.json', '.Claude/state.json',
               'temp/plan/example.md', 'Temp/test.txt', 'dependency/tool.exe',
               'dependency/.venv/pyvenv.cfg', 'dependency/package/LICENSE',
               'dependency/runtime.lock.json', 'scripts/one_off_probe.py', 'tests/test_scattered.py']
    assert violations(invalid) == invalid
    assert violations(['dependency/pysubs2.LICENSE', 'dependency/withny-dl.LICENSE',
                       'resource/dependencies/live-python.lock.json',
                       'resource/yt-dlp-plugins/video_downloader/yt_dlp_plugins/extractor/twitcasting.py',
                       'tests/core/test_paths.py', *MAINTAINED_SCRIPTS]) == []
    assert local_paths(['cookies.txt', '.AI', 'DOWNLOAD', 'Temp/a', 'docs/cookies.txt',
                        'resource/download/icon.svg', 'temporary.txt', 'downloads/a']) == [
                            'cookies.txt', '.AI', 'DOWNLOAD', 'Temp/a']


def test_local_repair_launcher_is_ignored_and_rejected_if_forced():
    names = ['启动修复版.cmd', '启动修复版.CMD']
    assert violations(names) == names
    assert local_paths(names) == names
    result = subprocess.check_output(
        ['git', 'check-ignore', '--no-index', '--stdin', '-z'], cwd=PROJECT_ROOT,
        input='启动修复版.cmd\0'.encode('utf-8'))
    assert result.decode('utf-8').split('\0') == ['启动修复版.cmd', '']
    tracked = subprocess.run(
        ['git', 'ls-files', '--error-unmatch', '--', '启动修复版.cmd'], cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert tracked.returncode == 1
    assert tracked.stdout == b''


def test_local_release_preparation_records_are_not_publishable():
    names = ['docs/release-preparation-v2.7.1.md',
             'docs/release-preparation-v2.8.0.md',
             'Docs/Release-Preparation-v2.7.1.MD']
    assert violations(names) == names
    assert local_paths(names) == names
    assert violations(['docs/releases/v2.7.1.md', 'RELEASE_NOTES.md']) == []
    result = subprocess.check_output(
        ['git', 'check-ignore', '--no-index', '--stdin', '-z'], cwd=PROJECT_ROOT,
        input=('\0'.join(names[:2]) + '\0').encode('utf-8'))
    assert result.decode('utf-8').split('\0') == names[:2] + ['']
    tracked = subprocess.run(
        ['git', 'ls-files', '--error-unmatch', '--', names[0]], cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert tracked.returncode == 1


def test_gitignore_uses_default_deny_for_runtime_and_temporary_scripts():
    root = PROJECT_ROOT
    ignored = ['cookies.txt', 'settings.ini', 'urls.txt', 'download/posts/image.png',
               '.ai/state.json', '.claude/state.json',
               'temp/plan/new.md', 'dependency/new-tool.dll', 'dependency/package/LICENSE',
               'dependency/yt-dlp-plugins/plugin.py', 'scripts/temporary-test.py']
    output = subprocess.check_output(['git', 'check-ignore', '--no-index', *ignored], cwd=root)
    assert output.decode('utf-8').splitlines() == ignored
    for allowed in ['dependency/new-library.LICENSE', *MAINTAINED_SCRIPTS]:
        result = subprocess.run(['git', 'check-ignore', '--no-index', allowed], cwd=root,
                                stdout=subprocess.PIPE)
        assert result.returncode == 1, allowed


@pytest.mark.parametrize('timeout', [False, True])
def test_git_failure_is_closed_and_never_echoes_remote_credentials(monkeypatch, timeout):
    secret = 'synthetic-token-never-echo'

    def fail(command, **kwargs):
        if timeout:
            raise subprocess.TimeoutExpired(command, kwargs['timeout'], stderr=secret.encode())
        return subprocess.CompletedProcess(command, 1, b'', secret.encode())

    monkeypatch.setattr(subprocess, 'run', fail)
    with pytest.raises(GuardError) as raised:
        git('ls-remote', f'https://{secret}@example.invalid/repo')
    assert secret not in str(raised.value)
