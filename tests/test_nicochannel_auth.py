import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

from video_downloader.services.nicochannel_auth import NicochannelAuthService


def mock_nicochannel_dependencies():
    yt_dlp = ModuleType("yt_dlp")
    cookies = ModuleType("yt_dlp.cookies")
    cookies._firefox_browser_dirs = []
    cookies._firefox_cookie_dbs = []
    cookies._is_path = lambda *args: False
    cookies._newest = lambda *args: None
    cookies._open_database_copy = lambda *args: None
    utils = ModuleType("yt_dlp.utils")
    utils.try_call = lambda *args, **kwargs: None
    cramjam = ModuleType("cramjam")
    return patch.dict(sys.modules, {
        "yt_dlp": yt_dlp,
        "yt_dlp.cookies": cookies,
        "yt_dlp.utils": utils,
        "cramjam": cramjam,
    })


class NicochannelAuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.logs: list[tuple[str, str]] = []

        def fake_log(msg: str, level: str = "info") -> None:
            self.logs.append((msg, level))

        self.service = NicochannelAuthService(log=fake_log)

    # ── _find_jwt ──────────────────────────────────────────────

    def test_find_jwt_returns_body_from_localstorage_item(self):
        jwt = (
            "eyJhbGciOiJIUzI1NiJ9.eyJhY2Nlc3NfdG9rZW4iOiJ0ZXN0In0."
            "signature"
        )
        items = {
            "some_key": '{"body": "' + jwt + '", "access_token": "x"}',
        }
        result = self.service._find_jwt(items)
        self.assertEqual(result, jwt)

    def test_find_jwt_skips_malformed_json(self):
        items = {"key1": "not json at all", "key2": '{"no_body": 1}'}
        result = self.service._find_jwt(items)
        self.assertIsNone(result)

    def test_find_jwt_ignores_non_jwt_body(self):
        items = {"key1": '{"body": "not-a-jwt", "access_token": "x"}'}
        result = self.service._find_jwt(items)
        self.assertIsNone(result)

    def test_find_jwt_returns_none_for_empty_dict(self):
        result = self.service._find_jwt({})
        self.assertIsNone(result)

    def test_find_jwt_from_auth0_cache_dict_body(self):
        """Auth0 cache: body is a dict with access_token field."""
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20ifQ.sig"
        items = {
            "@@auth0spajs@@::xxx::api.nicochannel.jp::openid": (
                '{"body":{"access_token":"' + jwt + '","scope":"openid","expires_in":86400}}'
            ),
        }
        result = self.service._find_jwt(items)
        self.assertEqual(result, jwt)

    def test_find_jwt_from_persisted_user_info(self):
        """Persist auth: JWT nested inside string-encoded JSON."""
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJuZXN0ZWQiOnRydWV9.sig"
        items = {
            "persist:auth": (
                '{"totalUserInformation":'
                '"{\\"root\\":{\\"userInformation\\":{\\"accessToken\\":\\"' + jwt + '\\"}}}"'
                '}'
            ),
        }
        result = self.service._find_jwt(items)
        self.assertEqual(result, jwt)

    def test_find_jwt_skips_body_dict_without_jwt_dots(self):
        """Auth0 body dict with non-JWT access_token is ignored."""
        items = {
            "key": '{"body":{"access_token":"not-a-jwt-string"}}',
        }
        result = self.service._find_jwt(items)
        self.assertIsNone(result)

    # ── caching ────────────────────────────────────────────────

    def test_get_auth_token_caches_result(self):
        """Second call returns cached token without re-extraction."""
        with patch.object(
            self.service, "_locate_ff_profile", side_effect=RuntimeError("should not be called twice")
        ):
            # Manually seed the cache
            self.service._cached_token = "cached-jwt-xxx.yyy.zzz"
            result = self.service.get_auth_token()
            self.assertEqual(result, "cached-jwt-xxx.yyy.zzz")

    # ── missing dependencies ───────────────────────────────────

    @patch("video_downloader.services.nicochannel_auth.NicochannelAuthService._locate_ff_profile")
    def test_returns_none_when_firefox_profile_not_found(self, mock_locate):
        mock_locate.side_effect = FileNotFoundError("no profile")
        with mock_nicochannel_dependencies():
            result = self.service.get_auth_token()
        self.assertIsNone(result)
        self.assertTrue(
            any("Firefox 配置未找到" in msg for msg, _ in self.logs),
            f"Expected warning log not found in {self.logs}",
        )

    @patch("video_downloader.services.nicochannel_auth.NicochannelAuthService._locate_ff_profile")
    def test_returns_none_on_unexpected_error(self, mock_locate):
        mock_locate.side_effect = OSError("permission denied")
        with mock_nicochannel_dependencies():
            result = self.service.get_auth_token()
        self.assertIsNone(result)
        self.assertTrue(
            any("提取 JWT 失败" in msg for msg, _ in self.logs),
            f"Expected error log not found in {self.logs}",
        )


if __name__ == "__main__":
    unittest.main()
