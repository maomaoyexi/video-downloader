"""
video_downloader.cli - 命令行模式
直接传 URL 或 --batch 自动识别平台；普通 yt-dlp 下载使用默认配置。
Rplay 与 FANBOX 使用各自专项入口并读取已保存配置；FANBOX 另提供扫描和归档命令。
不依赖 AppContainer/HTTP/SSE，纯函数 + subprocess 轻量实现。
"""
import os
import subprocess
import sys
from pathlib import Path

from .core.command import build_ytdlp_cmd
from .core.constants import DEFAULT_CONFIG, VERSION
from .core.paths import AppPaths
from .core.platform import clean_url, detect_platform, is_live_url


def _print_help():
    """打印 CLI 帮助。"""
    print(f"""
多平台视频下载工具 {VERSION} — 命令行模式
===========================================

用法:
  {sys.argv[0]} <URL>                  直接下载单个视频（自动识别平台）
  {sys.argv[0]} --batch [文件]         批量下载（默认读取 urls.txt）
  {sys.argv[0]} --fanbox-scan <URL> --output <清单.json> [选项]
                                      FANBOX 扫描清单，不下载附件
  {sys.argv[0]} --fanbox-download <URL> [选项]
                                      FANBOX 内容归档
  {sys.argv[0]} --fanbox-scan --help    查看 FANBOX 扫描选项
  {sys.argv[0]} --fanbox-download --help
                                      查看 FANBOX 归档与恢复选项
  {sys.argv[0]} --help / -h            查看此帮助
  {sys.argv[0]}                        启动 WebUI 模式（无参数）

示例:
  {sys.argv[0]} https://www.bilibili.com/video/BV1xx
  {sys.argv[0]} https://youtube.com/watch?v=dQw4w9WgXcQ
  {sys.argv[0]} --batch
  {sys.argv[0]} --batch my_links.txt
  {sys.argv[0]} --fanbox-scan https://creator.fanbox.cc --output manifest.json --anonymous
  {sys.argv[0]} --fanbox-download https://creator.fanbox.cc --preview

说明:
  - URL 识别包含 YouTube/Bilibili/Twitch/Niconico/NicoChannel/Fantia/TwitCasting/Twitter/Rplay/FANBOX；各平台支持的链接和权限不同
  - 普通 yt-dlp URL 和 --batch 中的普通视频使用 DEFAULT_CONFIG：最佳画质与编码、MP4、4线程，不读取 WebUI 保存的配置
  - 普通 CLI 不会自动应用 WebUI 保存的 Cookie 设置；自定义画质、代理、登录及 Fantia 专项下载请使用 WebUI
  - Rplay URL 使用专项入口读取 settings.ini；受限内容使用独立 Firefox 授权，普通 cookies.txt 不能替代；未完成文件重试会重新下载
  - FANBOX URL 和 --fanbox-download 读取 settings.ini 中的专项配置；需指定 --cookies 凭据文件或 --anonymous 时，请使用 --fanbox-download
  - --fanbox-scan 和 --fanbox-download 均读取 FANBOX_ANONYMOUS、FANBOX_COOKIE_FILE 和 USE_COOKIES；未指定凭据路径时使用工具目录 cookies.txt
  - 两个 FANBOX 命令的显式 --anonymous 或 --cookies 优先于保存设置，且彼此互斥；相对凭据路径以工具目录为基准
  - FANBOX 正文、图片、附件和外链清单以当前权限为准；外链仅记录，不下载外站内容；不保证所有平台的列表/频道均可下载
  - 普通视频保存到「download/平台名/作者名/」，FANBOX 默认归档到「download/Fanbox/」
  - 普通视频依赖 dependency 中的 yt-dlp.exe 和 ffmpeg.exe，Rplay 还需 ffprobe.exe；FANBOX 使用独立运行依赖
  - Withny HAR 存档和配置录制请使用 WebUI；此 CLI 没有对应 HAR 导入命令
  - 推荐下载限速 5–10 MB/s；高速或大批量下载可能导致 IP 或账号被限制或封禁，相关后果由使用者自行承担
""".strip())
    print()


