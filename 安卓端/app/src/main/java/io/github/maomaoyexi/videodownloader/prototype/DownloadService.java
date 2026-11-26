package io.github.maomaoyexi.videodownloader.prototype;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.ContentProviderOperation;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.OperationApplicationException;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.IBinder;
import android.os.PowerManager;
import android.os.RemoteException;
import android.provider.MediaStore;

import com.yausername.ffmpeg.FFmpeg;
import com.yausername.youtubedl_android.YoutubeDL;
import com.yausername.youtubedl_android.YoutubeDLRequest;
import io.github.maomaoyexi.videodownloader.prototype.DownloadHistory.Status;
import io.github.maomaoyexi.videodownloader.prototype.MediaTracks.AudioFormat;
import io.github.maomaoyexi.videodownloader.prototype.PlatformCookies.Platform;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.EnumMap;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.CancellationException;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import kotlin.Unit;

public final class DownloadService extends Service {
    private static final String CHANNEL = "video_downloads";
    private static final String CANCEL = "cancel_download";
    private static final String COOKIE_SETTINGS = "cookie_settings";
    private static final String LEGACY_COOKIES_ENABLED = "enabled";
    private static final int NOTIFICATION_ID = 1;
    private static final int MAX_LINKS = 20;
    static final int MAX_RATE_LIMIT_KIB = 102400;
    private static final List<String> VIDEO_CODECS = Arrays.asList("auto", "h264", "av1", "vp9");
    private static final int COLLECTION_TIMEOUT_SECONDS = 40;
    private static final int SUBTITLE_TIMEOUT_SECONDS = 40;
    private static final int HIGHEST_RESOLUTION = -1;
    private static final int FULL_HD_60 = -2;
    private static final List<Integer> RESOLUTION_OPTIONS =
            Arrays.asList(HIGHEST_RESOLUTION, 0, 4320, 2160, 1440, 1080, FULL_HD_60, 720, 480);
    private static final String VIDEO = "video";
    private static final String AUDIO = "audio";
    private static final String VIDEO_AND_AUDIO = "video-and-audio";
    private static final String SILENT_VIDEO_AND_AUDIO = "silent-video-and-audio";
    private static final List<String> OUTPUT_MODES = Arrays.asList(VIDEO, AUDIO, VIDEO_AND_AUDIO, SILENT_VIDEO_AND_AUDIO);
    private static final Object LOCK = new Object();
    private static final List<String> YOUTUBE = Arrays.asList("youtube.com", "www.youtube.com", "m.youtube.com");
    private static final List<String> BILIBILI = Arrays.asList("bilibili.com", "www.bilibili.com", "m.bilibili.com");
    private static final List<String> BILIBILI_SHORT_HOSTS = Arrays.asList("b23.tv", "bili2233.cn");
    private static final String COLLECTION_IDLE = DownloadCollections.status("idle", "");
    private static final ScheduledExecutorService REQUEST_DEADLINE =
            Executors.newSingleThreadScheduledExecutor(task -> new Thread(task, "request-deadline"));
    private static final String SUBTITLE_STEM = "subtitle";
    private static final String STREAM_PREFIX = "stream-";
    private static final Pattern SUBTITLE_FILE = Pattern.compile("subtitle[0-9]+\\.[A-Za-z0-9][A-Za-z0-9._-]{0,63}\\.srt");
    private static State state = new State("等待添加任务", "粘贴链接后，任务进度会显示在这里。", -1, false);
    private static Batch batch;
    private static Job active;
    private static CollectionProbe collectionProbe;
    private static String collectionResult = COLLECTION_IDLE;
    private static boolean changingCookies;
    private static String cookiePickerToken;
    private static final EnumMap<Platform, String> cookieMessages = new EnumMap<>(Platform.class);

    private static final class State {
        final String phase;
        final String detail;
        final float percent;
        final boolean busy;
        final Uri savedVideo;
        final Uri savedAudio;
        Uri savedDirectory;
        final String speed;
        final boolean audioOnly;
        final int etaSeconds;

        State(String phase, String detail, float percent, boolean busy) {
            this(phase, detail, percent, busy, null, null, false, "", -1);
        }

        State(String phase, String detail, float percent, boolean busy, Uri savedVideo, Uri savedAudio, boolean audioOnly) {
            this(phase, detail, percent, busy, savedVideo, savedAudio, audioOnly, "", -1);
        }

        State(String phase, String detail, float percent, boolean busy, Uri savedVideo, Uri savedAudio, boolean audioOnly,
              String speed, int etaSeconds) {
            this.phase = phase;
            this.detail = detail;
            this.percent = percent;
            this.busy = busy;
            this.savedVideo = savedVideo;
            this.savedAudio = savedAudio;
            this.speed = speed;
            this.audioOnly = audioOnly;
            this.etaSeconds = etaSeconds;
        }
    }

    private enum MediaStep {
        VIDEO("视频"), AUDIO("音频"), COMPANION_AUDIO("独立音频"), SUBTITLES("字幕"), COVER("封面");

        final String label;

        MediaStep(String label) {
            this.label = label;
        }
    }

    private static final class Job {
        final String id = UUID.randomUUID().toString();
        final String url;
        final Platform platform;
        final int resolutionOption;
        final String proxyUrl;
        final boolean cookiesEnabled;
        final boolean audioOnly;
        final int rateLimitKiB;
        final String outputMode;
        final AudioFormat audioFormat;
        final boolean cover;
        final Uri destinationTree;
        final String classification;
        List<String> folders;
        final String videoCodec;
        final int fragments;
        Status result;
        volatile boolean canceled;
        boolean skipped;
        boolean finalizing;
        boolean extrasPending;
        final DownloadSubtitles subtitles;
        final List<DownloadHistory.Attachment> attachments = new ArrayList<>();
        Thread attachmentWorker;
        final List<MediaStep> mediaSteps = new ArrayList<>();
        int mediaStepIndex;

        Job(String url, int resolutionOption, String proxyUrl, SharedPreferences settings, DownloadSubtitles subtitles,
            int rateLimitKiB, String outputMode, String videoCodec, int fragments, AudioFormat audioFormat,
            boolean cover, Uri destinationTree, String classification) {
            this.url = url;
            this.platform = platformForUrl(url);
            this.resolutionOption = resolutionOption;
            this.proxyUrl = proxyUrl;
            this.cookiesEnabled = settings.getBoolean(cookieEnabledKey(platform), false);
            this.rateLimitKiB = rateLimitKiB;
            this.outputMode = outputMode;
            this.audioFormat = audioFormat;
            this.cover = cover;
            this.destinationTree = destinationTree;
            this.classification = classification;
            this.videoCodec = videoCodec;
            this.fragments = fragments;
            audioOnly = AUDIO.equals(outputMode);
            this.subtitles = audioOnly ? null : subtitles;
            extrasPending = this.subtitles != null || cover;
            mediaSteps.add(audioOnly ? MediaStep.AUDIO : MediaStep.VIDEO);
            if (VIDEO_AND_AUDIO.equals(outputMode) || SILENT_VIDEO_AND_AUDIO.equals(outputMode)) {
                mediaSteps.add(MediaStep.COMPANION_AUDIO);
            }
            if (this.subtitles != null) mediaSteps.add(MediaStep.SUBTITLES);
            if (cover) mediaSteps.add(MediaStep.COVER);
        }

        void checkCanceled() {
            if (canceled || Thread.currentThread().isInterrupted()) throw new CancellationException();
        }

        String fileFormat() {
            return audioOnly ? audioFormat.extension : "mp4";
        }

        String mimeType() {
            return audioOnly ? audioFormat.mimeType : "video/mp4";
        }
    }

    private static final class Batch {
        final List<Job> jobs = new ArrayList<>();
        int index = 1;
        int completed;
        int failed;
        int skipped;
        boolean stopped;
        boolean workerStarted;
        Uri latestVideo;
        Uri latestAudio;
        Uri latestDirectory;
        String latestCompletedId;

        Batch(List<String> urls, int resolutionOption, String proxyUrl, SharedPreferences settings, DownloadSubtitles subtitles,
              int rateLimitKiB, String outputMode, String videoCodec, int fragments, AudioFormat audioFormat,
              boolean cover, Uri destinationTree, String classification) {
            for (String url : urls) {
                jobs.add(new Job(url, resolutionOption, proxyUrl, settings, subtitles, rateLimitKiB,
                        outputMode, videoCodec, fragments, audioFormat, cover, destinationTree, classification));
            }
        }

