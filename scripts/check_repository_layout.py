"""Keep local data out of the index and every outgoing commit tree."""
from __future__ import annotations

import argparse
import os
from pathlib import PurePosixPath
import re
import subprocess
import sys


LOCAL_ROOT_PATHS = frozenset({
    'cookies.txt', 'settings.ini', 'urls.txt', 'download', '.ai', '.claude', 'temp',
})
OBJECT_ID = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')


MAINTAINED_SCRIPTS = frozenset({
    'scripts/install_bililive.py', 'scripts/install_live_dependencies.py',
    'scripts/build_withny_dependency.py', 'scripts/check_live_release.py',
    'scripts/check_repository_layout.py',
    'scripts/withny_patch/chat.go', 'scripts/withny_patch/chat_protocol.go',
    'scripts/withny_patch/lifecycle.go', 'scripts/withny_patch/probe_windows.go',
    'scripts/withny_patch/remux_windows.go',
})


class GuardError(Exception):
    """Fail closed without including command arguments or credentials in output."""


def git(*args, input=None, optional=False):
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1',
               GIT_GRAFT_FILE=os.devnull)
    try:
        result = subprocess.run(['git', *args], input=input, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, timeout=60)
    except subprocess.TimeoutExpired:
        raise GuardError('Git 校验超时，拒绝操作；请检查远程连接后重试。') from None
    if result.returncode and not optional:
        raise GuardError(f'Git {args[0]} 校验失败；请检查仓库、远程连接及本地对象是否完整。')
    return result.stdout if result.returncode == 0 else None


def paths_from(data):
    return data.decode('utf-8', errors='surrogateescape').split('\0')


def local_paths(paths):
    return [path for path in paths if path and
            path.replace('\\', '/').split('/')[0].casefold() in LOCAL_ROOT_PATHS]


def violations(paths):
    invalid = []
    for path in paths:
        normalized = path.replace('\\', '/')
        parts = PurePosixPath(normalized).parts
        if not parts:
            continue
        top = parts[0].casefold()
        if (top in LOCAL_ROOT_PATHS
                or (top == 'dependency' and not (
                    len(parts) == 2 and parts[-1].endswith('.LICENSE')))
                or (top == 'tests' and len(parts) == 2
                    and parts[-1].startswith('test_') and parts[-1].endswith('.py'))
                or (top == 'scripts' and normalized not in MAINTAINED_SCRIPTS)):
            invalid.append(path)
    return invalid


def check(*, staged=False):
    # Always inspect the entire index, including previously tracked local files.
    # Staged deletions disappear from this list, so cleanup commits remain possible.
    invalid = violations(paths_from(git('ls-files', '--cached', '-z')))
    if invalid:
        print('拒绝提交：根目录 cookies.txt、settings.ini、urls.txt、download、.ai、.claude、'
              'temp 仅留本地；dependency 仅保留根目录 *.LICENSE，'
              'scripts 仅保留明确维护的脚本；测试放入 tests 的功能子目录。', file=sys.stderr)
        for path in invalid:
            print(f'  {ascii(path)}', file=sys.stderr)
        print('使用 git rm --cached 取消跟踪；不要用 git add -f 绕过目录规则。', file=sys.stderr)
    return 1 if invalid else 0


def commit_oid(oid, *, optional=False):
    value = git('rev-parse', '--verify', f'{oid}^{{commit}}', optional=optional)
    if value is None:
        return None
    commit = value.decode('ascii').strip()
    if not OBJECT_ID.fullmatch(commit):
        raise GuardError('无法解析提交对象，拒绝推送。')
    return commit


def check_push(lines, remote_location):
    tips, excluded, new_ref = set(), set(), False
    for line in lines:
        fields = line.split()
        if len(fields) != 4 or not all(OBJECT_ID.fullmatch(oid) for oid in (fields[1], fields[3])):
            raise GuardError('无法解析 pre-push 输入，拒绝推送。')
        _, local_oid, _, remote_oid = fields
        if not local_oid.strip('0'):
            continue  # Ref deletion transmits no new local history.
        tips.add(commit_oid(local_oid))
        if not remote_oid.strip('0'):
            new_ref = True
        else:
            old = commit_oid(remote_oid, optional=True)
            if old:
                excluded.add(old)
    if not tips:
        return 0
    if git('rev-parse', '--is-shallow-repository').strip() != b'false':
        raise GuardError('浅克隆无法完整检查待推送历史；请补全历史后重试。')
    if new_ref:
        # Query the actual destination, never stale refs/remotes/* or local tags.
        # Unknown remote objects are not excluded: scanning more is safer than
        # silently missing commits. This also covers first pushes to a new remote.
        for entry in git('ls-remote', '--refs', '--', remote_location).splitlines():
            fields = entry.split(b'\t', 1)
            if len(fields) != 2:
                raise GuardError('无法读取远程引用，拒绝推送。')
            oid = fields[0].decode('ascii')
            if not OBJECT_ID.fullmatch(oid):
                raise GuardError('远程对象格式无效，拒绝推送。')
            old = commit_oid(oid, optional=True)
            if old:
                excluded.add(old)
    revisions = '\n'.join([*sorted(tips), *('^' + oid for oid in sorted(excluded))]) + '\n'
    commits = set(git('rev-list', '--stdin', input=revisions.encode('ascii')).decode('ascii').splitlines())
    # Also enforce a clean target tree when a new ref points at an existing commit.
    for commit in sorted(commits | tips):
        invalid = local_paths(paths_from(git('ls-tree', '--name-only', '-z', commit)))
        if invalid:
            print(f'拒绝推送：提交 {commit[:12]} 包含根目录本地数据。', file=sys.stderr)
            for path in invalid:
                print(f'  {ascii(path)}', file=sys.stderr)
            print('请从尚未推送的每个提交中移除这些路径；追加删除提交仍会上传旧内容。', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--staged', action='store_true', help='Check the complete proposed commit index')
    mode.add_argument('--pre-push', nargs=2, metavar=('REMOTE', 'LOCATION'), help='Check history from hook stdin')
    args = parser.parse_args()
    try:
        code = check_push(sys.stdin, args.pre_push[1]) if args.pre_push else check(staged=args.staged)
    except (GuardError, OSError, UnicodeError) as exc:
        # Never echo subprocess stderr or a remote URL, which may include a token.
        print(str(exc) if isinstance(exc, GuardError) else '仓库校验无法完成，拒绝操作。', file=sys.stderr)
        code = 1
    raise SystemExit(code)
