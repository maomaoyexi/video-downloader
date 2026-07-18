import os
import unittest

from video_downloader.web.rendering import SESSION_TOKEN_PLACEHOLDER, render_html_page, serve_static_file


def _skip_if_frozen():
    import sys
    if getattr(sys, "frozen", False):
        raise unittest.SkipTest("PyInstaller frozen mode")


class WebPageTests(unittest.TestCase):
    def test_render_replaces_session_token(self):
        token = "test-session-token"
        rendered = render_html_page(token)
        self.assertIsInstance(rendered, bytes)
        text = rendered.decode("utf-8")
        # Token is injected via window.SESSION_TOKEN inline script
        self.assertIn(f'window.SESSION_TOKEN = "{token}";', text)
        self.assertNotIn(SESSION_TOKEN_PLACEHOLDER, text)

    def test_template_keeps_expected_structure(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(base, "resource", "templates", "index.html")
        self.assertTrue(os.path.isfile(template_path), f"Template missing: {template_path}")
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", html)
        # HTML 结构检查
        self.assertIn("page-download", html)
        self.assertIn("page-settings", html)
        self.assertIn("page-history", html)
        self.assertIn("page-tools", html)
        self.assertIn("page-help", html)
        self.assertIn("page-about", html)
        # 引用了外部 CSS/JS
        self.assertIn("/static/css/style.css", html)
        self.assertIn("/static/js/app.js", html)
        # Token 占位符
        self.assertIn("__SESSION_TOKEN__", html)

    def test_reset_config_uses_post(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # reset-config 使用 POST 在 JS 中
        self.assertIn("api('/api/reset-config', {method:'POST'})", js)

    def test_app_js_has_api_endpoints(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # 关键 API 端点仍在 JS 中
        self.assertIn("/api/events?token=", js)
        self.assertIn("/api/start", js)
        self.assertIn("/api/do-update", js)

    def test_serve_static_file_css(self):
        content, mime = serve_static_file("/static/css/style.css")
        self.assertIsNotNone(content)
        self.assertIn("text/css", mime)
        self.assertIn(b":root", content)

    def test_serve_static_file_js(self):
        content, mime = serve_static_file("/static/js/app.js")
        self.assertIsNotNone(content)
        self.assertIn("javascript", mime)

    def test_serve_static_file_not_found(self):
        content, mime = serve_static_file("/static/nonexistent.file")
        self.assertIsNone(content)
        self.assertIsNone(mime)

    def test_serve_static_file_path_traversal_blocked(self):
        content, mime = serve_static_file("/static/../../../etc/passwd")
        self.assertIsNone(content)
        self.assertIsNone(mime)

    def test_serve_static_file_non_static_prefix_blocked(self):
        content, mime = serve_static_file("/api/config")
        self.assertIsNone(content)
        self.assertIsNone(mime)

    def test_fallback_html(self):
        from video_downloader.web.rendering import _fallback_html
        html = _fallback_html("fallback-token")
        self.assertIsInstance(html, bytes)
        text = html.decode("utf-8")
        self.assertIn("fallback-token", text)


if __name__ == "__main__":
    unittest.main()
