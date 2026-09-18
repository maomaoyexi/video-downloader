import ctypes
import os
import shlex
import sys
from pathlib import Path

from .constants import DEFAULT_SUBTITLE_LANGS
from .paths import AppPaths


_TWITCASTING_PLUGIN_RELATIVE_PATH = (
    "yt-dlp-plugins/video_downloader/yt_dlp_plugins/"
    "postprocessor/twitcasting_parallel.py"
)


def twitcasting_hls_fallback_args(tool_dir):
    """返回多初始化段回退参数；插件缺失时安全降级为纯 FFmpeg。"""
    args = [
        "--downloader", "m3u8:ffmpeg",
        # 对插件不接管的播放列表显式启用 HLS 连接复用，避免依赖 FFmpeg
        # 不同版本的 auto 默认值。
        "--downloader-args", "ffmpeg_i:-http_persistent 1 -http_multiple 1",
    ]
    tool_dir = Path(tool_dir)
    paths = AppPaths(tool_dir)
    configured_plugin_dirs = paths.plugin_dirs()
    plugin_root = None
    for candidate in (
        paths.dependency_dir,
        tool_dir,
        Path(sys._MEIPASS) if getattr(sys, "_MEIPASS", None) else None,
    ):
        if candidate and (candidate / _TWITCASTING_PLUGIN_RELATIVE_PATH).is_file():
            plugin_root = candidate
            break
    if plugin_root is None:
        return args

    plugin_dir_args = []
    if plugin_root not in configured_plugin_dirs:
        # PyInstaller 单文件版的数据文件位于 _MEIPASS；外部 yt-dlp 需要显式
        # 获得该临时目录，才能发现打包进去的插件。
        plugin_dir_args = ["--plugin-dirs", str(plugin_root)]
    return [
        *plugin_dir_args,
        "--enable-file-urls",
        "--use-postprocessor", "TwitCastingParallelHls:when=before_dl",
        "--use-postprocessor", "TwitCastingParallelHls:when=post_process;cleanup=true",
        *args,
    ]


def _browser_cookie_spec(cfg):
    """构建 yt-dlp 的浏览器 Cookie 参数，允许 Firefox 自动探测 Profile。"""
    browser = str(cfg.get("BROWSER_NAME") or "").strip().lower()
    profile = str(cfg.get("BROWSER_PROFILE") or "").strip()
    # "Default" 是 Chromium 的常见目录名，也是本项目的历史默认值；Firefox
    # 通常使用随机前缀目录。切换浏览器后继续传 firefox:Default 会导致 yt-dlp
    # 在一个不存在的目录中查找数据库，因此让 yt-dlp 自动选择最近使用的 Profile。
    if browser == "firefox" and profile.lower() == "default":
        profile = ""
    return f"{browser}:{profile}" if profile else browser


def _append_proxy_option(cmd, cfg):
    """显式表达代理开关，避免关闭代理时仍继承系统代理环境变量。"""
    if cfg["PROXY_ENABLED"]:
        proxy = f"{cfg['PROXY_TYPE']}://{cfg['PROXY_ADDR']}:{cfg['PROXY_PORT']}"
    else:
        proxy = ""
    cmd += ["--proxy", proxy]


def _append_cookie_options(cmd, cfg, cookie_file):
    if not cfg["USE_COOKIES"]:
        return
    if cfg["COOKIE_MODE"] == 1:
        if cookie_file is not None:
            cmd += ["--cookies", str(cookie_file)]
    else:
        browser_spec = _browser_cookie_spec(cfg)
        if browser_spec:
            cmd += ["--cookies-from-browser", browser_spec]


def _append_subtitle_options(cmd, cfg, download_dir, platform_name, also_set_default_output=False):
    if not cfg.get("DOWNLOAD_SUBTITLES", 0):
        return False
    subtitle_type = cfg.get("SUBTITLE_TYPE", "all")
    subtitle_langs = cfg.get("SUBTITLE_LANGS") or DEFAULT_SUBTITLE_LANGS
    subtitle_tmpl = download_dir / platform_name / "subtitles" / "%(title)s [%(id)s].%(ext)s"
    if also_set_default_output:
        cmd += ["-o", str(subtitle_tmpl)]
    cmd += ["-o", f"subtitle:{subtitle_tmpl}"]
    if subtitle_type in {"all", "manual"}:
        cmd.append("--write-subs")
    if subtitle_type in {"all", "auto"}:
        cmd.append("--write-auto-subs")
    cmd += ["--sub-langs", subtitle_langs]
    return True


