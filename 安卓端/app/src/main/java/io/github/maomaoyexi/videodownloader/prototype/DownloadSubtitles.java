package io.github.maomaoyexi.videodownloader.prototype;

import io.github.maomaoyexi.videodownloader.prototype.PlatformCookies.Platform;

import java.net.URI;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class DownloadSubtitles {
    private static final int MAX_SELECTION = 20;
    private static final Pattern LANGUAGE_CODE = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._-]{0,63}");
    private static final Pattern YOUTUBE_TRANSLATION = Pattern.compile(
            "(?:^|&)tlang=([A-Za-z0-9][A-Za-z0-9._-]{0,63})(?:&|$)");
    private static final String MANUAL = "manual";
    private static final String AUTO = "auto";

    static final DownloadSubtitles ALL_MANUAL =
            new DownloadSubtitles(Collections.emptyList(), Collections.emptyList());

    private final List<String> manual;
    private final List<String> automatic;

    private DownloadSubtitles(List<String> manual, List<String> automatic) {
        this.manual = manual;
        this.automatic = automatic;
    }

    static final class Request {
        final boolean automatic;
        final String languages;
        final String suffix;
        final int expectedCount;

        private Request(boolean automatic, String languages, String suffix, int expectedCount) {
            this.automatic = automatic;
            this.languages = languages;
            this.suffix = suffix;
            this.expectedCount = expectedCount;
        }
    }

    static DownloadSubtitles parse(String json) {
        try {
            if (json == null || json.length() > 4096) throw new IllegalArgumentException();
            JSONArray tracks = new JSONArray(json);
            if (tracks.length() == 0 || tracks.length() > MAX_SELECTION) throw new IllegalArgumentException();
            List<String> manual = new ArrayList<>();
            List<String> automatic = new ArrayList<>();
            Set<String> seen = new HashSet<>();
            for (int index = 0; index < tracks.length(); index++) {
                JSONObject track = tracks.getJSONObject(index);
                String language = stringValue(track, "language");
                String source = stringValue(track, "source");
                if (!isLanguage(language) || (!MANUAL.equals(source) && !AUTO.equals(source))) {
                    throw new IllegalArgumentException();
                }
                if (!seen.add(source + ":" + language)) throw new IllegalArgumentException();
                (AUTO.equals(source) ? automatic : manual).add(language);
            }
            return new DownloadSubtitles(manual, automatic);
        } catch (JSONException invalid) {
            throw new IllegalArgumentException(invalid);
        }
    }

    List<Request> requests(Platform platform) {
        if (this == ALL_MANUAL) {
            return Collections.singletonList(new Request(false, "all,-live_chat,-danmaku,-ai-.*", "", 0));
        }
        List<Request> requests = new ArrayList<>();
        addRequest(requests, manual, false, "");
        if (platform == Platform.BILIBILI) {
            // Bilibili's extractor stores AI subtitles alongside uploaded subtitles.
            List<String> ai = new ArrayList<>();
            List<String> captions = new ArrayList<>();
            for (String language : automatic) (isBilibiliAi(language) ? ai : captions).add(language);
            addRequest(requests, ai, false, ".auto");
            addRequest(requests, captions, true, ".auto");
        } else {
            addRequest(requests, automatic, true, ".auto");
        }
        return requests;
    }

    private static void addRequest(List<Request> requests, List<String> languages, boolean automatic, String suffix) {
        if (languages.isEmpty()) return;
        List<String> selectors = new ArrayList<>();
        for (String language : languages) {
            // yt-dlp treats sub-langs as case-insensitive regexes and reserves the bare alias "all".
            selectors.add("(?-i:" + language.replace(".", "\\.") + ")");
        }
        requests.add(new Request(automatic, String.join(",", selectors), suffix, languages.size()));
    }

    static String catalog(JSONObject metadata, Platform platform) throws JSONException {
        JSONArray tracks = new JSONArray();
        Set<String> seen = new HashSet<>();
        appendCatalog(tracks, seen, metadata.optJSONObject("subtitles"), platform, false);
        appendCatalog(tracks, seen, metadata.optJSONObject("automatic_captions"), platform, true);
        return new JSONObject().put("status", "ready").put("tracks", tracks).toString();
    }

    private static void appendCatalog(JSONArray tracks, Set<String> seen, JSONObject subtitles, Platform platform,
                                      boolean automatic) throws JSONException {
        if (subtitles == null) return;
        for (Iterator<String> keys = subtitles.keys(); keys.hasNext(); ) {
            String language = keys.next();
            JSONArray formats = subtitles.optJSONArray(language);
            if (!isLanguage(language) || formats == null || formats.length() == 0) continue;
            boolean biliAi = platform == Platform.BILIBILI && isBilibiliAi(language);
            String source = automatic || biliAi ? AUTO : MANUAL;
            if (!seen.add(source + ":" + language)) continue;
            tracks.put(new JSONObject().put("language", language).put("source", source)
                    .put("label", label(language, formats, platform, automatic, biliAi)));
        }
    }

    private static String label(String language, JSONArray formats, Platform platform, boolean automatic, boolean biliAi) {
        String name = "";
        String translation = "";
        boolean hasUrl = false;
        for (int index = 0; index < formats.length(); index++) {
            JSONObject format = formats.optJSONObject(index);
            if (format == null) continue;
            if (name.isEmpty()) name = stringValue(format, "name").trim();
            String url = stringValue(format, "url");
            if (!url.isEmpty() && automatic && platform == Platform.YOUTUBE) {
                hasUrl = true;
                if (translation.isEmpty()) translation = translatedLanguage(url);
            }
        }
        boolean original = automatic && platform == Platform.YOUTUBE && language.endsWith("-orig");
        if (name.isEmpty()) {
            String displayCode = biliAi ? language.substring(3) : original ? language.substring(0, language.length() - 5)
                    : translation.isEmpty() ? language : translation;
            Locale locale = Locale.forLanguageTag(displayCode);
            name = locale.getLanguage().isEmpty() ? displayCode : locale.getDisplayName(Locale.SIMPLIFIED_CHINESE);
        }
        if (biliAi) return name + "（AI 字幕）";
        if (!automatic || platform != Platform.YOUTUBE) return name;
        if (original) return name + "（自动生成 · 原语）";
        if (!translation.isEmpty()) return name + "（自动翻译）";
        return hasUrl ? name + "（自动生成）" : name;
    }

    private static String translatedLanguage(String url) {
        try {
            URI uri = URI.create(url);
            String translation = findTranslation(uri.getQuery());
            if (!translation.isEmpty()) return translation;

            String path = uri.getPath();
            String prefix = "/tts_params/";
            int start = path == null ? -1 : path.indexOf(prefix);
            if (start == -1) return "";
            start += prefix.length();
            int end = path.indexOf('/', start);
            return findTranslation(end == -1 ? path.substring(start) : path.substring(start, end));
        } catch (IllegalArgumentException ignored) {
            return "";
        }
    }

    private static String findTranslation(String parameters) {
        if (parameters == null) return "";
        Matcher language = YOUTUBE_TRANSLATION.matcher(parameters);
        return language.find() ? language.group(1) : "";
    }

    private static boolean isBilibiliAi(String language) {
        return language.regionMatches(true, 0, "ai-", 0, 3);
    }

    private static boolean isLanguage(String language) {
        return LANGUAGE_CODE.matcher(language).matches()
                && !"danmaku".equalsIgnoreCase(language) && !"live_chat".equalsIgnoreCase(language);
    }

    private static String stringValue(JSONObject object, String name) {
        Object value = object.opt(name);
        return value instanceof String ? (String) value : "";
    }
}