        String id() {
            return jobs.get(0).id;
        }
    }

    private static final class CollectionProbe {
        final String id = UUID.randomUUID().toString();
        final String url;
        final Platform platform;
        final String proxyUrl;
        final boolean cookiesEnabled;
        final boolean subtitles;
        final Thread worker;
        ScheduledFuture<?> deadline;
        volatile boolean stopped;

        CollectionProbe(Context context, String url, String proxyUrl, boolean subtitles) {
            this.url = url;
            this.platform = platformForUrl(url);
            this.proxyUrl = proxyUrl;
            this.cookiesEnabled = cookieSettings(context).getBoolean(cookieEnabledKey(platform), false);
            this.subtitles = subtitles;
            worker = new Thread(() -> resolveCollection(context, this), "collection-probe");
        }

        void checkStopped() {
            if (stopped) throw new CancellationException();
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    static boolean validResolution(int resolution) {
        return RESOLUTION_OPTIONS.contains(resolution);
    }

    static boolean validOutputMode(String outputMode) {
        return OUTPUT_MODES.contains(outputMode);
    }

    static boolean validVideoCodec(String codec) {
        return VIDEO_CODECS.contains(codec);
    }

    static boolean validFragments(int fragments) {
        return fragments >= 1 && fragments <= 16;
    }

    static boolean validProxyScheme(String scheme) {
        return "http".equals(scheme) || "socks5".equals(scheme);
    }

    static String enqueue(Context context, String value, int resolutionOption, boolean proxyEnabled,
                          String proxyAddress, String proxyPort, boolean subtitles, int rateLimitKiB,
                          String outputMode, String videoCodec, String proxyScheme, int fragments,
                          String audioFormatId, boolean cover, String selectedSubtitles) {
        if (value == null) return "请输入 YouTube 或哔哩哔哩点播链接。";
        String[] lines = value.split("\\r\\n|[\\r\\n]", -1);
        List<String> urls = new ArrayList<>();
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i].trim();
            if (line.isEmpty()) continue;
            if (urls.size() >= MAX_LINKS) return "一次最多提交 20 条链接。";
            try {
                urls.add(normalizeUrl(line));
            } catch (IllegalArgumentException invalid) {
                return "第 " + (i + 1) + " 行不是有效的 YouTube 或哔哩哔哩点播链接。";
            }
        }
        if (urls.isEmpty()) return "请输入 YouTube 或哔哩哔哩点播链接。";
        DownloadSubtitles subtitleSelection = subtitles ? DownloadSubtitles.ALL_MANUAL : null;
        if (selectedSubtitles != null) {
            if (!subtitles || urls.size() != 1 || AUDIO.equals(outputMode)) return "请为单个视频选择字幕。";
            try {
                subtitleSelection = DownloadSubtitles.parse(selectedSubtitles);
            } catch (IllegalArgumentException invalid) {
                return "请选择有效的字幕轨道。";
            }
        }
        if (!validResolution(resolutionOption)) {
            return "请选择一个有效的画质上限。";
        }
        if (rateLimitKiB < 0 || rateLimitKiB > MAX_RATE_LIMIT_KIB) {
            return "请输入 0–102400 KiB/s 的下载限速。";
        }
        if (!validOutputMode(outputMode)) return "请选择有效的音画输出模式。";
        AudioFormat audioFormat = AudioFormat.fromId(audioFormatId);
        if (audioFormat == null) return "请选择有效的音频格式。";
        if (!validVideoCodec(videoCodec)) return "请选择有效的视频编码。";
        if (!validFragments(fragments)) return "分片并发数需在 1–16 之间。";
        String proxyUrl = "";
        if (proxyEnabled) {
            try {
                proxyUrl = normalizeProxy(proxyScheme, proxyAddress, proxyPort);
            } catch (IllegalArgumentException invalid) {
                return "请输入有效的代理地址和端口（1–65535）。";
            }
        }
        synchronized (LOCK) {
            if (active != null) return "请先完成或取消当前任务。";
            if (collectionProbe != null) return "请等待列表解析结束。";
            if (changingCookies || cookiePickerToken != null) return "请等待 Cookie 操作完成。";
            DownloadDestination.Snapshot destination = DownloadDestination.snapshot(context);
            if (destination.tree != null && !DownloadDestination.hasWriteAccess(context, destination.tree)) {
                return "自选下载目录的授权已失效，请在设置中重新选择目录。";
            }
            collectionResult = COLLECTION_IDLE;
            batch = new Batch(urls, resolutionOption, proxyUrl, cookieSettings(context), subtitleSelection, rateLimitKiB,
                    outputMode, videoCodec, fragments, audioFormat, cover, destination.tree, destination.classification);
            active = batch.jobs.get(0);
            state = new State("正在准备", "正在启动下载引擎。", -1, true);
            try {
                context.startForegroundService(new Intent(context, DownloadService.class).setIdentifier(batch.id()));
            } catch (RuntimeException error) {
                failToStart(context);
                return "无法启动下载服务。";
            }
        }
        return "";
    }

    static String inspectCollection(Context context, String value, boolean proxyEnabled, String proxyAddress,
                                    String proxyPort) {
        return inspectCollection(context, value, proxyEnabled, proxyAddress, proxyPort, "http");
    }

    static String inspectCollection(Context context, String value, boolean proxyEnabled, String proxyAddress,
                                    String proxyPort, String proxyScheme) {
        return inspectMetadata(context, value, proxyEnabled, proxyAddress, proxyPort, proxyScheme, false);
    }

    static String inspectSubtitles(Context context, String value, boolean proxyEnabled, String proxyAddress,
                                   String proxyPort, String proxyScheme) {
        return inspectMetadata(context, value, proxyEnabled, proxyAddress, proxyPort, proxyScheme, true);
    }

