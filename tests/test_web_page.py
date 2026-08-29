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
        self.assertIn('class="app"', html)
        self.assertIn('class="rail" aria-label="应用侧栏"', html)
        self.assertIn('class="main"', html)
        self.assertIn('aria-label="主导航"', html)
        self.assertIn("ErgouTree", html)
        self.assertIn("@ergou10086", html)
        self.assertIn("https://github.com/ergou10086", html)
        self.assertIn("DarkKandaoMaster", html)
        self.assertIn("强壮的砍刀", html)
        self.assertIn("https://github.com/DarkKandaoMaster", html)
        self.assertIn("https://github.com/maomaoyexi", html)
        # 自建单色墨系设计系统：base.css 定义令牌与组件，dark.css 只覆盖变量
        self.assertIn("/static/css/base.css", html)
        self.assertIn("/static/css/dark.css", html)
        self.assertIn("/static/css/responsive.css", html)
        self.assertIn("/static/css/animations.css", html)
        self.assertIn("/static/js/app.js", html)
        self.assertNotIn("tabler.min.css", html)
        self.assertNotIn("tabler.min.js", html)
        # 图标为内联 SVG sprite，不再有独立的 icons.js
        self.assertIn('<symbol id="i-download"', html)
        self.assertNotIn("/static/js/icons.js", html)
        # 下载历史的列表 / 网格视图切换
        self.assertIn('id="viewList"', html)
        self.assertIn('id="viewGrid"', html)
        # Token 占位符
        self.assertIn("__SESSION_TOKEN__", html)
        self.assertIn('id="btnWithnyLive"', html)
        self.assertIn('id="nicochannelHint"', html)

    def test_reset_config_uses_post(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # reset-config 使用 POST 在 JS 中
        self.assertIn("api('/api/reset-config', {method:'POST'})", js)
        self.assertIn("api('/api/start-withny-live'", js)

    def test_only_light_dark_theme_remains(self):
        """配色切换（Everforest ↔ 中性）已整套删除，只剩明暗两态。"""
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "resource", "templates", "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(base, "resource", "static", "js", "theme.js"), "r", encoding="utf-8") as f:
            js = f.read()
        with open(os.path.join(base, "resource", "static", "css", "dark.css"), "r", encoding="utf-8") as f:
            css = f.read()
        self.assertNotIn("data-palette", html)
        self.assertNotIn("paletteToggle", html)
        self.assertNotIn("video-dl-palette", js)
        self.assertNotIn("togglePalette", js)
        self.assertIn("video-dl-theme", js)
        self.assertIn("toggleTheme", js)
        self.assertIn('theme-toggle', html)
        # 深色只覆盖 :root 里的颜色变量
        self.assertIn('[data-theme="dark"]{', css)

    def test_app_js_has_api_endpoints(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # 关键 API 端点仍在 JS 中
        self.assertIn("/api/events?token=", js)
        self.assertIn("/api/start", js)
        self.assertIn("/api/start-withny-archive", js)
        self.assertIn('{name:"Withny",color:"#22C55E"}', js)
        self.assertIn("/api/do-update", js)

    def test_bilibili_part_title_uses_safe_dom_properties(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        self.assertIn("title.title = String(p.title ?? '');", js)
        self.assertIn("title.textContent = String(p.title ?? '');", js)
        self.assertNotIn("list.innerHTML = parts.map", js)

    def test_serve_static_file_css(self):
        content, mime = serve_static_file("/static/css/base.css")
        self.assertIsNotNone(content)
        self.assertIn("text/css", mime)
        self.assertIn(b":root", content)

    def test_animation_styles_keep_motion_accessible(self):
        content, mime = serve_static_file("/static/css/animations.css")
        self.assertIsNotNone(content)
        self.assertIn("text/css", mime)
        self.assertIn(b"@keyframes page-in", content)
        self.assertIn(b"prefers-reduced-motion:reduce", content)

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