def parse_custom_ytdlp_args(value):
    """把用户填写的 yt-dlp 参数安全拆成 ``Popen`` 参数列表。

    参数始终通过列表传给子进程，不经过 shell，因此引号只负责把带空格的值
    组合为同一个参数。空输入返回空列表。
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    text = str(value).strip()
    if not text:
        return []
    try:
        # shlex is used here to give a clear error for unclosed quotes on every OS.
        shlex.split(text, posix=True)
    except ValueError as exc:
        raise ValueError(f"自定义 yt-dlp 参数无法解析: {exc}") from exc
    if os.name != "nt":
        return shlex.split(text, posix=True)

    # Match the quoting rules users see in CMD/PowerShell and preserve unquoted
    # backslashes in Windows paths. CommandLineToArgvW only tokenizes; no shell runs.
    argc = ctypes.c_int()
    command_line_to_argv = ctypes.windll.shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    command_line_to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argv = command_line_to_argv(text, ctypes.byref(argc))
    if not argv:
        raise ValueError("自定义 yt-dlp 参数无法解析")
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv)


def _append_custom_ytdlp_args(cmd, cfg, custom_args):
    # 默认参数在前、本次参数在后，让本次参数可以按 yt-dlp 的常规规则覆盖默认值。
    cmd += parse_custom_ytdlp_args(cfg.get("YTDLP_DEFAULT_ARGS", ""))
    cmd += parse_custom_ytdlp_args(custom_args)


def build_ytdlp_cmd(url, config, tool_dir, exe_suffix="", *, is_live=False, platform_override=None, cookie_file=None, bili_parts=None, nicochannel_auth_token=None, use_ffmpeg_for_hls=False, include_subtitles=True, subtitle_only=False, custom_args=None, po_token_base_url=None):
    """构建 yt-dlp 下载命令行参数。

    根据配置项组装完整的 yt-dlp 命令行参数列表，包括输出模板、格式选择、
    音频处理、代理、Cookie、编码器等全部选项。

    Args:
        url: 目标视频/直播链接。
        config: 配置字典，包含分辨率、编码、音频质量等全部设置项。
        tool_dir: 应用程序根目录。第三方工具优先从 dependency 子目录加载。
        exe_suffix: 可执行文件后缀，Windows 下为 ".exe"，其他平台为空。
        is_live: 是否为直播下载，直播使用 --live-from-start 并归入直播目录。
        platform_override: 平台覆盖名，如果不为 None 则替代 config 中的 PLATFORM。
        cookie_file: Cookie 文件路径，用于文件模式 Cookie 鉴权。
        bili_parts: Bilibili 分P 选择参数，如 "1,3,5" 或 "all"，通过 -I 传递给 yt-dlp。
        nicochannel_auth_token: NicoChannel 的 JWT 鉴权令牌，通过 --extractor-args 注入。
        use_ffmpeg_for_hls: TwitCasting 遇到多初始化片段的 fMP4 播放列表时，由
            执行器重试阶段置 True，强制改用 FFmpeg 下载 m3u8，绕过 hlsnative 限制。

    Returns:
        list[str]: 完整的 yt-dlp 命令行参数列表。
    """
    cfg = config
    tool_dir = Path(tool_dir)
    paths = AppPaths(tool_dir)
    ytdlp = str(paths.executable("yt-dlp", exe_suffix))
    plugin_dirs = paths.plugin_dirs()
    download_dir = paths.download_dir
    cmd = [
        ytdlp,
        "--newline",
        "--continue",
        "--encoding",
        "utf-8",
        "--socket-timeout",
        "30",
        # 给每条下载进度附加当前格式的音视频编码信息。执行器据此识别
        # 分离流中的视频/音频阶段，前端即可切换进度条颜色。
        "--progress-template",
        (
            "download:[download] %(progress._percent_str)s of "
            "%(progress._total_bytes_str)s at %(progress._speed_str)s "
            "ETA %(progress._eta_str)s "
            "__VD_STAGE__%(info.vcodec)s|%(info.acodec)s"
        ),
    ]
    for plugin_dir in plugin_dirs:
        cmd += ["--plugin-dirs", str(plugin_dir)]
    platform_name = platform_override if platform_override else cfg["PLATFORM"]
    is_nico_live = "live.nicovideo.jp" in url.lower() or "live2.nicovideo.jp" in url.lower()

    if subtitle_only:
        cmd += ["--skip-download"]
        if not _append_subtitle_options(cmd, cfg, download_dir, platform_name, also_set_default_output=True):
            return cmd + [url]
        if cfg["SPEED_LIMIT"] > 0:
            cmd += ["-r", f"{cfg['SPEED_LIMIT']}M"]
        _append_proxy_option(cmd, cfg)
        _append_cookie_options(cmd, cfg, cookie_file)
        if cfg["WIN_FILENAMES"]:
            cmd += ["--windows-filenames"]
        if cfg["STRICT_FILENAME"]:
            cmd += ["--restrict-filenames"]
        if platform_name == "TwitCasting" and cfg.get("TC_PASSWORD"):
            cmd += ["--video-password", cfg["TC_PASSWORD"]]
        if platform_name == "NicoChannel" and nicochannel_auth_token:
            cmd += ["--username", "jwt_token", "--password", nicochannel_auth_token]
        if platform_name == "YouTube" and po_token_base_url:
            cmd += [
                "--extractor-args",
                f"youtubepot-bgutilhttp:base_url={po_token_base_url}",
            ]
        _append_custom_ytdlp_args(cmd, cfg, custom_args)
        cmd.append(url)
        return cmd

    # VOD 模板：开启嵌入元数据时，在文件名前追加 [YYYYMMDD] 发布日期，便于按时间排序
    vod_date_prefix = "[%(upload_date)s] " if cfg["EMBED_META"] else ""

    # 直播统一由调用方传入的 is_live 驱动（Twitch/TwitCasting 等），
    # 使用 --live-from-start 从头抓取并归入直播目录。
    # Niconico 直播/录播（timeshift）不加 --live-from-start：
    #   不加时 → yt-dlp 提取器自行判断直播/录播状态，录播下载全量分片后退出，
    #            直播从当前时刻开始录制。
    #   加了  → 对无 timeshift 缓冲的直播直接报错 "no formats that can be
    #            downloaded from the start"，录播也会失败。
    # 因此 Niconico 由 yt-dlp 自行决定，仅指定输出目录。
    #
    # 直播文件名规则：
    #   EMBED_META=1 → "[20260730] title - id.ext"（日期前缀，方便按时间排序归档）
    #   EMBED_META=0 → "title - 20260730 id.ext"（日期在标题后，保持原有格式）
    if is_live and not is_nico_live:
        out_tmpl = str(
            download_dir / platform_name / "%(uploader)s" / "直播" / f"{vod_date_prefix}%(title)s - %(id)s.%(ext)s") if vod_date_prefix else str(
            download_dir / platform_name / "%(uploader)s" / "直播" / "%(title)s - %(upload_date)s %(id)s.%(ext)s")
        cmd += ["--live-from-start"]
    elif is_nico_live:
        out_tmpl = str(
            download_dir / "Niconico" / "直播" / f"{vod_date_prefix}%(title)s - %(id)s.%(ext)s") if vod_date_prefix else str(
            download_dir / "Niconico" / "直播" / "%(title)s - %(upload_date)s %(id)s.%(ext)s")
    else:
        out_tmpl = str(download_dir / platform_name / "%(uploader)s" / f"{vod_date_prefix}%(title)s [%(id)s].%(ext)s")

    cmd += ["-o", out_tmpl]
    archive = paths.archive(f"{platform_name.lower()}_archive.txt")
    cmd += ["--download-archive", str(archive)]

    if include_subtitles:
        _append_subtitle_options(cmd, cfg, download_dir, platform_name)

    res = cfg["RESOLUTION"]
    codec = cfg["CODEC"]
    res_str = f"[height<={res}]" if res != "best" else ""
    if codec == "h264":
        vcodec = "[vcodec~='avc1|h264']"
    elif codec == "av1":
        vcodec = "[vcodec~='av01']"
    elif codec == "vp9":
        vcodec = "[vcodec~='vp9']"
    else:
        vcodec = ""

    audio_q = cfg["AUDIO_QUALITY"]
    aformat_base = f"bestaudio[abr<={audio_q}]" if audio_q != "best" else "bestaudio"
    fmt = cfg["OUTPUT_FORMAT"]
    vcodec_part = res_str + vcodec
    vfmt = f"bestvideo{vcodec_part}+{aformat_base}/best{vcodec_part}/best"

    # === 音频处理方案 ===
    audio_mode = cfg.get("AUDIO_MODE", "0")
    audio_fmt = cfg.get("AUDIO_FORMAT", "mp3")

    if audio_mode == "3":
        # 只输出音频：bestaudio 优先（有独立音频流则直下），否则回退 best 再提取
        # 不加 --keep-video，下载的中间视频文件自动丢弃
        afilter = f"[abr<={audio_q}]" if audio_q != "best" else ""
        cmd += ["-f", f"bestaudio{afilter}/best"]
        cmd += ["-x", "--audio-format", audio_fmt]
    elif audio_mode == "2":
        # 同时输出音频：与模式 0 一样先合并下载，下载完成后由 download_executor
        # 调 ffmpeg 从合并文件中提取指定格式音频，避免 --keep-video 导致中间裸流残留
        cmd += ["-f", vfmt, "--merge-output-format", fmt]
        if fmt != "webm":
            cmd += ["--remux-video", fmt]
    elif audio_mode == "1":
        # 分离音画：视频和音频分开下载，不合并，各自保持原生格式
        # 添加 /best 回退以兼容仅提供单一合并流的平台（如 TwitCasting）
        cmd += ["-f", f"bestvideo{vcodec_part},{aformat_base}/best{vcodec_part}/best"]
    else:
        # 模式 "0"（默认）：正常合并为单一视频文件
        cmd += ["-f", vfmt, "--merge-output-format", fmt]
        if fmt != "webm":
            cmd += ["--remux-video", fmt]

    cmd += ["-N", str(cfg["THREADS"])]
    if cfg["SPEED_LIMIT"] > 0:
        cmd += ["-r", f"{cfg['SPEED_LIMIT']}M"]
    _append_proxy_option(cmd, cfg)
    _append_cookie_options(cmd, cfg, cookie_file)
    if cfg["EMBED_META"]:
        cmd += ["--embed-metadata"]
    if cfg["DOWNLOAD_THUMB"]:
        cmd += ["--write-thumbnail", "--convert-thumbnails", "jpg"]
        # 正常合并模式（且非 WebM）才嵌图
        if audio_mode == "0" and fmt != "webm":
            cmd += ["--embed-thumbnail"]
    if cfg["WIN_FILENAMES"]:
        cmd += ["--windows-filenames"]
    if cfg["STRICT_FILENAME"]:
        cmd += ["--restrict-filenames"]
    if cfg["HWACCEL"] != "cpu":
        cmd += ["--postprocessor-args", f"Merger+ffmpeg_o:-c:v {cfg['HWACCEL']}"]
    cmd += ["--ffmpeg-location", str(paths.executable("ffmpeg", exe_suffix).parent)]
    # TwitCasting 的部分 fMP4 HLS 录像会在播放列表中途切换初始化片段，
    # yt-dlp 原生 hlsnative 下载器会因此报
    # "Initialization fragment found after media fragments"。默认仍用原生
    # 下载器（可并发 -N 个分片，速度更快）；仅在检测到该错误后由执行器重试
    # 时置 use_ffmpeg_for_hls，让 FFmpeg 接管 m3u8 下载以兼容这类播放列表。
    if platform_name == "TwitCasting" and use_ffmpeg_for_hls:
        # before_dl 插件并发预取带多个 EXT-X-MAP 的远程分片，再把本地播放列表
        # 交给 FFmpeg 封装；yt-dlp 因而仍能继续执行元数据、封面和归档流程。
        # 插件若遇到不支持的清单会保持原 URL，自动退回原有 FFmpeg 串行路径。
        cmd += twitcasting_hls_fallback_args(tool_dir)
    # TwitCasting 密码保护/会员限定直播与录播需要通过 --video-password 解锁。
    if platform_name == "TwitCasting" and cfg.get("TC_PASSWORD"):
        cmd += ["--video-password", cfg["TC_PASSWORD"]]
    # 评论抓取与重编码仅对 Niconico 注入。
    if platform_name == "Niconico" and cfg["NICO_COMMENTS"]:
        cmd += ["--write-comments"]
    if platform_name == "Niconico" and cfg["NICO_RECODE"]:
        cmd += ["--recode-video", fmt]
    # NicoChannel: 插件通过 --username jwt_token --password <JWT> 接收鉴权令牌
    # （而非 --extractor-args），详见插件的 _perform_login() 方法
    if platform_name == "NicoChannel" and nicochannel_auth_token:
        cmd += ["--username", "jwt_token", "--password", nicochannel_auth_token]
    # Bilibili 多P选择：通过 -I 指定下载哪些分P
    if bili_parts and bili_parts != "all":
        cmd += ["-I", bili_parts]
    # YouTube 已结束直播的留档（live_status=post_live）在默认播放器客户端下会返回
    # "This live event has ended."，只有 web_embedded 客户端能取到已转码的 VOD。
    # 在默认客户端集之后追加 web_embedded 兜底：正常视频仍优先走默认客户端，
    # 仅当默认客户端无法提取时自动回退，不影响已有下载行为。
    if platform_name == "YouTube":
        cmd += ["--extractor-args", "youtube:player_client=default,web_embedded"]
        if po_token_base_url:
            cmd += [
                "--extractor-args",
                f"youtubepot-bgutilhttp:base_url={po_token_base_url}",
            ]
    _append_custom_ytdlp_args(cmd, cfg, custom_args)
    cmd.append(url)
    return cmd
