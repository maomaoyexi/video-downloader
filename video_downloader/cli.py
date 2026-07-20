"""
video_downloader.cli - 命令行模式
直接传 URL 或 --batch 即可下载，使用默认配置，自动识别平台。
不依赖 AppContainer/HTTP/SSE，纯函数 + subprocess 轻量实现。
"""
import os
import subprocess
import sys
from pathlib import Path

from .core.command import build_ytdlp_cmd
from .core.constants import DEFAULT_CONFIG, VERSION, PLATFORM_INFO
from .core.platform import clean_url, detect_platform


def _print_help():
    """打印 CLI 帮助。"""
    print(f"""
多平台视频下载工具 {VERSION} — 命令行模式
===========================================

用法:
  {sys.argv[0]} <URL>                  直接下载单个视频（自动识别平台）
  {sys.argv[0]} --batch [文件]         批量下载（默认读取 urls.txt）
  {sys.argv[0]} --help / -h            查看此帮助
  {sys.argv[0]}                        启动 WebUI 模式（无参数）

示例:
  {sys.argv[0]} https://www.bilibili.com/video/BV1xx
  {sys.argv[0]} https://youtube.com/watch?v=dQw4w9WgXcQ
  {sys.argv[0]} --batch
  {sys.argv[0]} --batch my_links.txt

说明:
  - CLI 模式使用默认配置：最佳画质、H.264、MP4、4线程、Cookie 自动
  - 平台根据 URL 域名自动识别，无需手动指定（支持 YouTube/Bilibili/Twitch/Niconico/Fantia）
  - 下载文件保存到工具目录下的「平台名/作者名/」文件夹
  - 如需自定义配置（画质、编码、代理等），请启动 WebUI 在设置页面调整
  - 依赖 yt-dlp.exe 和 ffmpeg.exe 需位于工具目录中
""".strip())
    print()


def _find_tool_dir():
    """找到工具目录（yt-dlp.exe / ffmpeg.exe 所在目录）。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def _get_exe_suffix():
    return ".exe" if os.name == "nt" else ""


def run_cli(argv):
    """CLI 入口。解析参数并执行对应命令。"""
    if not argv:
        _print_help()
        return 0

    arg1 = argv[0]

    # --help / -h
    if arg1 in ("--help", "-h", "help"):
        _print_help()
        return 0

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
    exe_suffix = _get_exe_suffix()

    url = clean_url(url)
    if not url:
        print("错误: URL 无效或为空")
        return 1

    platform = detect_platform(url)
    config = dict(DEFAULT_CONFIG)
    if platform:
        config["PLATFORM"] = platform
        print(f"平台: {platform} (自动识别)")
    else:
        print(f"平台: {config['PLATFORM']} (未识别域名，使用默认)")

    # 检查依赖
    ytdlp = tool_dir / f"yt-dlp{exe_suffix}"
    ffmpeg = tool_dir / f"ffmpeg{exe_suffix}"
    if not ytdlp.exists():
        print(f"错误: 找不到 {ytdlp.name}，请将其放到工具目录中")
        return 1
    if not ffmpeg.exists():
        print(f"警告: 找不到 {ffmpeg.name}，部分功能可能不可用")

    try:
        cmd = build_ytdlp_cmd(url, config, tool_dir, exe_suffix)
    except Exception as exc:
        print(f"错误: 命令构建失败 - {exc}")
        return 1

    print(f"链接: {url}")
    print(f"保存: {tool_dir / config['PLATFORM']}")
    print()

    try:
        # CLI 模式下直接输出到终端，不隐藏窗口
        proc = subprocess.Popen(cmd, cwd=str(tool_dir))
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
