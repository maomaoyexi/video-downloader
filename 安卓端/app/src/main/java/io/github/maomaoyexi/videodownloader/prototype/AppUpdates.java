package io.github.maomaoyexi.videodownloader.prototype;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class AppUpdates {
    private static final String REPO = "maomaoyexi/video-downloader";
    private static final String API = "https://api.github.com/repos/" + REPO + "/releases?per_page=30&page=";
    private static final String DOWNLOAD_BASE = "https://github.com/" + REPO + "/releases/download/";
    private static final String TAG_PREFIX = "android-v";
    private static final Pattern VERSION = Pattern.compile("(0|[1-9][0-9]{0,8})\\.(0|[1-9][0-9]{0,8})\\.(0|[1-9][0-9]{0,8})");
    private static final int MAX_REPLY_BYTES = 2 * 1024 * 1024;
    private static final int MAX_PAGES = 10;

    private AppUpdates() {}

    static Result check(String installedVersion) {
        int[] installed = parseVersion(installedVersion);
        if (installed == null) return Result.error("无法识别当前应用版本。");

        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20);
        Release latest = null;
        try {
            for (int page = 1; page <= MAX_PAGES; page++) {
                int timeout = Math.min(8000, remainingMillis(deadline));
                HttpURLConnection connection = (HttpURLConnection) new URL(API + page).openConnection();
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(timeout);
                connection.setReadTimeout(timeout);
                connection.setRequestProperty("Accept", "application/vnd.github+json");
                connection.setRequestProperty("X-GitHub-Api-Version", "2022-11-28");
                connection.setRequestProperty("User-Agent", "VideoDownloaderAndroid/" + installedVersion);
                try {
                    int status = connection.getResponseCode();
                    if (status == 429 || status == 403 && "0".equals(connection.getHeaderField("X-RateLimit-Remaining"))) {
                        return Result.error("GitHub 请求次数达到上限，请稍后再试。");
                    }
                    if (status != HttpURLConnection.HTTP_OK) {
                        return Result.error("GitHub 暂时无法提供更新信息，请稍后重试。");
                    }
                    try (InputStream input = connection.getInputStream()) {
                        latest = newestRelease(new JSONArray(readReply(input, deadline)), latest);
                    }
                    String links = connection.getHeaderField("Link");
                    if (links == null || !links.contains("rel=\"next\"")) {
                        return resultFor(latest, installed);
                    }
                } finally {
                    connection.disconnect();
                }
            }
        } catch (JSONException error) {
            return Result.error("GitHub 返回的更新信息无法读取，请稍后重试。");
        } catch (IOException | SecurityException error) {
            return Result.error("无法连接 GitHub，请检查网络后重试。");
        }
        return Result.error("暂时无法确认最新版本，请稍后重试。");
    }

    static Release newestRelease(JSONArray releases, Release latest) {
        for (int i = 0; i < releases.length(); i++) {
            JSONObject item = releases.optJSONObject(i);
            if (item == null || item.optBoolean("draft") || item.optBoolean("prerelease")) continue;
            String tag = item.optString("tag_name");
            if (!tag.startsWith(TAG_PREFIX)) continue;
            String versionName = tag.substring(TAG_PREFIX.length());
            int[] version = parseVersion(versionName);
            if (version == null || latest != null && compare(version, latest.version) <= 0) continue;
            String filename = "video-downloader-android-" + versionName + "-arm64-v8a.apk";
            String url = DOWNLOAD_BASE + tag + "/" + filename;
            JSONArray assets = item.optJSONArray("assets");
            if (assets == null) continue;
            for (int j = 0; j < assets.length(); j++) {
                JSONObject asset = assets.optJSONObject(j);
                if (asset != null && filename.equals(asset.optString("name"))
                        && "uploaded".equals(asset.optString("state")) && asset.optLong("size") > 0
                        && url.equals(asset.optString("browser_download_url"))) {
                    String notes = item.isNull("body") ? "" : item.optString("body").trim();
                    if (notes.length() > 4000) notes = notes.substring(0, 4000) + "\n…";
                    latest = new Release(versionName, version, notes, url);
                    break;
                }
            }
        }
        return latest;
    }

    static int[] parseVersion(String value) {
        if (value == null) return null;
        Matcher matcher = VERSION.matcher(value);
        if (!matcher.matches()) return null;
        return new int[]{Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)),
                Integer.parseInt(matcher.group(3))};
    }

    static Result resultFor(Release latest, int[] installed) {
        if (latest == null) return new Result("unpublished", null, "GitHub 暂无可下载的安卓正式版。");
        if (compare(latest.version, installed) <= 0) {
            return new Result("current", null, "当前已经是最新版本。");
        }
        return new Result("available", latest, "");
    }

    private static int compare(int[] left, int[] right) {
        for (int i = 0; i < left.length; i++) {
            int order = Integer.compare(left[i], right[i]);
            if (order != 0) return order;
        }
        return 0;
    }

    private static int remainingMillis(long deadline) throws IOException {
        long remaining = TimeUnit.NANOSECONDS.toMillis(deadline - System.nanoTime());
        if (remaining <= 0) throw new IOException("Release request timed out");
        return (int) remaining;
    }

    private static String readReply(InputStream input, long deadline) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int read;
        while ((read = input.read(buffer)) != -1) {
            remainingMillis(deadline);
            if (output.size() + read > MAX_REPLY_BYTES) throw new IOException("Release list too large");
            output.write(buffer, 0, read);
        }
        return new String(output.toByteArray(), StandardCharsets.UTF_8);
    }

    static final class Release {
        final String versionName;
        final int[] version;
        final String notes;
        final String downloadUrl;

        Release(String versionName, int[] version, String notes, String downloadUrl) {
            this.versionName = versionName;
            this.version = version;
            this.notes = notes;
            this.downloadUrl = downloadUrl;
        }
    }

    static final class Result {
        final String status;
        final Release release;
        final String message;

        Result(String status, Release release, String message) {
            this.status = status;
            this.release = release;
            this.message = message;
        }

        static Result error(String message) {
            return new Result("error", null, message);
        }
    }
}
