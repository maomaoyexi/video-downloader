from .constants import AUDIO_SEP_OPTIONS


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
        is_live_url = is_live or "twitch.tv/" in url.lower() and "/videos/" not in url.lower() and "/clip/" not in url.lower()
        if is_live_url:
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
    merge = cfg["MERGE_MODE"]
    sep_mode = cfg["AUDIO_SEP_MODE"]
    fmt = cfg["OUTPUT_FORMAT"]
    vcodec_part = res_str + vcodec
    # 编码筛选失败时逐级回退，避免因站点流信息不完整而无格式可选。
    vfmt = f"bestvideo{vcodec_part}+{aformat_base}/best{vcodec_part}/best"

    if merge == 1:
        cmd += ["-f", vfmt, "--merge-output-format", fmt]
        if fmt != "webm":
            cmd += ["--remux-video", fmt]
        if sep_mode > 0:
            ext = AUDIO_SEP_OPTIONS[sep_mode - 1]
            cmd += ["-x", "--audio-format", ext, "--keep-video"]
    else:
        # 分离模式用逗号分别下载视频与音频，不触发合并后处理。
        separate_vfmt = f"bestvideo{vcodec_part}/bestvideo"
        cmd += ["-f", f"{separate_vfmt},{aformat_base}"]

    # 同时下载音频（独立 MP3 文件），Fantia 除外
    if cfg.get("AUDIO_DOWNLOAD") and platform_name != "Fantia":
        cmd += ["-x", "--audio-format", "mp3", "--keep-video"]
    cmd += ["-N", str(cfg["THREADS"])]
    if cfg["SPEED_LIMIT"] > 0:
        cmd += ["-r", f"{cfg['SPEED_LIMIT']}M"]
    if cfg["PROXY_ENABLED"]:
        cmd += ["--proxy", f"{cfg['PROXY_TYPE']}://{cfg['PROXY_ADDR']}:{cfg['PROXY_PORT']}"]
    if cfg["USE_COOKIES"]:
        if cfg["COOKIE_MODE"] == 1:
            # 手动 Cookie 仅在临时文件就绪时传入，避免空路径参数。
            if cookie_file is not None:
                cmd += ["--cookies", str(cookie_file)]
        else:
            cmd += ["--cookies-from-browser", f"{cfg['BROWSER_NAME']}:{cfg['BROWSER_PROFILE']}"]
    if cfg["EMBED_META"]:
        cmd += ["--embed-metadata"]
    if cfg["DOWNLOAD_THUMB"]:
        cmd += ["--write-thumbnail", "--convert-thumbnails", "jpg"]
        # WebM、音频分离或独立下载时不嵌图，规避后处理冲突。
        if merge == 1 and fmt != "webm" and sep_mode == 0:
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
