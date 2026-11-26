package io.github.maomaoyexi.videodownloader.prototype;

import io.github.maomaoyexi.videodownloader.prototype.PlatformCookies.Platform;

import java.util.Locale;

final class CookieDownloadFailure {
    private CookieDownloadFailure() {}

    static String describe(String diagnostic, Platform platform, String stage) {
        // Match diagnostic text in memory. Never include engine output in the UI.
        String text = diagnostic == null ? "" : diagnostic.toLowerCase(Locale.ROOT);
        if (text.trim().isEmpty()) {
            return stage + "时，下载引擎异常退出，未返回错误详情。";
        }
        String site = platform.label;
        if (platform == Platform.YOUTUBE && text.contains("the provided youtube account cookies are no longer valid")) {
            return "YouTube 登录 Cookie 已失效，请重新导出并导入。";
        }
        if (containsAny(text, "does not look like a netscape format", "cookies file must be netscape formatted",
                "skipping cookie entry", "skipping cookie file entry")) {
            return "检测到 Cookie 文件格式问题，请重新导出 Netscape 格式的 cookies.txt。";
        }
        if (text.contains("unicodeencodeerror") && text.contains("latin-1")) {
            return "Cookie 含有无法用于网络请求的字符，请重新导出 cookies.txt。";
        }
        if (containsAny(text, "private video", "members-only", "members only",
                "join this channel", "supporter-only video", "not available in your country",
                "deleted or geo-restricted")) {
            return "平台限制了此视频的观看权限，请用同一账号在浏览器确认能否播放。";
        }
        if (containsAny(text, "captcha challenge before playback", "sign in to confirm",
                "authentication required", "login required")) {
            return site + " 要求登录或进行账号验证，请用同一账号在浏览器确认能否播放。";
        }
        if (containsAny(text, "timed out", "connecttimeout", "readtimeout")) {
            return "连接 " + site + " 超时，请检查手机网络或 VPN 后重试。";
        }
        if (containsAny(text, "certificate_verify_failed", "certificate verify failed")) {
            return "连接 " + site + " 时证书校验失败，请检查手机时间和网络设置。";
        }
        if (containsAny(text, "connection refused", "connection reset", "network is unreachable",
                "getaddrinfo failed", "failure in name resolution", "failed to resolve")) {
            return "无法连接 " + site + "，请检查手机网络或代理设置。";
        }
        if (containsAny(text, "http error 403", "http status 403")) {
            return site + " 拒绝了下载请求（HTTP 403），请用同一网络试一条公开视频对照。";
        }
        if (containsAny(text, "http error 429", "http status 429")) {
            return site + " 暂时限制了请求频率（HTTP 429），请稍后再试。";
        }
        if (containsAny(text, "http error 412", "http status 412", "blocked by server (412)")) {
            return site + " 拒绝了这次请求（HTTP 412），请稍后重试。";
        }
        if (text.contains("you have exceeded the rate limit")) {
            return site + " 暂时限制了请求频率，请稍后再试。";
        }
        if (platform == Platform.YOUTUBE && containsAny(text, "no supported javascript runtime", "signature solving failed",
                "n challenge solving failed")) {
            return "YouTube 解析校验失败，可能未取得可下载的格式。请换一条公开视频对照。";
        }
        if (containsAny(text, "requested format is not available", "no video formats found",
                "only images are available")) {
            return "当前画质不可用。可试「自动」，或换一条能正常播放的视频。";
        }
        if (containsAny(text, "unable to extract initial state", "unable to extract video data")) {
            return "下载引擎无法解析 " + site + " 视频信息，请用另一条公开视频对照。";
        }
        return stage + "时，下载引擎返回了未识别的错误。";
    }

    private static boolean containsAny(String text, String... phrases) {
        for (String phrase : phrases) {
            if (text.contains(phrase)) return true;
        }
        return false;
    }
}
