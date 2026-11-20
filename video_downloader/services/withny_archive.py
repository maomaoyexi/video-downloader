import base64
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse


class WithnyArchiveError(Exception):
    pass


def sanitized_url(value):
    parsed = urlparse(value or "")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}{parsed.path}"


def _response_text(content):
    text = content.get("text", "")
    if not isinstance(text, str):
        return ""
    if str(content.get("encoding", "")).lower() == "base64":
        try:
            return base64.b64decode(text, validate=True).decode("utf-8")
        except (ValueError, UnicodeError):
            return ""
    return text


def playlist_type(text):
    upper = text.lstrip("\ufeff\r\n\t ").upper()
    if not upper.startswith("#EXTM3U"):
        return None
    if "#EXT-X-STREAM-INF" in upper:
        return "master"
    if "#EXTINF" in upper or "#EXT-X-TARGETDURATION" in upper:
        return "media"
    return "hls"


def encryption_tags(text):
    tags = []
    pattern = r"#EXT-X-(?:SESSION-)?KEY\s*:\s*([^\r\n]+)"
    for match in re.finditer(pattern, text, re.IGNORECASE):
        attrs = match.group(1)
        method = re.search(r"(?:^|,)\s*METHOD\s*=\s*([^,\s]+)", attrs, re.IGNORECASE)
        keyformat = re.search(r"(?:^|,)\s*KEYFORMAT\s*=\s*\"?([^,\"\s]+)", attrs, re.IGNORECASE)
        tags.append({
            "method": method.group(1).upper() if method else "UNKNOWN",
            "keyformat": keyformat.group(1) if keyformat else "identity",
        })
    return tags


def _request_cookies(request):
    cookies = {}
    cookie_items = request.get("cookies", [])
    headers = request.get("headers", [])
    if not all(isinstance(items, list) and all(isinstance(item, dict) for item in items)
               for items in (cookie_items, headers)):
        raise WithnyArchiveError("HAR 中的 Cookie 或请求头格式无效")
    for item in cookie_items:
        name = str(item.get("name", "")).strip()
        value = str(item.get("value", ""))
        if name and value:
            cookies[name.lower()] = (name, value)
    for header in headers:
        if str(header.get("name", "")).lower() != "cookie":
            continue
        for part in str(header.get("value", "")).split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name and value:
                cookies[name.lower()] = (name, value)
    return cookies