    private static String inspectMetadata(Context context, String value, boolean proxyEnabled, String proxyAddress,
                                          String proxyPort, String proxyScheme, boolean subtitles) {
        String url;
        try {
            url = subtitles ? normalizeUrl(value) : normalizeCollectionUrl(value);
        } catch (IllegalArgumentException invalid) {
            return subtitles ? "请输入有效的单个视频链接。" : "请输入有效的 B 站视频或 YouTube 播放列表链接。";
        }
        String proxyUrl;
        try {
            proxyUrl = proxyEnabled ? normalizeProxy(proxyScheme, proxyAddress, proxyPort) : "";
        } catch (IllegalArgumentException invalid) {
            return "请输入有效的代理地址和端口（1–65535）。";
        }
        synchronized (LOCK) {
            if (active != null) return "请先完成或取消当前任务。";
            if (collectionProbe != null) return "请等待列表解析结束。";
            if (changingCookies || cookiePickerToken != null) return "请等待 Cookie 操作完成。";
            CollectionProbe probe = new CollectionProbe(context, url, proxyUrl, subtitles);
            collectionProbe = probe;
            collectionResult = DownloadCollections.status("loading", subtitles ? "正在读取字幕…" : "正在读取视频列表…");
            probe.deadline = REQUEST_DEADLINE.schedule(() -> expireCollection(probe),
                    COLLECTION_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            probe.worker.start();
        }
        return "";
    }

    static String collectionState() {
        synchronized (LOCK) {
            return collectionResult;
        }
    }

    static void cancelCollection() {
        synchronized (LOCK) {
            collectionResult = COLLECTION_IDLE;
            if (collectionProbe != null) stopCollection(collectionProbe);
        }
    }

    private static void expireCollection(CollectionProbe probe) {
        synchronized (LOCK) {
            if (probe != collectionProbe || probe.stopped) return;
            collectionResult = DownloadCollections.status("error", "读取 " + probe.platform.label
                    + (probe.subtitles ? " 字幕" : " 列表") + "超时，请检查网络后重试。");
            stopCollection(probe);
        }
    }

    private static void stopCollection(CollectionProbe probe) {
        probe.stopped = true;
        probe.deadline.cancel(false);
        // The wrapper destroys its child process when its execute thread is interrupted.
        probe.worker.interrupt();
    }

    private static void resolveCollection(Context context, CollectionProbe probe) {
        File work = new File(context.getCacheDir(), "job-" + probe.id);
        String subject = probe.subtitles ? "字幕列表" : "视频列表";
        String next = DownloadCollections.status("error", "无法读取" + subject + "，请重试。");
        try {
            probe.checkStopped();
            if (!work.mkdir()) throw new IOException();
            YoutubeDL engine = YoutubeDL.getInstance();
            engine.init(context);
            YoutubeDLRequest request = probe.subtitles ? singleVideoRequest(probe.url, probe.proxyUrl)
                    : collectionRequest(probe.url, probe.proxyUrl);
            if (probe.subtitles) {
                request.addOption("--socket-timeout", "15");
                request.addOption("--retries", "1");
                request.addOption("--extractor-retries", "1");
                request.addOption("--simulate");
                request.addOption("--write-subs");
                request.addOption("--write-auto-subs");
                request.addOption("--sub-langs", "^$");
                request.addOption("--print", "%(.{subtitles,automatic_captions})j");
            }
            File cookieCopy = null;
            if (probe.cookiesEnabled) {
                File installed = probe.platform.cookieFile(context.getNoBackupFilesDir());
                if (installed.isFile()) cookieCopy = copyCookiesForRequest(request, installed, work);
            }
            probe.checkStopped();
            JSONObject result = new JSONObject(engine.execute(request, probe.id, false).getOut());
            if (probe.subtitles) {
                next = DownloadSubtitles.catalog(result, probe.platform);
                return;
            }
            String fullVideo = bilibiliShareCollectionUrl(probe.url, result);
            if (fullVideo != null) {
                // A short link may select a part in its redirect even when the input had no part parameter.
                YoutubeDLRequest allParts = collectionRequest(fullVideo, probe.proxyUrl);
                if (cookieCopy != null) allParts.addOption("--cookies", cookieCopy.getAbsolutePath());
                probe.checkStopped();
                result = new JSONObject(engine.execute(allParts, probe.id, false).getOut());
            }
            JSONObject parsed = DownloadCollections.parse(result, probe.platform);
            next = parsed.toString();
            if (probe.platform == Platform.BILIBILI && !probe.stopped
                    && probe.deadline.getDelay(TimeUnit.MILLISECONDS) > DownloadCollections.PART_TITLES_BUDGET_MS) {
                DownloadCollections.loadBilibiliPartTitles(result.optString("id"), parsed.optJSONArray("entries"),
                        probe.proxyUrl);
                next = parsed.toString();
            }
        } catch (JSONException malformed) {
            next = DownloadCollections.status("error", "平台返回的" + subject + "无法读取，请重试。");
        } catch (Exception error) {
            if (!probe.stopped) {
                next = DownloadCollections.status("error", CookieDownloadFailure.describe(
                        error.getMessage(), probe.platform, "读取" + subject));
            }
        } finally {
            cleanWorkDirectory(work);
            synchronized (LOCK) {
                probe.deadline.cancel(false);
                if (collectionProbe == probe) {
                    if (!probe.stopped) collectionResult = next;
                    collectionProbe = null;
                }
            }
        }
    }

    private static YoutubeDLRequest collectionRequest(String url, String proxyUrl) {
        YoutubeDLRequest request = new YoutubeDLRequest(url);
        request.addOption("--ignore-config");
        request.addOption("--proxy=" + proxyUrl);
        request.addOption("--no-cache-dir");
        request.addOption("--socket-timeout", "8");
        request.addOption("--retries", "0");
        request.addOption("--extractor-retries", "0");
        request.addOption("--skip-download");
        request.addOption("--flat-playlist");
        request.addOption("--yes-playlist");
        request.addOption("--playlist-end", DownloadCollections.PROBE_LIMIT);
        request.addOption("--dump-single-json");
        return request;
    }

    private static String bilibiliShareCollectionUrl(String input, JSONObject result) {
        if (!BILIBILI_SHORT_HOSTS.contains(Uri.parse(input).getHost())
                || !"video".equals(result.optString("_type", "video"))) return null;
        try {
            Uri video = validatedWebUrl(result.optString("webpage_url"));
            String part = video.getQueryParameter("p");
            if (!BILIBILI.contains(video.getHost().toLowerCase(Locale.ROOT))
                    || part == null || !part.matches("[1-9][0-9]{0,8}")) return null;
            return normalizeCollectionUrl(video.buildUpon().clearQuery().fragment(null).build().toString());
        } catch (IllegalArgumentException invalid) {
            return null;
        }
    }

    private static void failToStart(Context context) {
        Job job = active;
        job.result = job.canceled ? Status.CANCELED : Status.FAILED;
        DownloadHistory.record(context, job.id, "", job.platform.id, job.result, null, null, job.outputMode);
        if (!job.canceled) batch.failed++;
        state = job.canceled ? new State("已取消", "当前任务已停止。", -1, false)
                : new State("启动失败", "请在下载页重新提交任务。", -1, false);
        active = null;
    }

    private static String normalizeProxy(String scheme, String address, String port) {
        String host = address == null ? "" : address.trim();
        String portText = port == null ? "" : port.trim();
        if (!validProxyScheme(scheme) || host.length() > 253
                || !host.matches("(?i)([a-z0-9][a-z0-9.-]*|\\[[0-9a-f:]+\\])")
                || !portText.matches("[0-9]{1,5}")) {
            throw new IllegalArgumentException();
        }
        int value = Integer.parseInt(portText);
        if (value < 1 || value > 65535) throw new IllegalArgumentException();
        try {
            return new URI(scheme, null, host, value, null, null, null).toASCIIString();
        } catch (URISyntaxException invalid) {
            throw new IllegalArgumentException(invalid);
        }
    }

    private static Uri validatedWebUrl(String value) {
        if (value == null || value.length() > 2048 || value.chars().anyMatch(Character::isWhitespace)) {
            throw new IllegalArgumentException();
        }
        Uri url = Uri.parse(value);
        String scheme = url.getScheme();
        String host = url.getHost();
        if (host == null || (!"http".equalsIgnoreCase(scheme) && !"https".equalsIgnoreCase(scheme))
                || url.getUserInfo() != null || url.getPort() != -1) {
            throw new IllegalArgumentException();
        }
        return url;
    }

    private static String normalizeUrl(String value) {
        Uri url = validatedWebUrl(value);
        String host = url.getHost().toLowerCase(Locale.ROOT);
        String path = url.getPath() == null ? "" : url.getPath();
        if (YOUTUBE.contains(host)) {
            if (path.matches("/(live|shorts)/[A-Za-z0-9_-]{11}/?")) {
                return "https://www.youtube.com/watch?v=" + path.split("/")[2];
            }
            String id = url.getQueryParameter("v");
            if ("/watch".equals(path) && id != null && id.matches("[A-Za-z0-9_-]{11}")) {
                return "https://www.youtube.com/watch?v=" + id;
            }
        } else {
            boolean shortLink = (BILIBILI_SHORT_HOSTS.contains(host) || "youtu.be".equals(host))
                    && path.matches("/[A-Za-z0-9_-]+/?");
            boolean biliVideo = BILIBILI.contains(host) && path.matches("(?i)/video/(BV[A-Za-z0-9]+|av[0-9]+)/?");
            if (shortLink || biliVideo) return url.buildUpon().scheme("https").fragment(null).build().toString();
        }
        throw new IllegalArgumentException();
    }

    private static String normalizeCollectionUrl(String value) {
        Uri url = validatedWebUrl(value);
        String host = url.getHost().toLowerCase(Locale.ROOT);
        String path = url.getPath() == null ? "" : url.getPath();
        if (YOUTUBE.contains(host) || "youtu.be".equals(host)) {
            String playlist = url.getQueryParameter("list");
            if (playlist == null || !playlist.matches("[A-Za-z0-9_-]{2,128}")) {
                throw new IllegalArgumentException();
            }
            if (YOUTUBE.contains(host) && path.matches("/playlist/?")) {
                return "https://www.youtube.com/playlist?list=" + playlist;
            }
            String video = null;
            if ("youtu.be".equals(host) && path.matches("/[A-Za-z0-9_-]{11}/?")) {
                video = path.substring(1, 12);
            } else if (YOUTUBE.contains(host) && "/watch".equals(path)) {
                video = url.getQueryParameter("v");
            }
            if (video != null && video.matches("[A-Za-z0-9_-]{11}")) {
                return "https://www.youtube.com/watch?v=" + video + "&list=" + playlist;
            }
        } else if (url.getQueryParameter("p") == null) {
            if (BILIBILI.contains(host) && path.matches("(?i)/video/(BV[A-Za-z0-9]+|av[0-9]+)/?")) {
                return "https://www.bilibili.com" + path;
            }
            if (BILIBILI_SHORT_HOSTS.contains(host) && path.matches("/[A-Za-z0-9_-]+/?")) {
                return "https://" + host + path;
            }
        }
        throw new IllegalArgumentException();
    }

    static String snapshot() {
        synchronized (LOCK) {
            JSONObject object = new JSONObject();
            try {
                object.put("phase", state.phase).put("detail", state.detail)
                        .put("percent", state.percent).put("busy", state.busy)
                        .put("speed", state.speed)
                        .put("etaSeconds", state.etaSeconds)
                        .put("canPlay", state.savedVideo != null)
                        .put("hasAudioFile", state.savedAudio != null)
                        .put("outputMode", batch == null ? VIDEO : batch.jobs.get(0).outputMode)
                        .put("audioOnly", state.audioOnly)
                        .put("batchTotal", batch == null ? 0 : batch.jobs.size())
                        .put("batchIndex", batch == null ? 0 : batch.index)
                        .put("batchCompleted", batch == null ? 0 : batch.completed)
                        .put("batchFailed", batch == null ? 0 : batch.failed)
                        .put("batchSkipped", batch == null ? 0 : batch.skipped)
                        .put("canSkip", canSkipCurrent())
                        .put("batchStopped", batch != null && batch.stopped)
                        .put("batchItems", batchItems());
                if (state.busy && active != null) {
                    int step = active.mediaStepIndex;
                    object.put("mediaStep", step + 1)
                            .put("mediaStepTotal", active.mediaSteps.size())
                            .put("mediaStepLabel", active.mediaSteps.get(step).label);
                }
            } catch (JSONException error) {
                throw new IllegalStateException(error);
            }
            return object.toString();
        }
    }

    // Caller holds LOCK so the link details and batch counters reflect the same transition.
    private static JSONArray batchItems() throws JSONException {
        JSONArray items = new JSONArray();
        if (batch != null) {
            for (Job job : batch.jobs) {
                String status;
                if (job.result != null) status = job.skipped ? "skipped" : job.result.id;
                else if (job == active) status = "downloading";
                else status = active == null ? "canceled" : "waiting";
                items.put(new JSONObject().put("url", job.url).put("status", status).put("outputMode", job.outputMode));
            }
        }
        return items;
    }

    static String cookieState(Context context, Platform platform) {
        synchronized (LOCK) {
            try {
                return new JSONObject().put("configured",
                                platform != null && platform.cookieFile(context.getNoBackupFilesDir()).isFile())
                        .put("enabled", platform != null && cookieSettings(context)
                                .getBoolean(cookieEnabledKey(platform), false))
                        .put("busy", active != null || cookiePickerToken != null || changingCookies || collectionProbe != null)
                        .put("message", platform == null ? "不支持此平台的 Cookie。" :
                                cookieMessages.getOrDefault(platform, "")).toString();
            } catch (JSONException error) {
                throw new IllegalStateException(error);
            }
        }
    }

    private static String cookieEnabledKey(Platform platform) {
        return platform.id + "_enabled";
    }

    // Call under LOCK before reading a toggle or changing any imported file.
    private static SharedPreferences cookieSettings(Context context) {
        SharedPreferences settings = context.getSharedPreferences(COOKIE_SETTINGS, Context.MODE_PRIVATE);
        SharedPreferences.Editor migration = null;
        boolean hadGlobalSwitch = settings.contains(LEGACY_COOKIES_ENABLED);
        for (Platform platform : Platform.values()) {
            String key = cookieEnabledKey(platform);
            if (settings.contains(key)) continue;
            if (migration == null) migration = settings.edit();
            boolean enabled = hadGlobalSwitch ? settings.getBoolean(LEGACY_COOKIES_ENABLED, false)
                    : platform.cookieFile(context.getNoBackupFilesDir()).isFile();
            migration.putBoolean(key, enabled);
        }
        if (migration != null) migration.apply();
        return settings;
    }

    static String setPlatformCookiesEnabled(Context context, Platform platform, boolean enabled) {
        synchronized (LOCK) {
            if (platform == null) return "不支持此平台的 Cookie。";
            if (active != null) return "请先完成或取消当前任务。";
            if (collectionProbe != null) return "请等待列表解析结束。";
            if (changingCookies || cookiePickerToken != null) return "请等待 Cookie 操作完成。";
            SharedPreferences settings = cookieSettings(context);
            String key = cookieEnabledKey(platform);
            boolean previous = settings.getBoolean(key, false);
            if (previous == enabled) return "";
            if (settings.edit().putBoolean(key, enabled).commit()) {
                cookieMessages.remove(platform);
                return "";
            }
            // SharedPreferences also changes its in-memory value on a failed disk write.
            settings.edit().putBoolean(key, previous).apply();
            return "无法保存 Cookie 开关设置，请重试。";
        }
    }

    static boolean beginCookiePicker(Platform platform, String token) {
        synchronized (LOCK) {
            if (!canChangeCookies(platform)) return false;
            cookiePickerToken = token;
            return true;
        }
    }

    static void closeCookiePicker(Platform platform, String token, String message) {
        synchronized (LOCK) {
            if (!token.equals(cookiePickerToken)) return;
            cookiePickerToken = null;
            cookieMessages.put(platform, message);
        }
    }

    static void cleanStaleCookieFiles(Context context) {
        synchronized (LOCK) {
            if (active == null && collectionProbe == null && !changingCookies) {
                for (Platform platform : Platform.values()) {
                    PlatformCookies.cleanStaleCopies(platform.cookieFile(context.getNoBackupFilesDir()),
                            context.getCacheDir());
                }
            }
        }
    }

    private static boolean canChangeCookies(Platform platform) {
        if (active != null) {
            cookieMessages.put(platform, "请先完成或取消当前任务。");
            return false;
        }
        if (collectionProbe != null) {
            cookieMessages.put(platform, "请等待列表解析结束。");
            return false;
        }
        if (changingCookies || cookiePickerToken != null) return false;
        cookieMessages.put(platform, "");
        return true;
    }

    // A null document removes the previously imported file.
    static void changeCookies(Context context, Platform platform, Uri document, String token) {
        synchronized (LOCK) {
            if (token != null) {
                if (!token.equals(cookiePickerToken)) return;
                cookiePickerToken = null;
            }
            if (!canChangeCookies(platform)) return;
            // Freeze migrated switches before an import or removal can change their defaults.
            cookieSettings(context);
            changingCookies = true;
        }
        new Thread(() -> {
            String platformCookie = platform.label + " Cookie";
            String message = document == null ? "无法移除 " + platformCookie + "，请重试。"
                    : "无法读取或保存 " + platformCookie + " 文件，请重试。";
            try {
                File installed = platform.cookieFile(context.getNoBackupFilesDir());
                if (document == null) {
                    PlatformCookies.cleanStaleCopies(installed, context.getCacheDir());
                    message = PlatformCookies.remove(installed) ? "已移除 " + platformCookie + "。" : "";
                } else {
                    String records;
                    try (InputStream input = context.getContentResolver().openInputStream(document)) {
                        records = PlatformCookies.readRecords(input, platform);
                    }
                    PlatformCookies.install(records, installed);
                    message = "已导入 " + platformCookie + "。";
                }
            } catch (PlatformCookies.InvalidFile invalid) {
                message = invalid.getMessage();
            } catch (IOException | RuntimeException error) {
                // Provider and engine messages may contain credentials.
            } finally {
                synchronized (LOCK) {
                    cookieMessages.put(platform, message);
                    changingCookies = false;
                }
            }
        }, "platform-cookies").start();
    }

    private static Platform platformForUrl(String url) {
        String host = Uri.parse(url).getHost().toLowerCase(Locale.ROOT);
        if (YOUTUBE.contains(host) || "youtu.be".equals(host)) return Platform.YOUTUBE;
        if (BILIBILI.contains(host) || BILIBILI_SHORT_HOSTS.contains(host)) return Platform.BILIBILI;
        return null;
    }

    static Uri completedVideo() {
        synchronized (LOCK) {
            return state.savedVideo;
        }
    }

    static Uri completedAudio() {
        synchronized (LOCK) {
            return state.savedAudio;
        }
    }

    static Uri completedDirectory() {
        synchronized (LOCK) {
            return state.savedDirectory;
        }
    }

    static void refreshDeletedMedia(Context context, String id) {
        synchronized (LOCK) {
            if (batch == null || !id.equals(batch.latestCompletedId)) return;
        }
        Uri video = DownloadHistory.completedVideo(context, id);
        Uri audio = DownloadHistory.completedAudio(context, id);
        synchronized (LOCK) {
            if (batch == null || !id.equals(batch.latestCompletedId)) return;
            batch.latestVideo = video;
            batch.latestAudio = audio;
            if (active == null) {
                Uri directory = state.savedDirectory;
                state = new State(state.phase, state.detail, state.percent, false, video, audio, state.audioOnly);
                state.savedDirectory = directory;
            }
        }
    }

    static void cancel() {
        cancel(null);
    }

    // The caller holds LOCK while reading the current batch and job.
    private static boolean canSkipCurrent() {
        return active != null && batch.workerStarted && !batch.stopped && batch.index < batch.jobs.size()
                && !active.canceled && !active.finalizing;
    }

    static void skipCurrent() {
        Job job;
        synchronized (LOCK) {
            if (!canSkipCurrent()) return;
            job = active;
            job.skipped = true;
            job.canceled = true;
            state = new State("正在跳过", "正在结束当前条目。", -1, true);
        }
        stopJobProcess(job);
    }

    private static void cancel(String batchId) {
        Job job;
        synchronized (LOCK) {
            job = active;
            if (job == null || batch.stopped || (batchId != null && !batchId.equals(batch.id()))) return;
            if (job.finalizing && batch.index == batch.jobs.size() && !job.extrasPending) return;
            batch.stopped = true;
            state = new State("正在取消", "正在结束当前任务。", -1, true);
            if (job.finalizing) {
                if (job.attachmentWorker != null) job.attachmentWorker.interrupt();
                return;
            }
            if (job.canceled) return;
            job.canceled = true;
        }
        stopJobProcess(job);
    }

    private static void stopJobProcess(Job job) {
        // Cancellation may arrive just before the engine registers its process ID.
        new Thread(() -> {
            while (true) {
                synchronized (LOCK) {
                    if (active != job) return;
                }
                if (YoutubeDL.getInstance().destroyProcessById(job.id)) return;
                try {
                    Thread.sleep(120);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        }, "cancel-download").start();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && CANCEL.equals(intent.getAction())) {
            synchronized (LOCK) {
                if (active == null) stopSelf(startId);
            }
            if (intent.getIdentifier() != null) cancel(intent.getIdentifier());
            return START_NOT_STICKY;
        }
        Batch running;
        Job firstJob;
        synchronized (LOCK) {
            if (active == null) {
                stopSelf(startId);
                return START_NOT_STICKY;
            }
            running = batch;
            if (intent == null || !running.id().equals(intent.getIdentifier()) || running.workerStarted) {
                return START_NOT_STICKY;
            }
            running.workerStarted = true;
            firstJob = active;
            try {
                NotificationManager notifications = getSystemService(NotificationManager.class);
                notifications.createNotificationChannel(new NotificationChannel(
                        CHANNEL, "视频下载", NotificationManager.IMPORTANCE_LOW));
                startForeground(NOTIFICATION_ID, notification(running));
            } catch (RuntimeException error) {
                failToStart(this);
                stopSelf(startId);
                return START_NOT_STICKY;
            }
        }
        new Thread(() -> {
            PowerManager.WakeLock wakeLock = getSystemService(PowerManager.class)
                    .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "VideoDownloader:Download");
            try {
                for (Job job = firstJob; job != null; ) {
                    job = download(running, job, wakeLock);
                }
            } finally {
                if (wakeLock.isHeld()) wakeLock.release();
            }
        }, "video-download").start();
        return START_NOT_STICKY;
    }

    private Notification notification(Batch running) {
        int flags = PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT;
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), flags);
        PendingIntent stop = PendingIntent.getService(this, 1,
                new Intent(this, DownloadService.class).setAction(CANCEL).setIdentifier(running.id()), flags);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_sys_download)
                .setContentTitle("多平台下载")
                .setContentText(running.jobs.get(0).audioOnly ? "正在处理音频下载任务" : "正在处理视频下载任务")
                .setContentIntent(open)
                .addAction(new Notification.Action.Builder(null, "取消", stop).build())
                .setOngoing(true)
                .build();
    }

    private Job download(Batch running, Job job, PowerManager.WakeLock wakeLock) {
        File work = new File(getCacheDir(), "job-" + job.id);
        String extension = "." + job.fileFormat();
        String formatLabel = job.fileFormat().toUpperCase(Locale.ROOT);
        String audioLabel = job.audioFormat.extension.toUpperCase(Locale.ROOT);
        String audioExtension = "." + job.audioFormat.extension;
        State terminal;
        Status result;
        String title = "";
        String authorFolder = DownloadDestination.authorFolder(null);
        String mainName = null;
        String companionName = null;
        File cookieCopy = null;
        String localFailure = "无法准备下载临时目录，请检查手机剩余空间。";
        try {
            job.checkCanceled();
            if (!wakeLock.isHeld()) wakeLock.acquire();
            if (!work.mkdir()) throw new IOException("无法创建临时下载目录。");
            localFailure = "无法初始化下载引擎，请退出并重新打开应用后重试。";
            YoutubeDL engine = YoutubeDL.getInstance();
            engine.init(this);
            FFmpeg.getInstance().init(this);

            YoutubeDLRequest request = singleVideoRequest(job);
            if (job.cookiesEnabled) {
                File installed = job.platform.cookieFile(getNoBackupFilesDir());
                if (installed.isFile()) {
                    localFailure = "无法准备 " + job.platform.label + " Cookie 副本，请检查手机剩余空间后重试。";
                    cookieCopy = copyCookiesForRequest(request, installed, work);
                }
            }
            addTransferProgress(request);
            request.addOption("--socket-timeout", "20");
            request.addOption("--retries", "2");
            if (job.rateLimitKiB > 0) request.addOption("--limit-rate", job.rateLimitKiB + "K");
            if (job.fragments > 1) request.addOption("--concurrent-fragments", job.fragments);
            update(job, new State("正在解析", "正在获取可用的点播格式。", -1, true));
            job.checkCanceled();
            localFailure = null;
            boolean silent = SILENT_VIDEO_AND_AUDIO.equals(job.outputMode);
            boolean separate = selectOutputFormat(engine, request, job, cookieCopy);
            String nameTemplate = "%(title).100B [%(id)s]";
            String template = (silent || job.audioOnly ? STREAM_PREFIX : "") + nameTemplate
                    + (silent ? ".%(format_id)s" : "") + ".%(ext)s";
            request.addOption("-o", new File(work, template).getAbsolutePath());
            File authorMetadata = new File(work, "author.jsonl");
            request.addCommands(Arrays.asList("--print-to-file", "after_move:%(.{channel,uploader,creator})j",
                    authorMetadata.getAbsolutePath().replace("%", "%%")));
            engine.execute(request, job.id, false, (progress, eta, line) -> {
                if (line.startsWith("[Merger]") || line.startsWith("[VideoRemuxer]")) {
                    update(job, new State("正在处理视频", "正在封装为 " + formatLabel + "。", -1, true));
                } else if (line.startsWith("[download]")) {
                    TransferProgress transfer = TransferProgress.parse(line);
                    if (transfer != null) update(job, new State("正在下载", "当前音频或视频流进度",
                            transfer.percent, true, null, null, false, transfer.speed, transfer.etaSeconds));
                }
                return Unit.INSTANCE;
            });
            job.checkCanceled();
            String author = readAuthor(authorMetadata, job.platform);
            authorFolder = DownloadDestination.authorFolder(author);
            job.folders = DownloadDestination.folders(job.classification, job.platform.label, job.outputMode, author);
            File mainFile;
            File audioFile = null;
            localFailure = "下载结束后未取得可保存的 " + formatLabel + " 文件。";
            File[] files = work.listFiles(file -> nonEmptyFile(file) && (silent || job.audioOnly
                    ? file.getName().startsWith(STREAM_PREFIX) : file.getName().toLowerCase(Locale.ROOT).endsWith(extension)));
            if (files == null || files.length != (separate ? 2 : 1)) throw new IOException();
            localFailure = "无法读取媒体轨道，请尝试其他画质或编码。";
            update(job, new State("正在检查轨道", "正在核对下载文件的画面和声音。", -1, true));
            mainFile = files[0];
            if (silent) {
                update(job, new State("正在分离轨道", "正在生成无声 MP4 和独立 " + audioLabel + "。", -1, true));
                File videoSource = findTrack(files, true, job);
                File audioSource = findTrack(files, false, job);
                String name = videoSource.getName();
                int stemEnd = name.lastIndexOf("].") + 1;
                if (stemEnd <= STREAM_PREFIX.length()) throw new IOException();
                String stem = name.substring(STREAM_PREFIX.length(), stemEnd);
                mainFile = new File(work, stem + ".mp4");
                audioFile = new File(work, stem + audioExtension);
                localFailure = "无法生成无声 MP4 或独立 " + audioLabel + "，请尝试其他画质或编码。";
                MediaTracks.silentVideo(this, videoSource, mainFile, job::checkCanceled);
                update(job, new State("正在处理音频", "正在生成独立 " + audioLabel + " 文件。", -1, true),
                        MediaStep.COMPANION_AUDIO);
                MediaTracks.audio(this, audioSource, audioFile, job.audioFormat, job::checkCanceled);
            } else {
                MediaTracks.Tracks tracks = MediaTracks.inspect(this, mainFile, job::checkCanceled);
                if (!job.audioOnly && !tracks.hasVideo) throw new MissingTracks("源素材缺少视频轨，无法输出视频。");
                if (!tracks.hasAudio) throw new MissingTracks("源素材缺少音频轨，无法输出声音。");
                if (job.audioOnly) {
                    update(job, new State("正在处理音频", "正在准备 " + audioLabel + " 文件。", -1, true));
                    String sourceName = mainFile.getName();
                    String stem = sourceName.substring(STREAM_PREFIX.length(), sourceName.lastIndexOf('.'));
                    mainFile = new File(work, stem + audioExtension);
                    localFailure = "无法生成 " + audioLabel + " 音频。";
                    MediaTracks.audio(this, files[0], mainFile, job.audioFormat, job::checkCanceled);
                } else if (VIDEO_AND_AUDIO.equals(job.outputMode)) {
                    update(job, new State("正在提取音频", "正在从已下载的 MP4 生成独立 " + audioLabel + "。", -1, true),
                            MediaStep.COMPANION_AUDIO);
                    String stem = mainFile.getName().substring(0, mainFile.getName().length() - extension.length());
                    audioFile = new File(work, stem + audioExtension);
                    localFailure = "无法从已下载的视频提取 " + audioLabel + "。";
                    MediaTracks.audio(this, mainFile, audioFile, job.audioFormat, job::checkCanceled);
                }
            }
            update(job, new State("正在保存", "正在写入手机的下载目录。", -1, true));
            localFailure = job.destinationTree == null ? "文件已下载，写入手机的下载目录失败，请检查剩余空间后重试。"
                    : "无法写入自选下载目录，请在设置中重新授权或检查剩余空间。";
            Uri[] saved = saveMedia(job, mainFile, audioFile);
            Uri savedVideo = saved[0];
            Uri savedAudio = saved[1];
            mainName = readDisplayName(savedVideo);
            Uri savedDirectory = saved[2];
            String destination = job.destinationTree == null ? "下载 / 多平台下载" : "自选目录";
            if (!job.folders.isEmpty()) destination += " / " + String.join(" / ", job.folders);
            String detail = "已保存到「" + destination + "」";
            title = mainName == null || mainName.isEmpty() ? mainFile.getName() : mainName;
            detail += "：" + title;
            if (savedAudio != null) {
                companionName = readDisplayName(savedAudio);
                detail += " 和 " + (companionName == null ? audioFile.getName() : companionName);
            }
            if (title.toLowerCase(Locale.ROOT).endsWith(extension)) title = title.substring(0, title.length() - extension.length());
            if (job.subtitles != null) detail += "。" + finishSubtitles(running, job, engine, work, cookieCopy, title);
            if (job.cover) detail += "。" + finishCover(running, job, engine, work, cookieCopy,
                    mainName == null || mainName.isEmpty() ? mainFile.getName() : mainName);
            synchronized (LOCK) {
                job.extrasPending = false;
            }
            terminal = new State("下载完成", detail, 100, false, savedVideo, savedAudio, job.audioOnly);
            terminal.savedDirectory = savedDirectory;
            result = Status.COMPLETED;
        } catch (Exception error) {
            boolean canceled;
            synchronized (LOCK) {
                job.finalizing = true;
                canceled = job.canceled || error instanceof CancellationException || error instanceof InterruptedException;
            }
            terminal = canceled
                    ? new State("已取消", job.skipped ? "当前条目已跳过。" : "当前任务已停止。", -1, false)
                    : new State("下载失败", error instanceof MissingTracks ? error.getMessage() : localFailure != null ? localFailure
                            : describeEngineFailure(error, job, cookieCopy != null), -1, false);
            result = canceled ? Status.CANCELED : Status.FAILED;
        } finally {
            cleanWorkDirectory(work);
        }

        DownloadHistory.record(this, job.id, title, job.platform.id, result, terminal.savedVideo, terminal.savedAudio,
                job.outputMode, terminal.savedDirectory, authorFolder, mainName, companionName, job.attachments);
        synchronized (LOCK) {
            job.result = result;
            if (result == Status.COMPLETED) {
                running.completed++;
                running.latestVideo = terminal.savedVideo;
                running.latestAudio = terminal.savedAudio;
                running.latestDirectory = terminal.savedDirectory;
                running.latestCompletedId = job.id;
            } else if (result == Status.FAILED) {
                running.failed++;
            } else if (job.skipped) {
                running.skipped++;
            }

            if (!running.stopped && running.index < running.jobs.size()) {
                active = running.jobs.get(running.index);
                running.index++;
                state = new State("正在准备", "正在启动下载引擎。", -1, true);
                return active;
            }

            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
            boolean playableAudio = running.latestVideo != null && job.audioOnly;
            state = running.stopped && result != Status.CANCELED && running.index < running.jobs.size()
                    ? new State("已取消", "未开始的链接已取消。", -1, false, running.latestVideo, running.latestAudio, playableAudio)
                    : new State(terminal.phase, terminal.detail, terminal.percent, false, running.latestVideo, running.latestAudio, playableAudio);
            state.savedDirectory = running.latestDirectory;
            active = null;
            return null;
        }
    }

    private static String readAuthor(File metadata, Platform platform) {
        if (metadata == null || !nonEmptyFile(metadata) || metadata.length() > 64 * 1024) return null;
        String[] fields = platform == Platform.BILIBILI
                ? new String[] {"uploader", "channel", "creator"} : new String[] {"channel", "uploader", "creator"};
        try {
            for (String line : Files.readAllLines(metadata.toPath())) {
                JSONObject values;
                try {
                    values = new JSONObject(line);
                } catch (JSONException malformed) {
                    continue;
                }
                for (String field : fields) {
                    Object value = values.opt(field);
                    if (value instanceof String) {
                        String name = ((String) value).trim();
                        if (!name.isEmpty() && !"NA".equals(name)) return name;
                    }
                }
            }
        } catch (IOException ignored) {
            // Metadata is optional and must not discard a completed download.
        }
        return null;
    }

    private static final class MissingTracks extends IOException {
        MissingTracks(String message) {
            super(message);
        }
    }

    private File findTrack(File[] files, boolean video, Job job) throws IOException, InterruptedException {
        for (File file : files) {
            MediaTracks.Tracks tracks = MediaTracks.inspect(this, file, job::checkCanceled);
            if (video ? tracks.hasVideo : tracks.hasAudio) return file;
        }
        throw new MissingTracks(video ? "源素材缺少视频轨，无法输出无声视频。" : "源素材缺少音频轨，无法输出独立音频。");
    }

    private static YoutubeDLRequest singleVideoRequest(Job job) {
        return singleVideoRequest(job.url, job.proxyUrl);
    }

    private static YoutubeDLRequest singleVideoRequest(String url, String proxyUrl) {
        YoutubeDLRequest request = new YoutubeDLRequest(url);
        request.addOption("--ignore-config");
        // The Android wrapper drops empty option values passed separately.
        request.addOption("--proxy=" + proxyUrl);
        request.addOption("--no-cache-dir");
        request.addOption("--no-playlist");
        request.addOption("--no-live-from-start");
        request.addOption("--match-filter", "live_status!=?is_live & live_status!=?is_upcoming & live_status!=?post_live");
        return request;
    }

    private boolean selectOutputFormat(YoutubeDL engine, YoutubeDLRequest request, Job job, File cookieCopy) throws Exception {
        if (job.audioOnly) {
            request.addOption("-f", "ba[ext=m4a]/ba/b/bv*");
            return false;
        }
        boolean fullHd60 = job.resolutionOption == FULL_HD_60;
        int height = fullHd60 ? 1080 : job.resolutionOption;
        addVideoSort(request, job, height, fullHd60);
        String limit = height > 0 ? "[height<=" + height + "]" : "";
        if (fullHd60) limit += "[fps<=?60]";
        if (!SILENT_VIDEO_AND_AUDIO.equals(job.outputMode)) {
            request.addOption("--merge-output-format", "mp4");
            request.addOption("--remux-video", "mp4");
            if (height > 0) request.addOption("-f", "bv*" + limit + "+ba/b" + limit + "/bv" + limit);
            return false;
        }

        // Choose whether to download two independent streams or a single combined stream before transferring media.
        String video = "bv" + limit;
        String combined = "b" + limit;
        String audio = "ba[ext=m4a]/ba";
        YoutubeDLRequest probe = singleVideoRequest(job);
        if (cookieCopy != null) probe.addOption("--cookies", cookieCopy.getAbsolutePath());
        probe.addOption("--socket-timeout", "20");
        probe.addOption("--retries", "2");
        addVideoSort(probe, job, height, fullHd60);
        probe.addOption("-f", video + "+(" + audio + ")/" + combined + "/" + video + "/(" + audio + ")");
        probe.addOption("--skip-download");
        probe.addOption("--dump-single-json");
        JSONObject formats = new JSONObject(engine.execute(probe, job.id, false).getOut());
        job.checkCanceled();
        JSONArray streams = formats.optJSONArray("requested_formats");
        if (streams != null && streams.length() == 2) {
            request.addOption("-f", video + ",(" + audio + ")");
            return true;
        }
        if ("none".equals(formats.optString("vcodec"))) throw new MissingTracks("源素材缺少符合当前画质的视频轨。");
        if ("none".equals(formats.optString("acodec"))) throw new MissingTracks("源素材缺少音频轨，无法输出独立音频。");
        request.addOption("-f", combined);
        return false;
    }

    private static void addVideoSort(YoutubeDLRequest request, Job job, int height, boolean fullHd60) {
        String preferredCodec = "auto".equals(job.videoCodec) ? "h264" : job.videoCodec;
        String formatSort = "vcodec:" + preferredCodec + ",acodec:aac";
        if (height == HIGHEST_RESOLUTION || height > 1080 || fullHd60) {
            request.addOption("--format-sort-force");
            formatSort = (fullHd60 ? "res,fps," : "res,") + formatSort;
        }
        request.addOption("-S", formatSort);
    }

    private String finishSubtitles(Batch running, Job job, YoutubeDL engine, File work, File cookieCopy, String savedStem) {
        Thread worker = Thread.currentThread();
        ScheduledFuture<?> deadline = null;
        int savedCount = 0;
        try {
            synchronized (LOCK) {
                if (running.stopped) return "已停止下载字幕。";
                job.attachmentWorker = worker;
                job.mediaStepIndex = job.mediaSteps.indexOf(MediaStep.SUBTITLES);
                state = new State("正在下载字幕", "视频已保存，正在获取字幕。", -1, true);
            }
            deadline = REQUEST_DEADLINE.schedule(() -> {
                synchronized (LOCK) {
                    if (job.attachmentWorker == worker) worker.interrupt();
                }
            }, SUBTITLE_TIMEOUT_SECONDS, TimeUnit.SECONDS);

            boolean incomplete = false;
            int requestIndex = 0;
            for (DownloadSubtitles.Request selection : job.subtitles.requests(job.platform)) {
                String stem = SUBTITLE_STEM + ++requestIndex;
                YoutubeDLRequest request = singleVideoRequest(job);
                if (cookieCopy != null) request.addOption("--cookies", cookieCopy.getAbsolutePath());
                request.addOption("--socket-timeout", "8");
                request.addOption("--retries", "0");
                request.addOption("--extractor-retries", "0");
                request.addOption("--skip-download");
                addTransferProgress(request);
                request.addOption(selection.automatic ? "--write-auto-subs" : "--write-subs");
                request.addOption("--sub-langs", selection.languages);
                request.addOption("--sub-format", "srt/vtt/ass/best");
                request.addOption("--convert-subs", "srt");
                request.addOption("-o", new File(work, stem).getAbsolutePath().replace("%", "%%") + ".%(ext)s");
                job.checkCanceled();
                try {
                    engine.execute(request, job.id, false, (progress, eta, line) -> {
                        if (line.startsWith("[download]")) {
                            TransferProgress transfer = TransferProgress.parse(line);
                            if (transfer != null) update(job, new State("正在下载字幕", "当前字幕文件进度",
                                    transfer.percent, true, null, null, false, transfer.speed, transfer.etaSeconds));
                        }
                        return Unit.INSTANCE;
                    });
                } catch (Exception error) {
                    incomplete = true;
                }
                job.checkCanceled();

                File[] subtitles = work.listFiles(file -> file.getName().startsWith(stem + ".")
                        && SUBTITLE_FILE.matcher(file.getName()).matches() && nonEmptyFile(file));
                if (subtitles == null) throw new IOException();
                incomplete |= subtitles.length < selection.expectedCount;
                for (File subtitle : subtitles) {
                    String name = savedStem + selection.suffix + subtitle.getName().substring(stem.length());
                    try {
                        saveExtra(job, subtitle, name, DownloadHistory.SUBTITLE_MIME);
                        savedCount++;
                    } catch (IOException | RuntimeException error) {
                        job.checkCanceled();
                        incomplete = true;
                    }
                }
            }
            if (savedCount == 0) {
                if (job.subtitles != DownloadSubtitles.ALL_MANUAL || incomplete) return "所选字幕未能下载或保存。";
                return "未找到可下载的人工字幕。";
            }
            return !incomplete ? "已保存 " + savedCount + " 个 SRT 字幕。"
                    : "已保存 " + savedCount + " 个 SRT 字幕，部分字幕未能保存。";
        } catch (Exception error) {
            synchronized (LOCK) {
                if (running.stopped) return "已停止下载字幕。";
            }
            return savedCount == 0 ? "字幕未能下载或保存。" : "已保存 " + savedCount + " 个 SRT 字幕，部分字幕未能保存。";
        } finally {
            synchronized (LOCK) {
                job.attachmentWorker = null;
                if (deadline != null) deadline.cancel(false);
            }
            // Both the deadline and the user's stop action interrupt this worker.
            Thread.interrupted();
        }
    }

    private String finishCover(Batch running, Job job, YoutubeDL engine, File work, File cookieCopy, String savedName) {
        Thread worker = Thread.currentThread();
        ScheduledFuture<?> deadline = null;
        try {
            synchronized (LOCK) {
                if (running.stopped) return "已停止下载封面。";
                job.attachmentWorker = worker;
                job.mediaStepIndex = job.mediaSteps.indexOf(MediaStep.COVER);
                state = new State("正在下载封面", "媒体已保存，正在获取视频封面。", -1, true);
            }
            deadline = REQUEST_DEADLINE.schedule(() -> {
                synchronized (LOCK) {
                    if (job.attachmentWorker == worker) worker.interrupt();
                }
            }, SUBTITLE_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            YoutubeDLRequest request = singleVideoRequest(job);
            if (cookieCopy != null) request.addOption("--cookies", cookieCopy.getAbsolutePath());
            DownloadCover.configure(request, work);
            job.checkCanceled();
            engine.execute(request, job.id, false);
            job.checkCanceled();
            DownloadCover.Image image = DownloadCover.find(work, savedName);
            if (image == null) return "未取得可保存的封面。";
            saveExtra(job, image.file, image.displayName, image.mimeType);
            return "已保存封面。";
        } catch (Exception error) {
            synchronized (LOCK) {
                return running.stopped ? "已停止下载封面。" : "封面未能下载或保存。";
            }
        } finally {
            synchronized (LOCK) {
                job.attachmentWorker = null;
                if (deadline != null) deadline.cancel(false);
            }
            Thread.interrupted();
        }
    }

    private static File copyCookiesForRequest(YoutubeDLRequest request, File source, File work) throws IOException {
        // yt-dlp may save its cookie jar when the process ends.
        File copy = new File(work, source.getName());
        Files.copy(source.toPath(), copy.toPath());
        request.addOption("--cookies", copy.getAbsolutePath());
        return copy;
    }

    private static boolean nonEmptyFile(File file) {
        return Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS) && file.length() > 0;
    }

    private static void cleanWorkDirectory(File work) {
        File[] items = work.listFiles();
        if (items != null) {
            for (File item : items) item.delete();
        }
        work.delete();
    }

    private static void addTransferProgress(YoutubeDLRequest request) {
        request.addOption("--newline");
        request.addOption("--progress");
        request.addOption("--progress-template", TransferProgress.TEMPLATE);
    }

    private Uri stageOutput(Job job, File file, String displayName, String mimeType) throws IOException {
        job.checkCanceled();
        ContentValues values = new ContentValues();
        values.put(MediaStore.Downloads.DISPLAY_NAME, displayName);
        values.put(MediaStore.Downloads.MIME_TYPE, mimeType);
        values.put(MediaStore.Downloads.RELATIVE_PATH, DownloadDestination.mediaStorePath(job.folders.toArray(new String[0])));
        values.put(MediaStore.Downloads.IS_PENDING, 1);
        Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        if (uri == null) throw new IOException("手机的下载目录暂不可写。");

        try {
            try (FileInputStream input = new FileInputStream(file);
                 OutputStream output = getContentResolver().openOutputStream(uri, "w")) {
                if (output == null) throw new IOException("无法写入手机的下载目录。");
                byte[] buffer = new byte[64 * 1024];
                for (int count; (count = input.read(buffer)) != -1; ) {
                    job.checkCanceled();
                    output.write(buffer, 0, count);
                }
            }
            return uri;
        } catch (IOException | RuntimeException error) {
            discardOutput(uri);
            throw error;
        }
    }

    private Uri[] saveMedia(Job job, File main, File audio) throws IOException {
        if (job.destinationTree != null) {
            List<DownloadDestination.Output> outputs = new ArrayList<>();
            outputs.add(new DownloadDestination.Output(main, main.getName(), job.mimeType()));
            if (audio != null) outputs.add(new DownloadDestination.Output(audio, audio.getName(), job.audioFormat.mimeType));
            DownloadDestination.Saved saved = DownloadDestination.save(this, job.destinationTree, job.folders, outputs,
                    job::checkCanceled, () -> markFinalizing(job));
            return new Uri[] {saved.files.get(0), audio == null ? null : saved.files.get(1), saved.directory};
        }
        Uri primary = null;
        Uri companion = null;
        try {
            primary = stageOutput(job, main, main.getName(), job.mimeType());
            if (audio != null) companion = stageOutput(job, audio, audio.getName(), job.audioFormat.mimeType);
            synchronized (LOCK) {
                job.checkCanceled();
                ContentValues values = new ContentValues();
                values.put(MediaStore.Downloads.IS_PENDING, 0);
                ArrayList<ContentProviderOperation> operations = new ArrayList<>();
                operations.add(ContentProviderOperation.newUpdate(primary).withValues(values).withExpectedCount(1).build());
                if (companion != null) {
                    operations.add(ContentProviderOperation.newUpdate(companion).withValues(values).withExpectedCount(1).build());
                }
                try {
                    getContentResolver().applyBatch(MediaStore.AUTHORITY, operations);
                } catch (RemoteException | OperationApplicationException error) {
                    throw new IOException("无法确认文件已保存。", error);
                }
                job.finalizing = true;
            }
            return new Uri[] {primary, companion, null};
        } catch (IOException | RuntimeException error) {
            discardOutput(primary);
            discardOutput(companion);
            throw error;
        }
    }

    private static void markFinalizing(Job job) {
        synchronized (LOCK) {
            job.checkCanceled();
            job.finalizing = true;
        }
    }

    private void saveExtra(Job job, File file, String name, String mimeType) throws IOException {
        Uri uri;
        Uri directory = null;
        if (job.destinationTree != null) {
            DownloadDestination.Saved saved = DownloadDestination.save(this, job.destinationTree, job.folders,
                    Collections.singletonList(new DownloadDestination.Output(file, name, mimeType)),
                    job::checkCanceled, job::checkCanceled);
            uri = saved.files.get(0);
            directory = saved.directory;
        } else {
            uri = stageOutput(job, file, name, mimeType);
            try {
                job.checkCanceled();
                ContentValues values = new ContentValues();
                values.put(MediaStore.Downloads.IS_PENDING, 0);
                if (getContentResolver().update(uri, values, null, null) != 1) throw new IOException("附件保存失败。");
            } catch (IOException | RuntimeException error) {
                discardOutput(uri);
                throw error;
            }
        }
        String actualName = readDisplayName(uri);
        job.attachments.add(new DownloadHistory.Attachment(uri, directory,
                actualName == null || actualName.isEmpty() ? name : actualName, mimeType));
    }

    private void discardOutput(Uri uri) {
        if (uri == null) return;
        try {
            getContentResolver().delete(uri, null, null);
        } catch (RuntimeException ignored) {
            // The pending file remains hidden and is eligible for expiration.
        }
    }

    private String readDisplayName(Uri uri) {
        // MediaStore may rename a duplicate. A metadata failure cannot undo a published download.
        try (Cursor cursor = getContentResolver().query(uri,
                new String[] {MediaStore.Downloads.DISPLAY_NAME}, null, null, null)) {
            return cursor != null && cursor.moveToFirst() ? cursor.getString(0) : null;
        } catch (RuntimeException error) {
            return null;
        }
    }

    private static void update(Job job, State next) {
        update(job, next, null);
    }

    private static void update(Job job, State next, MediaStep step) {
        synchronized (LOCK) {
            if (active != job || job.canceled) return;
            if (step != null) job.mediaStepIndex = job.mediaSteps.indexOf(step);
            state = next;
        }
    }

    private static String describeEngineFailure(Exception error, Job job, boolean usesCookies) {
        String diagnostic = error.getMessage();
        if (diagnostic != null && diagnostic.toLowerCase(Locale.ROOT).contains("requested format is not available")) {
            return job.audioOnly ? "源素材没有可用的音频或音视频流。"
                    : "源素材缺少符合当前画质的音轨或视频轨，请尝试切换画质。";
        }
        if (!usesCookies && diagnostic != null && !diagnostic.trim().isEmpty()) return describe(error);
        String phase;
        synchronized (LOCK) {
            phase = state.phase;
        }
        String stage = "正在下载".equals(phase) ? "下载媒体数据"
                : "正在处理视频".equals(phase) ? "封装视频"
                : "正在处理音频".equals(phase) ? "整理 M4A" : "解析视频";
        return CookieDownloadFailure.describe(diagnostic, job.platform, stage);
    }

    private static String describe(Exception error) {
        String text = error.getMessage();
        if (text == null || text.trim().isEmpty()) return "请检查网络并重试。";
        String[] lines = text.split("\\r?\\n");
        String detail = lines[0];
        for (String line : lines) {
            if (line.startsWith("ERROR:")) {
                detail = line;
                break;
            }
        }
        detail = detail.replaceAll("https?://\\S+", "[链接]").trim();
        if (detail.isEmpty()) return "请检查网络并重试。";
        return detail.length() > 230 ? detail.substring(0, 230) + "…" : detail;
    }
}
