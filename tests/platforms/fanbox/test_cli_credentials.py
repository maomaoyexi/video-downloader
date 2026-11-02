from unittest.mock import Mock

import pytest

from video_downloader.platforms.fanbox import cli, download_cli
from video_downloader.platforms.fanbox.controller import FanboxController
from video_downloader.platforms.fanbox.executor import FanboxExecutor
from video_downloader.core.validation import validate_config
from video_downloader.services.download_manager import DownloadManager
from video_downloader.services.storage import StorageService
from video_downloader.state.app_state import AppState
from video_downloader.tasks.manager import TaskCallbacks
from .test_content import post
from .test_integration import ContextTransport


def write_cookie(path, label):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '# Netscape HTTP Cookie File\n'
        f'.fanbox.cc\tTRUE\t/\tTRUE\t0\tFANBOXSESSID\t{label}\n',
        encoding='utf-8',
    )


def save_settings(root, *, anonymous=0, cookie_file='', use_cookies=1):
    state = AppState()
    config, errors = validate_config({
        'FANBOX_ANONYMOUS': anonymous,
        'FANBOX_COOKIE_FILE': cookie_file,
        'USE_COOKIES': use_cookies,
    })
    assert not errors
    state.replace_config(config)
    storage = StorageService(root, state, validate_config, Mock(), Mock())
    storage.save_config()
    return storage, state


def session(credentials):
    return next((cookie.value for cookie in credentials.jar if cookie.name == 'FANBOXSESSID'), None)


def run_cli(entrypoint, root, monkeypatch, extra):
    seen = []
    if entrypoint == 'scan':
        def transport(credentials, **kwargs):
            seen.append(session(credentials))
            return ContextTransport([[post()]])
        monkeypatch.setattr(cli, 'CurlTransport', transport)
        result = cli.main([
            'https://sample.fanbox.cc/', '--output', str(root / 'manifest.json'),
            '--max-posts', '1', *extra,
        ], root=root)
    else:
        class Application:
            def __init__(self, directory):
                pass

            def create(self, url, options):
                return {'id': 'offline-job'}

            def run(self, job_id, **kwargs):
                seen.append(session(kwargs['credentials']))
                return {'status': 'completed'}
        monkeypatch.setattr(download_cli, 'ArchiveApplication', Application)
        result = download_cli.main(['https://sample.fanbox.cc/', *extra], root=root)
    return result, seen


@pytest.mark.parametrize('entrypoint', ['scan', 'download'])
@pytest.mark.parametrize('case', [
    'saved_anonymous', 'saved_relative_cookie', 'saved_absolute_cookie',
    'explicit_cookie_over_saved_anonymous', 'explicit_relative_cookie',
    'explicit_anonymous', 'disabled_cookies', 'explicit_cookie_over_disabled',
    'default_cookie',
])
def test_saved_fanbox_credentials_and_explicit_cli_precedence(tmp_path, monkeypatch, entrypoint, case):
    write_cookie(tmp_path / 'cookies.txt', 'default-session')
    saved = tmp_path / 'auth' / 'saved.txt'
    explicit = tmp_path / 'auth' / 'explicit.txt'
    write_cookie(saved, 'saved-session')
    write_cookie(explicit, 'explicit-session')
    anonymous = int(case in {'saved_anonymous', 'explicit_cookie_over_saved_anonymous'})
    configured = str(saved) if case == 'saved_absolute_cookie' else 'auth/saved.txt'
    if case in {'saved_anonymous', 'default_cookie'}:
        configured = ''
    enabled = int(case not in {'disabled_cookies', 'explicit_cookie_over_disabled'})
    extra = []
    if case.startswith('explicit_cookie_'):
        extra = ['--cookies', str(explicit)]
    elif case == 'explicit_relative_cookie':
        extra = ['--cookies', 'auth/explicit.txt']
    elif case == 'explicit_anonymous':
        extra = ['--anonymous']
    expected = {
        'saved_anonymous': None,
        'saved_relative_cookie': 'saved-session',
        'saved_absolute_cookie': 'saved-session',
        'explicit_cookie_over_saved_anonymous': 'explicit-session',
        'explicit_relative_cookie': 'explicit-session',
        'explicit_anonymous': None,
        'disabled_cookies': None,
        'explicit_cookie_over_disabled': 'explicit-session',
        'default_cookie': 'default-session',
    }[case]
    save_settings(tmp_path, anonymous=anonymous, cookie_file=configured, use_cookies=enabled)
    before = (tmp_path / 'settings.ini').read_bytes()

    result, seen = run_cli(entrypoint, tmp_path, monkeypatch, extra)

    assert result == 0
    assert seen == [expected]
    assert (tmp_path / 'settings.ini').read_bytes() == before