def load_and_select(har_path, max_size=64 * 1024 * 1024):
    path = Path(har_path)
    try:
        if path.stat().st_size > max_size:
            raise WithnyArchiveError("HAR 文件超过 64 MB 限制")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except WithnyArchiveError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WithnyArchiveError(f"无法读取 HAR: {exc}") from None

    log = data.get("log") if isinstance(data, dict) else None
    entries = log.get("entries") if isinstance(log, dict) else None
    if not isinstance(entries, list):
        raise WithnyArchiveError("HAR 不包含有效的网络请求列表")

    archive_url = ""
    records = []
    drm_signal = False
    cloudfront_names = {"cloudfront-key-pair-id", "cloudfront-policy", "cloudfront-signature"}
    signed_cookies = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise WithnyArchiveError("HAR 中的网络请求记录格式无效")
        request = entry.get("request", {})
        response = entry.get("response", {})
        if not isinstance(request, dict) or not isinstance(response, dict):
            raise WithnyArchiveError("HAR 中的请求或响应格式无效")
        content = response.get("content", {})
        if not isinstance(content, dict):
            raise WithnyArchiveError("HAR 中的响应内容格式无效")
        raw_url = request.get("url", "")
        if not isinstance(raw_url, str):
            raise WithnyArchiveError("HAR 中的请求地址格式无效")
        try:
            parsed = urlparse(raw_url)
            port = parsed.port
        except ValueError:
            raise WithnyArchiveError("HAR 中的请求地址格式无效") from None
        cookies = _request_cookies(request)
        signed_cookies.update({name: value for name, value in cookies.items() if name in cloudfront_names})
        if parsed.hostname and parsed.hostname.lower() in {"withny.fun", "www.withny.fun"} and re.fullmatch(r"/user/archives/[0-9a-f-]+/?", parsed.path, re.IGNORECASE):
            archive_url = sanitized_url(raw_url)
        text = _response_text(content)
        kind = playlist_type(text)
        mime = str(content.get("mimeType", "")).lower()
        if any(term in raw_url.lower() for term in ("widevine", "fairplay", "playready", "clearkey", "license", "licence", "drm")):
            drm_signal = True
        if not (parsed.path.lower().endswith(".m3u8") or "mpegurl" in mime or kind):
            continue
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or port not in {None, 443}:
            raise WithnyArchiveError("播放列表地址不符合安全要求")
        records.append({
            "index": index,
            "raw_url": raw_url,
            "display_url": sanitized_url(raw_url),
            "status": response.get("status", 0),
            "text": text,
            "type": kind or "hls",
            "cookies": cookies,
        })

    if not archive_url:
        raise WithnyArchiveError("HAR 中没有有效的 Withny 历史存档页面")
    if drm_signal:
        raise WithnyArchiveError("检测到 DRM 信号，已拒绝下载")
    if not records:
        raise WithnyArchiveError("HAR 中没有检测到 HLS 播放列表")

    valid = []
    for record in records:
        if not isinstance(record["status"], int) or not 200 <= record["status"] < 300 or not record["text"]:
            continue
        tags = [tag for tag in encryption_tags(record["text"]) if tag["method"] != "NONE"]
        if any(tag["keyformat"].lower() != "identity" for tag in tags):
            raise WithnyArchiveError("检测到 DRM KeyFormat，已拒绝下载")
        if tags:
            raise WithnyArchiveError("检测到加密 HLS，已拒绝下载")
        valid.append(record)

    media = [record for record in valid if record["type"] == "media"]
    masters = [record for record in valid if record["type"] == "master"]
    if not media:
        raise WithnyArchiveError("未取得媒体播放列表正文，请重新导出包含内容的 HAR")
    selected = max(masters or media, key=lambda item: item["index"])
    if selected["display_url"].startswith("https://archive.withny.fun/"):
        missing = cloudfront_names - set(signed_cookies)
        if missing:
            raise WithnyArchiveError("HAR 缺少 CloudFront 签名 Cookie，请启用“允许生成包含敏感数据的 HAR”后重新导出")
    cookie_header = "; ".join(
        f"{signed_cookies[name][0]}={signed_cookies[name][1]}"
        for name in sorted(cloudfront_names & set(signed_cookies))
    )
    if "\r" in cookie_header or "\n" in cookie_header:
        raise WithnyArchiveError("HAR Cookie 格式无效")
    duration = sum(float(value) for value in re.findall(r"#EXTINF\s*:\s*([0-9.]+)", "\n".join(item["text"] for item in media), re.IGNORECASE))
    return selected, archive_url, duration, cookie_header


def build_ffmpeg_command(ffmpeg, input_url, output, cookie_header=""):
    output = Path(output)
    temp = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.part{output.suffix}")
    command = [
        str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "warning",
        "-protocol_whitelist", "http,https,tcp,tls", "-referer", "https://www.withny.fun/",
    ]
    if cookie_header:
        command += ["-headers", f"Cookie: {cookie_header}\r\n"]
    command += [
        "-i", input_url, "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
        "-progress", "pipe:1", "-nostats",
    ]
    if output.suffix.lower() == ".mp4":
        command += ["-movflags", "+faststart"]
    command += ["-n", str(temp)]
    return command, temp


def redact_line(value, raw_url):
    text = value.replace(raw_url, sanitized_url(raw_url))
    return re.sub(r"https?://[^\s'\"]+", lambda match: sanitized_url(match.group(0)), text)