def _find_tool_dir():
    """找到应用程序根目录（包含 dependency 和 download 子目录）。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def _get_exe_suffix():
    return ".exe" if os.name == "nt" else ""


def run_cli(argv):
    """CLI 入口。解析参数并执行对应命令。"""
    # Redirected Windows consoles can default to GBK; video titles may contain
    # emoji. Keep command output consistent with the UTF-8 downloader stream.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    if not argv:
        _print_help()
        return 0

    arg1 = argv[0]

    # --help / -h
    if arg1 in ("--help", "-h", "help"):
        _print_help()
        return 0

    if arg1 == "--fanbox-scan":
        from .platforms.fanbox.cli import main as fanbox_scan
        return fanbox_scan(argv[1:], root=_find_tool_dir())

    if arg1 == '--fanbox-download':
        from .platforms.fanbox.download_cli import main as fanbox_download
        return fanbox_download(argv[1:],root=_find_tool_dir())

    # --batch [file]
    if arg1 in ("--batch", "-b"):
        file_path = argv[1] if len(argv) > 1 else "urls.txt"
        return _cmd_batch(file_path)

    # URL → download
    if arg1.startswith(("http://", "https://")):
        return _cmd_download(arg1)

    # Unknown
    print(f"未知参数: {arg1}")
    print("使用 --help 查看可用命令。")
    return 1


def _cmd_download(url):
    """下载单个视频。"""
    tool_dir = _find_tool_dir()
    paths = AppPaths(tool_dir)
    paths.ensure_runtime_dirs()
    exe_suffix = _get_exe_suffix()

    url = clean_url(url)
    if not url:
        print("错误: URL 无效或为空")
        return 1

    platform = detect_platform(url)
    from .services.routed_executor import is_fanbox
    if is_fanbox(url):
        from .platforms.fanbox.download_cli import main as fanbox_download
        return fanbox_download([url],root=tool_dir)
    if platform == 'Rplay':
        from .platforms.rplay_cli import download
        return download(url, paths, exe_suffix)
    config = dict(DEFAULT_CONFIG)
    if platform:
        config["PLATFORM"] = platform
        print(f"平台: {platform} (自动识别)")
    else:
        print(f"平台: {config['PLATFORM']} (未识别域名，使用默认)")

    # TwitCasting 密码保护内容需通过 WebUI 下载，CLI 不支持交互式密码输入
    if platform == "TwitCasting":
        print("提示: TwitCasting 内容可能受密码保护。如遇下载失败，请启动 WebUI 模式下载。")
        print("      WebUI 中可在设置页预填密码，或在收到密码提示弹窗后输入。")
        print()

    # NicoChannel: CLI 不支持自动提取 Firefox localStorage JWT
    if platform == "NicoChannel":
        print("提示: NicoChannel 首次下载需要在 WebUI 模式下完成（自动从 Firefox 提取 JWT 令牌）。")
        print("      后续下载可通过 CLI 进行（令牌由 yt-dlp 插件通过 Cookie 文件自动刷新）。")
        print()

    # 检查依赖
    ytdlp = paths.executable("yt-dlp", exe_suffix)
    ffmpeg = paths.executable("ffmpeg", exe_suffix)
    if not ytdlp.exists():
        print(f"错误: 找不到 {ytdlp.name}，请将其放到 dependency 目录中")
        return 1
    if not ffmpeg.exists():
        print(f"警告: 找不到 {ffmpeg.name}，部分功能可能不可用")

    try:
        cmd = build_ytdlp_cmd(
            url,
            config,
            tool_dir,
            exe_suffix,
            is_live=is_live_url(url, platform),
            platform_override=platform,
            live_mode=config.get("LIVE_MODE", "auto"),
        )
    except Exception as exc:
        print(f"错误: 命令构建失败 - {exc}")
        return 1

    print(f"链接: {url}")
    print(f"保存: {paths.download_dir / config['PLATFORM']}")
    print()

    try:
        # CLI 模式下直接输出到终端，不隐藏窗口
        env = paths.subprocess_env()
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        proc = subprocess.Popen(cmd, cwd=str(tool_dir), env=env)
        proc.wait()
        if proc.returncode == 0:
            print("\n✓ 下载完成!")
            return 0
        else:
            print(f"\n✗ 下载失败 (退出码 {proc.returncode})")
            return 1
    except KeyboardInterrupt:
        print("\n已取消。")
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass
        return 130
    except Exception as exc:
        print(f"\n错误: {exc}")
        return 1


def _cmd_batch(file_path):
    """批量下载 urls.txt 中的链接。"""
    tool_dir = _find_tool_dir()

    urls_file = Path(file_path)
    if not urls_file.is_absolute():
        urls_file = tool_dir / file_path

    if not urls_file.exists():
        print(f"错误: 找不到文件 {urls_file}")
        print("提示: 在工具目录下创建 urls.txt，每行一个链接（支持 # 注释）")
        return 1

    urls = []
    with open(urls_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)

    if not urls:
        print(f"错误: {urls_file} 中没有找到任何有效链接")
        return 1

    print(f"批量下载: {len(urls)} 个链接 (来自 {urls_file.name})")
    print()

    ok = 0
    fail = 0
    for i, url in enumerate(urls, 1):
        print(f"=== [{i}/{len(urls)}] ===")
        rc = _cmd_download(url)
        if rc == 0:
            ok += 1
        else:
            fail += 1
        print()

    print(f"=== 批量下载完成: 成功 {ok}, 失败 {fail}, 总计 {len(urls)} ===")
    return 0 if fail == 0 else 1
