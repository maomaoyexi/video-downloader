package io.github.maomaoyexi.videodownloader.prototype;

import io.github.maomaoyexi.videodownloader.prototype.PlatformCookies.Platform;

import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class DownloadCollections {
    private static final int MAX_ENTRIES = 100;
    static final int PROBE_LIMIT = MAX_ENTRIES + 1;
    private static final Pattern BILIBILI_PART = Pattern.compile(
            "https://www\\.bilibili\\.com/video/((?i:BV)[A-Za-z0-9]+)\\?p=([1-9][0-9]{0,8})");

    private DownloadCollections() {}

    static String status(String status, String message) {
        try {
            return new JSONObject().put("status", status).put("message", message).toString();
        } catch (JSONException error) {
            throw new IllegalStateException(error);
        }
    }

    static String parse(String output, Platform platform) throws JSONException {
        JSONObject result = new JSONObject(output);
        String type = result.optString("_type", "video");
        if (!"playlist".equals(type)) {
            if (platform == Platform.BILIBILI && "video".equals(type)) return status("single", "");
            return status("error", "未取得可选择的列表，请检查链接后重试。");
        }
        JSONArray source = result.optJSONArray("entries");
        if (source == null) return status("error", "平台未返回可选的视频列表。");
        JSONArray entries = new JSONArray();
        for (int index = 0; index < Math.min(source.length(), MAX_ENTRIES); index++) {
            JSONObject entry = source.optJSONObject(index);
            if (entry == null) continue;
            JSONObject selected = platform == Platform.BILIBILI
                    ? bilibiliEntry(result.optString("id"), entry) : youtubeEntry(entry, index + 1);
            if (selected != null) entries.put(selected);
        }
        if (entries.length() == 0) return status("error", "此列表没有可选的点播视频。");
        String title = title(result, platform == Platform.BILIBILI ? "B 站分 P" : "YouTube 播放列表");
        return new JSONObject().put("status", "ready").put("title", title).put("entries", entries)
                .put("truncated", source.length() > MAX_ENTRIES || result.optInt("playlist_count") > MAX_ENTRIES)
                .toString();
    }

    private static JSONObject bilibiliEntry(String videoId, JSONObject entry) throws JSONException {
        Matcher match = BILIBILI_PART.matcher(entry.optString("url"));
        if (!match.matches() || !videoId.equals(match.group(1))) return null;
        int ordinal = Integer.parseInt(match.group(2));
        return entry(ordinal, title(entry, "第 " + ordinal + " P"), match.group());
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
