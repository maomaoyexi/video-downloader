package io.github.maomaoyexi.videodownloader.prototype;

import io.github.maomaoyexi.videodownloader.prototype.PlatformCookies.Platform;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

public final class DownloadSubtitlesTest {
    public static void main(String[] args) throws Exception {
        youtubeTracksKeepTheirSources();
        bilibiliAiTracksUseWriteSubs();
        rejectsInvalidSelections();
        System.out.println("人工字幕、自动生成、自动翻译及语言选择校验通过。");
    }

    private static void youtubeTracksKeepTheirSources() throws Exception {
        JSONObject metadata = new JSONObject("{"
                + "\"subtitles\":{\"en\":[{\"name\":\"English\"}],\"en-US\":[{\"name\":\"English (US)\"}]},"
                + "\"automatic_captions\":{"
                + "\"en\":[{\"name\":\"English\",\"url\":\"https://www.youtube.com/api/timedtext?lang=en\"}],"
                + "\"en-orig\":[{\"name\":\"English (Original)\"}],"
                + "\"ja\":[{\"name\":\"Japanese\",\"url\":\"https://www.youtube.com/api/timedtext?lang=en&tlang=ja\"}],"
                + "\"fr\":[{\"name\":\"French\",\"url\":\"https://manifest.googlevideo.com/api/manifest/hls_playlist/tts_params/lang%3Den%26tlang%3Dfr/playlist/index.m3u8\"}],"
                + "\"live_chat\":[{}]}}");
        JSONArray tracks = new JSONObject(DownloadSubtitles.catalog(metadata, Platform.YOUTUBE)).getJSONArray("tracks");
        if (tracks.length() != 6) throw new AssertionError(tracks);
        assertTrack(tracks, "en", "manual", "English");
        assertTrack(tracks, "en", "auto", "English（自动生成）");
        assertTrack(tracks, "en-orig", "auto", "English (Original)（自动生成 · 原语）");
        assertTrack(tracks, "ja", "auto", "Japanese（自动翻译）");
        assertTrack(tracks, "fr", "auto", "French（自动翻译）");

        DownloadSubtitles selected = DownloadSubtitles.parse("[{\"language\":\"en\",\"source\":\"manual\"},"
                + "{\"language\":\"en\",\"source\":\"auto\"}]");
        List<DownloadSubtitles.Request> requests = selected.requests(Platform.YOUTUBE);
        if (requests.size() != 2) throw new AssertionError("Mixed sources need separate requests");
        assertRequest(requests.get(0), false, "(?-i:en)", "", 1);
        assertRequest(requests.get(1), true, "(?-i:en)", ".auto", 1);

        DownloadSubtitles literal = DownloadSubtitles.parse("[{\"language\":\"en.1\",\"source\":\"manual\"},"
                + "{\"language\":\"all\",\"source\":\"manual\"}]");
        assertRequest(literal.requests(Platform.YOUTUBE).get(0), false, "(?-i:en\\.1),(?-i:all)", "", 2);
    }

    private static void bilibiliAiTracksUseWriteSubs() throws Exception {
        JSONObject metadata = new JSONObject("{\"subtitles\":{\"zh-CN\":[{\"name\":\"中文\"}],"
                + "\"ai-en\":[{\"name\":\"英语\"}],\"danmaku\":[{}]}}");
        JSONArray tracks = new JSONObject(DownloadSubtitles.catalog(metadata, Platform.BILIBILI)).getJSONArray("tracks");
        if (tracks.length() != 2) throw new AssertionError(tracks);
        assertTrack(tracks, "zh-CN", "manual", "中文");
        assertTrack(tracks, "ai-en", "auto", "英语（AI 字幕）");

        DownloadSubtitles selected = DownloadSubtitles.parse("[{\"language\":\"zh-CN\",\"source\":\"manual\"},"
                + "{\"language\":\"ai-en\",\"source\":\"auto\"}]");
        List<DownloadSubtitles.Request> requests = selected.requests(Platform.BILIBILI);
        if (requests.size() != 2) throw new AssertionError("Bilibili AI subtitles need a distinct filename");
        assertRequest(requests.get(0), false, "(?-i:zh-CN)", "", 1);
        assertRequest(requests.get(1), false, "(?-i:ai-en)", ".auto", 1);

        List<DownloadSubtitles.Request> legacy = DownloadSubtitles.ALL_MANUAL.requests(Platform.BILIBILI);
        if (legacy.size() != 1) throw new AssertionError();
        assertRequest(legacy.get(0), false, "all,-live_chat,-danmaku,-ai-.*", "", 0);
    }

    private static void rejectsInvalidSelections() {
        expectInvalid("[]");
        expectInvalid("[{\"language\":\"en,*\",\"source\":\"manual\"}]");
        expectInvalid("[{\"language\":\"live_chat\",\"source\":\"auto\"}]");
        expectInvalid("[{\"language\":\"en\",\"source\":\"unknown\"}]");
        expectInvalid("[{\"language\":\"ja\",\"source\":\"auto\"},{\"language\":\"ja\",\"source\":\"auto\"}]");
    }

    private static void assertTrack(JSONArray tracks, String language, String source, String label) throws Exception {
        for (int index = 0; index < tracks.length(); index++) {
            JSONObject track = tracks.getJSONObject(index);
            if (language.equals(track.getString("language")) && source.equals(track.getString("source"))) {
                if (!label.equals(track.getString("label"))) throw new AssertionError(track);
                return;
            }
        }
        throw new AssertionError("Missing track " + language + "/" + source);
    }

    private static void assertRequest(DownloadSubtitles.Request request, boolean automatic, String languages,
                                      String suffix, int expectedCount) {
        if (request.automatic != automatic || !languages.equals(request.languages)
                || !suffix.equals(request.suffix) || request.expectedCount != expectedCount) {
            throw new AssertionError(request.languages + "/" + request.automatic + "/" + request.suffix);
        }
    }

    private static void expectInvalid(String json) {
        try {
            DownloadSubtitles.parse(json);
            throw new AssertionError("Invalid subtitle selection was accepted");
        } catch (IllegalArgumentException expected) {
            // Expected.
        }
    }
}
