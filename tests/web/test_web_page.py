from tests.helpers import PROJECT_ROOT
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_downloader.web.rendering import SESSION_TOKEN_PLACEHOLDER, read_error_manual, render_html_page, serve_static_file


def _skip_if_frozen():
    import sys
    if getattr(sys, "frozen", False):
        raise unittest.SkipTest("PyInstaller frozen mode")


class WebPageTests(unittest.TestCase):
    def test_error_manual_preserves_current_document_text(self):
        _skip_if_frozen()
        expected = (Path(PROJECT_ROOT) / "docs" / "错误码.txt").read_bytes().decode("utf-8")
        self.assertEqual(read_error_manual(), {
            "title": "错误与排查手册", "text": expected, "source": "docs/错误码.txt"
        })

    def test_error_manual_uses_bundled_docs_in_frozen_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            docs.mkdir()
            (docs / "错误码.txt").write_bytes("测试手册\r\n原样保留换行\r\n".encode("utf-8"))
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", directory, create=True):
                self.assertEqual(read_error_manual()["text"], "测试手册\r\n原样保留换行\r\n")

    def test_error_manual_unavailable_does_not_fall_back_to_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", directory, create=True):
                self.assertIsNone(read_error_manual())

    def test_render_replaces_session_token(self):
        token = "test-session-token"
        rendered = render_html_page(token)
        self.assertIsInstance(rendered, bytes)
        text = rendered.decode("utf-8")
        # Token is injected via window.SESSION_TOKEN inline script
        self.assertIn(f'window.SESSION_TOKEN = "{token}";', text)
        self.assertNotIn(SESSION_TOKEN_PLACEHOLDER, text)

    def test_current_version_changelog_matches_about_and_bundle(self):
        from pathlib import Path
        from video_downloader.core.constants import VERSION
        root = Path(PROJECT_ROOT)
        version = VERSION.split()[0]
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        html = (root / "resource/templates/index.html").read_text(encoding="utf-8")
        spec = (root / f"视频下载工具{version}-GUI.spec").read_text(encoding="utf-8")
        self.assertIn("## " + version + "\n", changelog)
        self.assertIn(f'id="aboutReleaseTitle">{version} 本版更新', html)
        self.assertIn('id="aboutReleaseDetails"', html)
        self.assertIn('project_root / "CHANGELOG.md"', spec)

    def test_v271_attribution_is_consistent_and_preserves_history(self):
        from pathlib import Path
        root = Path(PROJECT_ROOT)
        statement = "v2.7.1 的全部更新由 maomaoyexi 完成。"
        for name in ("CHANGELOG.md", "CREDITS.txt"):
            self.assertIn(statement, (root / name).read_text(encoding="utf-8"), name)
        for name in ("README.md", "RELEASE_NOTES.md"):
            public_document = (root / name).read_text(encoding="utf-8")
            self.assertNotIn(statement, public_document, name)
            self.assertNotIn("**v2.7.1 全部更新**", public_document, name)
            self.assertRegex(public_document, r"\| \[.*maomaoyexi.*\]\(https://github\.com/maomaoyexi\) \| v2\.7\.1 全部更新", name)
        html = (root / "resource/templates/index.html").read_text(encoding="utf-8")
        author = re.search(r'id="aboutReleaseAuthor">(.*?)</p>', html, re.S)
        self.assertIsNotNone(author)
        self.assertEqual(re.sub(r"<[^>]+>", "", author.group(1)), statement)
        self.assertIn('id="creditV271"', html)
        self.assertIn("v2.7.0 PR #18", html)
        self.assertIn("v2.7.0 维护", html)
        credits = (root / "CREDITS.txt").read_text(encoding="utf-8")
        self.assertIn("v2.7.0 PR #18 的全部新增功能", credits)

    def test_template_keeps_expected_structure(self):
        _skip_if_frozen()
        base = str(PROJECT_ROOT)
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
        self.assertIn('id="btnCopyCommand"', html)
        self.assertIn('id="speedText"', html)
        self.assertIn('id="sw_subtitles"', html)
        self.assertIn('id="s_subtitle_type"', html)
        self.assertIn('id="subtitleDownloadDialog"', html)
        self.assertIn('id="btnSubtitleDownload"', html)
        self.assertIn('id="coverDownloadDialog"', html)
        self.assertIn('id="btnCoverDownload"', html)
        self.assertIn('data-panel="coverDownloadDialog"', html)
        self.assertIn('id="task_ytdlp_args"', html)
        self.assertIn('id="s_ytdlp_default_args"', html)
        self.assertIn('id="sw_youtube_po_token"', html)

    def test_reset_config_uses_post(self):
        _skip_if_frozen()
        base = str(PROJECT_ROOT)
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # reset-config 使用 POST 在 JS 中
        self.assertIn("api('/api/reset-config', {method:'POST'})", js)
        self.assertIn("api('/api/start-withny-live'", js)

    def test_settings_javascript_only_references_existing_form_controls(self):
        """设置加载/保存不能读取模板中不存在的控件。"""
        _skip_if_frozen()
        base = str(PROJECT_ROOT)
        with open(os.path.join(base, "resource", "templates", "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(base, "resource", "static", "js", "app.js"), "r", encoding="utf-8") as f:
            js = f.read()

        settings_js = js[js.index("function applyConfig"):js.index("async function saveSettings()")]
        referenced_ids = set(
            re.findall(r"(?:\$|isOn|setSwitch)\('([^']+)'", settings_js)
        )
        template_ids = set(re.findall(r'id="([^"]+)"', html))

        self.assertEqual(set(), referenced_ids - template_ids)

    def test_only_light_dark_theme_remains(self):
        """配色切换（Everforest ↔ 中性）已整套删除，只剩明暗两态。"""
        _skip_if_frozen()
        base = str(PROJECT_ROOT)
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
        base = str(PROJECT_ROOT)
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # 关键 API 端点仍在 JS 中
        self.assertIn("/api/events?token=", js)
        self.assertIn("/api/start", js)
        self.assertIn("/api/start-withny-archive", js)
        self.assertIn("/api/current-command", js)
        self.assertIn("/api/download-subtitles", js)
        self.assertIn("/api/download-covers", js)
        self.assertIn("[LEGACY_ALL_SUBTITLE_LANGS, '全部字幕']", js)
        self.assertIn("[DEFAULT_SUBTITLE_LANGS, '中文（默认）']", js)
        self.assertIn('{name:"Withny",color:"#22C55E"}', js)
        self.assertIn("/api/do-update", js)

    def test_bilibili_part_title_uses_safe_dom_properties(self):
        _skip_if_frozen()
        base = str(PROJECT_ROOT)
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
