import unittest

from video_downloader.web_page import HTML_PAGE, SESSION_TOKEN_PLACEHOLDER, render_html_page


class WebPageTests(unittest.TestCase):
    def test_render_replaces_session_token(self):
        token = "test-session-token"
        rendered = render_html_page(token)
        self.assertIsInstance(rendered, bytes)
        text = rendered.decode("utf-8")
        self.assertIn(f'const SESSION_TOKEN = "{token}";', text)
        self.assertNotIn(SESSION_TOKEN_PLACEHOLDER, text)

    def test_page_keeps_expected_structure(self):
        self.assertTrue(HTML_PAGE.startswith("<!DOCTYPE html>"))
        self.assertTrue(HTML_PAGE.endswith("</html>"))
        self.assertIn("/api/events?token=", HTML_PAGE)
        self.assertIn("/api/start", HTML_PAGE)
        self.assertIn("/api/do-update", HTML_PAGE)

    def test_reset_config_uses_post(self):
        self.assertIn("api('/api/reset-config', {method:'POST'})", HTML_PAGE)


if __name__ == "__main__":
    unittest.main()