@pytest.mark.parametrize('entrypoint', ['scan', 'download'])
def test_explicit_anonymous_and_cookie_file_are_rejected_together(tmp_path, monkeypatch, entrypoint):
    write_cookie(tmp_path / 'cookies.txt', 'default-session')
    save_settings(tmp_path)
    result, seen = run_cli(entrypoint, tmp_path, monkeypatch, ['--anonymous', '--cookies', 'cookies.txt'])
    assert result == 2 and not seen


@pytest.mark.parametrize('entrypoint', ['scan', 'download'])
def test_explicit_missing_cookie_is_not_hidden_by_saved_anonymous(tmp_path, monkeypatch, entrypoint):
    save_settings(tmp_path, anonymous=1)
    result, seen = run_cli(entrypoint, tmp_path, monkeypatch, ['--cookies', 'missing.txt'])
    assert result == 2 and not seen


@pytest.mark.parametrize('target', ['output', 'checkpoint'])
def test_scan_never_overwrites_configured_credentials(tmp_path, monkeypatch, target):
    cookie = tmp_path / 'auth' / 'saved.txt'
    write_cookie(cookie, 'saved-session')
    save_settings(tmp_path, cookie_file='auth/saved.txt')
    before = cookie.read_bytes()
    transport = Mock(side_effect=AssertionError('transport must not start'))
    monkeypatch.setattr(cli, 'CurlTransport', transport)
    output = cookie if target == 'output' else tmp_path / 'manifest.json'
    extra = ['--checkpoint', str(cookie)] if target == 'checkpoint' else []
    assert cli.main(['https://sample.fanbox.cc/', '--output', str(output), *extra], root=tmp_path) == 2
    assert cookie.read_bytes() == before
    transport.assert_not_called()


@pytest.mark.parametrize('anonymous,use_cookies,expected', [(0, 1, 'saved-session'), (1, 1, None), (0, 0, None)])
def test_webui_saved_settings_already_control_auth_and_executor(tmp_path, anonymous, use_cookies, expected):
    write_cookie(tmp_path / 'cookies.txt', 'default-session')
    write_cookie(tmp_path / 'auth' / 'saved.txt', 'saved-session')
    storage, state = save_settings(tmp_path, anonymous=anonymous, cookie_file='auth/saved.txt', use_cookies=use_cookies)
    state.replace_config(storage.load_config())
    seen = []

    class Application:
        def run(self, job_id, **kwargs):
            seen.append(session(kwargs['credentials']))
            return {'id': job_id, 'status': 'preview_ready', 'counts': {}, 'output': '', 'error': None}

    application = Application()
    controller = FanboxController(application, tool_dir=tmp_path, config_getter=state.config_snapshot,
        start=Mock(), cancel=Mock())
    callbacks = TaskCallbacks(**{key: Mock() for key in TaskCallbacks.__dataclass_fields__})
    executor = FanboxExecutor(application, tool_dir=tmp_path, app_state=state,
        download_manager=DownloadManager(), callbacks=callbacks, job_id='existing-job', preview=True)
    try:
        assert controller.options()['anonymous'] is bool(anonymous)
        assert controller.options()['cookie_file'] == 'auth/saved.txt'
        assert controller.auth_status()['status'] == ('loaded' if expected else 'anonymous')
        assert executor.start_download('https://sample.fanbox.cc/')['ok']
        executor.thread.join(3)
        assert not executor.thread.is_alive()
        assert executor.last_result['status'] == 'preview_ready'
        assert seen == [expected]
    finally:
        controller.stop()
