def build_ytdlp_cmd(url, config, tool_dir, exe_suffix="", *, is_live=False, platform_override=None, cookie_file=None, bili_parts=None):
    cfg = config
    ytdlp = str(tool_dir / f"yt-dlp{exe_suffix}")
    cmd = [ytdlp, "--newline", "--continue", "--encoding", "utf-8"]
    platform_name = platform_override if platform_override else cfg["PLATFORM"]
    is_nico_live = "live.nicovideo.jp" in url.lower() or "live2.nicovideo.jp" in url.lower()

    # VOD 模板：开启嵌入元数据时，在文件名前追加 [YYYYMMDD] 发布日期，便于按时间排序
    vod_date_prefix = "[%(upload_date)s] " if cfg["EMBED_META"] else ""

    # Twitch 直播与录像共用入口，显式直播优先走从头抓取模板。
    if is_live or platform_name == "Twitch":
        is_live_download = is_live or ("twitch.tv/" in url.lower() and "/videos/" not in url.lower() and "/clip/" not in url.lower())
        if is_live_download:
            out_tmpl = str(
                tool_dir / platform_name / "%(uploader)s" / "直播" / "%(title)s - %(upload_date)s %(id)s.%(ext)s")
            cmd += ["--live-from-start"]
        else:
            out_tmpl = str(tool_dir / platform_name / "%(uploader)s" / f"{vod_date_prefix}%(title)s [%(id)s].%(ext)s")
    elif is_nico_live:
        # Niconico 直播按 URL 识别，并固定归入直播目录。
        out_tmpl = str(tool_dir / "Niconico" / "直播" / "%(title)s - %(upload_date)s %(id)s.%(ext)s")
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
        cmd += ["-f", f"bestvideo{vcodec_part},{aformat_base}"]
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
    # 评论抓取与重编码仅对 Niconico 注入。
    if platform_name == "Niconico" and cfg["NICO_COMMENTS"]:
        cmd += ["--write-comments"]
    if platform_name == "Niconico" and cfg["NICO_RECODE"]:
        cmd += ["--recode-video", fmt]
    # Bilibili 多P选择：通过 -I 指定下载哪些分P
    if bili_parts and bili_parts != "all":
        cmd += ["-I", bili_parts]
    cmd.append(url)
    return cmd
