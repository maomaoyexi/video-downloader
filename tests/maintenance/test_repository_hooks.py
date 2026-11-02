"""Exercise the installed hooks with disposable work trees and bare remotes.

All payloads are synthetic. Deliberate --no-verify commits model an existing bad
commit and test that a later ordinary push still cannot transmit it.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.helpers import PROJECT_ROOT


LOCAL_FILES = ['cookies.txt', 'settings.ini', 'urls.txt', 'download/posts/image.png',
               '.ai/state.json', '.claude/state.json', 'temp/plan/文档 with spaces.md',
               '启动修复版.cmd']
PAYLOAD = 'synthetic-local-only-data'


class Repository:
    def __init__(self, root, remote, env):
        self.root, self.remote, self.env = root, remote, env

    def git(self, *args, ok=True, cwd=None):
        result = subprocess.run(['git', *args], cwd=cwd or self.root, env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ok:
            assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
        return result

    def head(self, *, remote=False):
        return self.git('rev-parse', 'refs/heads/main', cwd=self.remote if remote else None).stdout.strip()

    def write(self, name, text=PAYLOAD):
        file = self.root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf-8')
        return file

    def commit(self, name, *, bypass=False, ok=True):
        return self.git('commit', *(['--no-verify'] if bypass else []), '-m', name, ok=ok)

    def unsafe_history(self, name):
        self.write(name)
        self.git('add', '-f', '--', name)
        self.commit('add synthetic local file', bypass=True)
        unsafe = self.head()
        self.git('rm', '--cached', '--', name)
        self.commit('untrack synthetic local file', bypass=True)
        return unsafe


@pytest.fixture
def repository(tmp_path):
    root, remote = tmp_path / 'work tree', tmp_path / 'remote store.git'
    root.mkdir()
    # Do not let a developer's Git config, signing, or parent hook environment
    # affect these isolated repositories. Keep the normal executable search path.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', ''))
    repo = Repository(root, remote, env)
    repo.git('init', '-b', 'main')
    repo.git('init', '--bare', '-b', 'main', str(remote))
    repo.git('config', 'user.name', 'Hook Test')
    repo.git('config', 'user.email', 'hook-test@example.invalid')
    repo.git('config', 'core.autocrlf', 'false')
    repo.git('config', 'core.hooksPath', '.githooks')
    for name in ['.githooks/pre-commit', '.githooks/pre-push',
                 'scripts/check_repository_layout.py', '.gitignore']:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / name, destination)
        if name.startswith('.githooks/'):
            destination.chmod(0o755)
    repo.git('add', '.')
    repo.commit('seed safe repository')
    repo.git('remote', 'add', 'origin', str(remote))
    repo.git('push', '-u', 'origin', 'main')
    return repo


@pytest.mark.parametrize('name', LOCAL_FILES)
def test_forced_add_is_rejected_by_real_precommit(repository, name):
    repo = repository
    file = repo.write(name)
    before = repo.head()
    assert repo.git('add', '--', name, ok=False).returncode != 0
    repo.git('add', '-f', '--', name)
    denied = repo.commit('should be refused', ok=False)
    assert denied.returncode != 0
    assert PAYLOAD.encode() not in denied.stdout + denied.stderr
    assert repo.head() == before
    repo.git('rm', '--cached', '--', name)
    repo.git('commit', '--allow-empty', '-m', 'cleanup index')
    repo.git('push', 'origin', 'main')
    assert file.read_text(encoding='utf-8') == PAYLOAD


def test_precommit_checks_unchanged_tracked_local_data(repository):
    repo = repository
    file = repo.write('Cookies.TXT')
    repo.git('add', '-f', 'Cookies.TXT')
    repo.commit('simulate already tracked data', bypass=True)
    repo.write('safe.txt', 'safe')
    repo.git('add', 'safe.txt')
    assert repo.commit('unrelated edit', ok=False).returncode != 0
    repo.git('rm', '--cached', 'Cookies.TXT')
    repo.commit('remove tracking while keeping local data')
    assert file.is_file()


@pytest.mark.parametrize('name', LOCAL_FILES)
def test_prepush_blocks_added_then_removed_paths_without_transmitting_objects(repository, name):
    repo = repository
    before = repo.head(remote=True)
    unsafe = repo.unsafe_history(name)
    denied = repo.git('push', 'origin', 'main', ok=False)
    assert denied.returncode != 0
    assert PAYLOAD.encode() not in denied.stdout + denied.stderr
    assert repo.head(remote=True) == before
    assert repo.git('cat-file', '-e', unsafe.decode(), cwd=repo.remote, ok=False).returncode != 0


def test_new_annotated_tag_ignores_stale_remote_tracking_refs(repository):
    repo = repository
    repo.unsafe_history('.CLAUDE/state.json')
    repo.git('update-ref', 'refs/remotes/origin/main', repo.head().decode())
    repo.git('tag', '-a', 'unsafe-tag', '-m', 'tag with unsafe ancestry')
    assert repo.git('push', 'origin', 'refs/tags/unsafe-tag', ok=False).returncode != 0
    assert repo.git('show-ref', '--tags', cwd=repo.remote, ok=False).returncode == 1


def test_merge_history_and_multiple_updates_are_checked(repository):
    repo = repository
    baseline = repo.head(remote=True)
    repo.git('tag', 'safe-tag')
    repo.git('checkout', '-b', 'side')
    repo.unsafe_history('download/private/file.bin')
    repo.git('checkout', 'main')
    repo.write('main.txt', 'safe main edit')
    repo.git('add', 'main.txt')
    repo.commit('safe main edit')
    repo.git('merge', '--no-ff', 'side', '-m', 'merge clean tip with unsafe parent history')
    assert repo.git('push', 'origin', 'main', 'refs/tags/safe-tag', ok=False).returncode != 0
    assert repo.head(remote=True) == baseline
    assert repo.git('show-ref', '--tags', cwd=repo.remote, ok=False).returncode == 1


def test_force_push_still_checks_divergent_history(repository):
    repo = repository
    baseline = repo.head().decode()
    repo.write('remote.txt', 'safe remote edit')
    repo.git('add', 'remote.txt')
    repo.commit('advance remote')
    repo.git('push', 'origin', 'main')
    before = repo.head(remote=True)
    repo.git('reset', '--hard', baseline)
    repo.unsafe_history('settings.ini')
    assert repo.git('push', '--force', 'origin', 'main', ok=False).returncode != 0
    assert repo.head(remote=True) == before


def test_existing_remote_history_is_not_reuploaded_but_new_remote_is_audited(repository, tmp_path):
    repo = repository
    repo.unsafe_history('temp/legacy-plan.md')
    # Model history already present on a remote before these hooks were installed.
    repo.git('push', '--no-verify', 'origin', 'main')
    repo.write('safe.txt', 'safe')
    repo.git('add', 'safe.txt')
    repo.commit('safe new change')
    repo.git('tag', '-a', 'safe-tag', '-m', 'safe tip over existing remote history')
    repo.git('push', 'origin', 'main', 'refs/tags/safe-tag')
    repo.git('push', 'origin', ':refs/tags/safe-tag')
    empty = tmp_path / 'new remote.git'
    repo.git('init', '--bare', str(empty))
    assert repo.git('push', str(empty), 'main', ok=False).returncode != 0
    assert repo.git('show-ref', cwd=empty, ok=False).returncode == 1


def test_git_replace_cannot_hide_outgoing_unsafe_tree(repository):
    repo = repository
    baseline = repo.head().decode()
    repo.write('urls.txt')
    repo.git('add', '-f', 'urls.txt')
    repo.commit('simulate bad commit', bypass=True)
    unsafe = repo.head().decode()
    repo.git('replace', unsafe, baseline)
    assert repo.git('push', 'origin', 'main', ok=False).returncode != 0


def test_noncommit_tags_fail_closed(repository):
    repo = repository
    blob = repo.git('rev-parse', 'HEAD:.gitignore').stdout.decode().strip()
    repo.git('tag', 'blob-tag', blob)
    assert repo.git('push', 'origin', 'refs/tags/blob-tag', ok=False).returncode != 0


def test_shallow_history_fails_closed(repository, tmp_path):
    repo = repository
    clone = tmp_path / 'shallow clone'
    repo.git('clone', '--depth=1', repo.remote.as_uri(), str(clone))
    repo.git('config', 'core.hooksPath', '.githooks', cwd=clone)
    repo.git('tag', 'shallow-tag', cwd=clone)
    assert repo.git('push', 'origin', 'refs/tags/shallow-tag', cwd=clone, ok=False).returncode != 0


def test_malformed_input_and_unavailable_remote_fail_closed_without_echoing_credentials(repository):
    repo = repository
    command = [sys.executable, 'scripts/check_repository_layout.py', '--pre-push', 'origin',
               'invalid-transport::test-token-never-echo']
    for data in ['bad input\n', f'refs/heads/main {repo.head().decode()} refs/heads/main {"0" * 40}\n']:
        result = subprocess.run(command, cwd=repo.root, env=repo.env, input=data.encode(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert result.returncode != 0
        assert b'test-token-never-echo' not in result.stdout + result.stderr


def test_hooks_use_unix_line_endings():
    for name in ['pre-commit', 'pre-push']:
        data = (PROJECT_ROOT / '.githooks' / name).read_bytes()
        assert data.startswith(b'#!/bin/sh\n')
        assert b'\r' not in data
