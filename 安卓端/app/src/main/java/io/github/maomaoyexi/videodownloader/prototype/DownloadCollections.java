package io.github.maomaoyexi.videodownloader.prototype;

import io.github.maomaoyexi.videodownloader.prototype.PlatformCookies.Platform;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class DownloadCollections {
    private static final int MAX_ENTRIES = 100;
    static final int PROBE_LIMIT = MAX_ENTRIES + 1;
    static final int PART_TITLES_BUDGET_MS = 5_000;
    private static final int PART_TITLES_TIMEOUT_MS = 2_000;
    private static final int MAX_PART_METADATA_BYTES = 512 * 1024;
    private static final Pattern BILIBILI_ID = Pattern.compile("(?i:BV)[A-Za-z0-9]+");
    private static final Pattern BILIBILI_PART = Pattern.compile(
            "https://www\\.bilibili\\.com/video/((?i:BV)[A-Za-z0-9]+)\\?p=([1-9][0-9]{0,8})");

    private DownloadCollections() {}

    static String status(String status, String message) {
        return state(status, message).toString();
    }

    private static JSONObject state(String status, String message) {
        try {
            return new JSONObject().put("status", status).put("message", message);
        } catch (JSONException error) {
            throw new IllegalStateException(error);
        }
    }

    static JSONObject parse(JSONObject result, Platform platform) throws JSONException {
        String type = result.optString("_type", "video");
        if (!"playlist".equals(type)) {
            if (platform == Platform.BILIBILI && "video".equals(type)) return state("single", "");
            return state("error", "未取得可选择的列表，请检查链接后重试。");
        }
        JSONArray source = result.optJSONArray("entries");
        if (source == null) return state("error", "平台未返回可选的视频列表。");
        JSONArray entries = new JSONArray();
        for (int index = 0; index < Math.min(source.length(), MAX_ENTRIES); index++) {
            JSONObject entry = source.optJSONObject(index);
            if (entry == null) continue;
            JSONObject selected = platform == Platform.BILIBILI
                    ? bilibiliEntry(result.optString("id"), entry) : youtubeEntry(entry, index + 1);
            if (selected != null) entries.put(selected);
        }
        if (entries.length() == 0) return state("error", "此列表没有可选的点播视频。");
        String title = title(result, platform == Platform.BILIBILI ? "B 站分 P" : "YouTube 播放列表");
        return new JSONObject().put("status", "ready").put("title", title).put("entries", entries)
                .put("truncated", source.length() > MAX_ENTRIES || result.optInt("playlist_count") > MAX_ENTRIES);
    }

    static void loadBilibiliPartTitles(String videoId, JSONArray entries, String proxyUrl) {
        if (entries == null || !BILIBILI_ID.matcher(videoId).matches()) return;
        for (int index = 0; index < entries.length(); index++) {
            if (entries.optJSONObject(index).optString("title").isEmpty()) {
                try {
                    fillBilibiliPartTitles(entries, readBilibiliPartMetadata(videoId, proxyUrl));
                } catch (IOException | JSONException ignored) {
                    // Part numbers remain usable when the title endpoint is unavailable.
                }
                return;
            }
        }
    }

    private static JSONObject readBilibiliPartMetadata(String videoId, String proxyUrl)
            throws IOException, JSONException {
        Proxy proxy = Proxy.NO_PROXY;
        if (!proxyUrl.isEmpty()) {
            URI address = URI.create(proxyUrl);
            Proxy.Type type = "socks5".equals(address.getScheme()) ? Proxy.Type.SOCKS : Proxy.Type.HTTP;
            proxy = new Proxy(type, InetSocketAddress.createUnresolved(address.getHost(), address.getPort()));
        }
        URL endpoint = new URL("https://api.bilibili.com/x/player/pagelist?bvid=" + videoId);
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(PART_TITLES_BUDGET_MS - PART_TITLES_TIMEOUT_MS);
        HttpURLConnection connection = (HttpURLConnection) endpoint.openConnection(proxy);
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(PART_TITLES_TIMEOUT_MS);
            connection.setReadTimeout(PART_TITLES_TIMEOUT_MS);
            connection.setRequestProperty("Referer", "https://www.bilibili.com/");
            if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) throw new IOException();
            try (InputStream input = connection.getInputStream();
                 ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192];
                while (!Thread.currentThread().isInterrupted() && System.nanoTime() < deadline) {
                    int size = input.read(buffer);
                    if (size == -1) return new JSONObject(new String(output.toByteArray(), StandardCharsets.UTF_8));
                    if (output.size() + size > MAX_PART_METADATA_BYTES) break;
                    output.write(buffer, 0, size);
                }
                throw new IOException();
            }
        } finally {
            connection.disconnect();
        }
    }

    static void fillBilibiliPartTitles(JSONArray entries, JSONObject metadata) throws JSONException {
        if (metadata.optInt("code", -1) != 0) return;
        JSONArray parts = metadata.optJSONArray("data");
        if (parts == null) return;
        Map<Integer, String> titles = new HashMap<>();
        for (int index = 0; index < parts.length(); index++) {
            JSONObject part = parts.optJSONObject(index);
            if (part == null) continue;
            int page = part.optInt("page");
            Object name = part.opt("part");
            if (page > 0 && name instanceof String && !((String) name).trim().isEmpty()) {
                titles.putIfAbsent(page, ((String) name).trim());
            }
        }
        for (int index = 0; index < entries.length(); index++) {
            JSONObject entry = entries.getJSONObject(index);
            String name = titles.get(entry.optInt("ordinal"));
            if (name != null && entry.optString("title").isEmpty()) entry.put("title", name);
        }
    }

    private static JSONObject bilibiliEntry(String videoId, JSONObject entry) throws JSONException {
        Matcher match = BILIBILI_PART.matcher(entry.optString("url"));
        if (!match.matches() || !videoId.equals(match.group(1))) return null;
        int ordinal = Integer.parseInt(match.group(2));
        return entry(ordinal, title(entry, ""), match.group());
    }

    private static JSONObject youtubeEntry(JSONObject entry, int position) throws JSONException {
        String id = entry.optString("id");
        if (!id.matches("[A-Za-z0-9_-]{11}") || !"Youtube".equals(entry.optString("ie_key"))) return null;
        int ordinal = Math.max(1, entry.optInt("playlist_index", position));
        return entry(ordinal, title(entry, "第 " + ordinal + " 集"), "https://www.youtube.com/watch?v=" + id);
    }

    private static JSONObject entry(int ordinal, String title, String url) throws JSONException {
        return new JSONObject().put("ordinal", ordinal).put("title", title).put("url", url);
    }

    private static String title(JSONObject metadata, String fallback) {
        Object raw = metadata.opt("title");
        String text = raw instanceof String ? ((String) raw).trim() : "";
        return text.isEmpty() ? fallback : text;
    }
}
