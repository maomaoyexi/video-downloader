def build_ytdlp_cmd(url, config, tool_dir, exe_suffix="", *, is_live=False, platform_override=None, cookie_file=None, bili_parts=None, nicochannel_auth_token=None):
    """构建 yt-dlp 下载命令行参数。

    根据配置项组装完整的 yt-dlp 命令行参数列表，包括输出模板、格式选择、
    音频处理、代理、Cookie、编码器等全部选项。

    Args:
        url: 目标视频/直播链接。
        config: 配置字典，包含分辨率、编码、音频质量等全部设置项。
        tool_dir: 工具目录路径（yt-dlp.exe/ffmpeg.exe 所在目录）。
        exe_suffix: 可执行文件后缀，Windows 下为 ".exe"，其他平台为空。
        is_live: 是否为直播下载，直播使用 --live-from-start 并归入直播目录。
        platform_override: 平台覆盖名，如果不为 None 则替代 config 中的 PLATFORM。
        cookie_file: Cookie 文件路径，用于文件模式 Cookie 鉴权。
        bili_parts: Bilibili 分P 选择参数，如 "1,3,5" 或 "all"，通过 -I 传递给 yt-dlp。
        nicochannel_auth_token: NicoChannel 的 JWT 鉴权令牌，通过 --extractor-args 注入。

    Returns:
        list[str]: 完整的 yt-dlp 命令行参数列表。
    """
    cfg = config
    ytdlp = str(tool_dir / f"yt-dlp{exe_suffix}")
    cmd = [ytdlp, "--newline", "--continue", "--encoding", "utf-8",
           "--socket-timeout", "30", "--plugin-dirs", str(tool_dir)]
    platform_name = platform_override if platform_override else cfg["PLATFORM"]
    is_nico_live = "live.nicovideo.jp" in url.lower() or "live2.nicovideo.jp" in url.lower()

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
            tool_dir / platform_name / "%(uploader)s" / "直播" / f"{vod_date_prefix}%(title)s - %(id)s.%(ext)s") if vod_date_prefix else str(
            tool_dir / platform_name / "%(uploader)s" / "直播" / "%(title)s - %(upload_date)s %(id)s.%(ext)s")
        cmd += ["--live-from-start"]
    elif is_nico_live:
        out_tmpl = str(
            tool_dir / "Niconico" / "直播" / f"{vod_date_prefix}%(title)s - %(id)s.%(ext)s") if vod_date_prefix else str(
            tool_dir / "Niconico" / "直播" / "%(title)s - %(upload_date)s %(id)s.%(ext)s")
    else:
        out_tmpl = str(tool_dir / platform_name / "%(uploader)s" / f"{vod_date_prefix}%(title)s [%(id)s].%(ext)s")

    cmd += ["-o", out_tmpl]
    archive = tool_dir / f"{platform_name.lower()}_archive.txt"
    cmd += ["--download-archive", str(archive)]

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
    if cfg["PROXY_ENABLED"]:
        cmd += ["--proxy", f"{cfg['PROXY_TYPE']}://{cfg['PROXY_ADDR']}:{cfg['PROXY_PORT']}"]
    if cfg["USE_COOKIES"]:
        if cfg["COOKIE_MODE"] == 1:
            if cookie_file is not None:
                cmd += ["--cookies", str(cookie_file)]
        else:
            cmd += ["--cookies-from-browser", f"{cfg['BROWSER_NAME']}:{cfg['BROWSER_PROFILE']}"]
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
    cmd += ["--ffmpeg-location", str(tool_dir)]
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
    cmd.append(url)
    return cmd
