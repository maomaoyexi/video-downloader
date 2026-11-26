package io.github.maomaoyexi.videodownloader.prototype;

import io.github.maomaoyexi.videodownloader.prototype.PlatformCookies.Platform;

public final class CookieDownloadFailureTest {
    public static void main(String[] args) {
        expect(Platform.YOUTUBE, "WARNING: The provided YouTube account cookies are no longer valid.\n"
                + "ERROR: [youtube] sample: Sign in to confirm you’re not a bot.", "登录 Cookie 已失效");
        expect(Platform.YOUTUBE, "ERROR: [youtube] sample: Sign in to confirm you’re not a bot.", "账号验证");
        expect(Platform.YOUTUBE, "ERROR: [youtube] sample: This is a private video.", "观看权限");
        expect(Platform.YOUTUBE, "ERROR: [youtube] sample: Unable to download API page: The read operation timed out", "连接 YouTube 超时");
        expect(Platform.YOUTUBE, "ERROR: unable to download video data: HTTP Error 403: Forbidden", "HTTP 403");
        expect(Platform.YOUTUBE, "ERROR: unable to download video data: HTTP Error 429: Too Many Requests", "HTTP 429");
        expect(Platform.YOUTUBE, "WARNING: [youtube] sample: n challenge solving failed: Some formats may be missing.\n"
                + "ERROR: Requested format is not available.", "解析校验失败");
        expect(Platform.BILIBILI, "ERROR: [BiliBili] sample: Requested format is not available.", "画质不可用");
        expect(Platform.YOUTUBE, "WARNING: skipping cookie entry with invalid length", "Cookie 文件格式");
        expect(Platform.YOUTUBE, "WARNING: skipping cookie file entry due to invalid length", "Cookie 文件格式");
        expect(Platform.YOUTUBE, "ERROR: Cookies file must be Netscape formatted, not JSON", "Cookie 文件格式");
        expect(Platform.BILIBILI, "ERROR: [BiliBili] sample: You have exceeded the rate limit. Try again later", "限制了请求频率");
        expect(Platform.BILIBILI, "ERROR: [BiliBili] Request is blocked by server (412)", "HTTP 412");
        expect(Platform.BILIBILI, "UnicodeEncodeError: 'latin-1' codec can't encode characters", "Cookie 含有");
        expect(Platform.YOUTUBE, "ERROR: extractor returned an unrecognized error", "解析视频时");
        expect(Platform.YOUTUBE, null, "下载引擎异常退出，未返回错误详情");
        System.out.println("Cookie 下载错误安全分类通过");
    }

    private static void expect(Platform platform, String diagnostic, String expected) {
        String marker = "SYNTHETIC_CREDENTIAL_DO_NOT_DISPLAY";
        String input = diagnostic == null ? null : diagnostic + "\n" + marker;
        String detail = CookieDownloadFailure.describe(input, platform, "解析视频");
        if (!detail.contains(expected) || detail.contains(marker)) {
            throw new AssertionError("预期受控提示包含「" + expected + "」，实际为「" + detail + "」");
        }
    }
}
