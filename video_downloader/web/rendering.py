"""
前端页面渲染与静态文件服务。
模板文件位于 templates/ 目录，静态资源位于 static/ 目录。
Session Token 通过模板占位符 __SESSION_TOKEN__ 注入。
"""

import os
import mimetypes

SESSION_TOKEN_PLACEHOLDER = "__SESSION_TOKEN__"

# 项目根目录，用于定位模板和静态文件（rendering.py 在 web/ 子目录，需要上两级到项目根）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RESOURCE_DIR = os.path.join(_PROJECT_ROOT, "resource")
_TEMPLATE_DIR = os.path.join(_RESOURCE_DIR, "templates")
_STATIC_DIR = os.path.join(_RESOURCE_DIR, "static")

# 确保标准 MIME 类型（Windows 上 mimetypes 可能不完整）
_MIME_MAP = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".eot": "application/vnd.ms-fontobject",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def _get_template_path():
    """获取 index.html 模板的完整路径（兼容 PyInstaller 打包）。"""
    # PyInstaller 打包后 __file__ 可能不准确，优先使用 sys._MEIPASS
    import sys
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = _RESOURCE_DIR
    return os.path.join(base, "templates", "index.html")


def _get_static_path():
    """获取 static 目录的完整路径（兼容 PyInstaller 打包）。"""
    import sys
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "static")
    return _STATIC_DIR


def render_html_page(token: str) -> bytes:
    """读取模板文件，替换 Session Token 并返回 HTML 内容。"""
    template_path = _get_template_path()

    # 如果模板文件不存在，回退到内联的简化页面
    if not os.path.isfile(template_path):
        return _fallback_html(token)

    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace(SESSION_TOKEN_PLACEHOLDER, token)
    return html.encode("utf-8")


def serve_static_file(request_path: str):
    """服务静态文件请求。
    返回 (bytes_content, content_type_str) 或 (None, None) 表示文件不存在。
    """
    # 安全：仅允许 /static/ 前缀，防止目录穿越
    # request_path 形如 /static/css/style.css
    normalized = os.path.normpath(request_path.lstrip("/"))
    # 确保请求路径确实在 static 目录下
    parts = normalized.replace("\\", "/").split("/")
    if not parts or parts[0] != "static":
        return None, None

    # 获取相对路径（去掉 static/ 前缀）
    relative = "/".join(parts[1:])
    static_root = _get_static_path()
    file_path = os.path.normpath(os.path.join(static_root, relative))

    # 安全检查：确保解析后的路径仍在 static 目录内
    if not file_path.startswith(os.path.normpath(static_root) + os.sep) and file_path != os.path.normpath(static_root):
        return None, None

    if not os.path.isfile(file_path):
        return None, None

    # 确定 MIME 类型
    _, ext = os.path.splitext(file_path)
    content_type = _MIME_MAP.get(ext.lower())
    if content_type is None:
        content_type, _ = mimetypes.guess_type(file_path)
        if content_type is None:
            content_type = "application/octet-stream"

    try:
        with open(file_path, "rb") as f:
            return f.read(), content_type
    except (IOError, OSError):
        return None, None


def _fallback_html(token: str) -> bytes:
    """当模板文件不可用时的最小回退页面。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>多平台视频下载工具</title>
<script>window.SESSION_TOKEN="{token}";</script>
</head>
<body style="background:#0f1117;color:#e8eaed;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif">
<div style="text-align:center">
<h1>多平台视频下载工具</h1>
<p style="color:#9aa0ac">前端资源文件 (templates/ static/) 未找到。</p>
<p style="color:#9aa0ac">请确保运行目录下包含完整的模板和静态文件。</p>
</div>
</body>
</html>""".encode("utf-8")
