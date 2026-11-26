package io.github.maomaoyexi.videodownloader.prototype;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.TimeUnit;

final class MediaTracks {
    private static final String PROBE_ERROR = "无法检查下载文件的音视频轨。";
    private static final String VIDEO_ERROR = "无法将下载文件的视频轨保存为无声 MP4。";
    private static final int PROBE_TIMEOUT_SECONDS = 45;
    private static final int CONVERSION_TIMEOUT_SECONDS = 3600;
    private static final long MAX_PROCESS_OUTPUT = 64 * 1024;

    @FunctionalInterface
    interface Cancellation {
        void check() throws InterruptedException;
    }

    enum AudioFormat {
        M4A("m4a", "audio/mp4", "ipod", "aac"),
        FLAC("flac", "audio/flac", "flac", "flac"),
        OPUS("opus", "audio/ogg", "opus", "opus"),
        WAV("wav", "audio/wav", "wav", "pcm_s16le");

        final String extension;
        final String mimeType;
        final String muxer;
        final String codec;

        AudioFormat(String extension, String mimeType, String muxer, String codec) {
            this.extension = extension;
            this.mimeType = mimeType;
            this.muxer = muxer;
            this.codec = codec;
        }

        static AudioFormat fromId(String id) {
            for (AudioFormat format : values()) {
                if (format.extension.equals(id)) return format;
            }
            return null;
        }
    }

    static final class Tracks {
        final boolean hasVideo;
        final boolean hasAudio;
        private final String firstAudioCodec;

        private Tracks(boolean hasVideo, boolean hasAudio, String firstAudioCodec) {
            this.hasVideo = hasVideo;
            this.hasAudio = hasAudio;
            this.firstAudioCodec = firstAudioCodec;
        }
    }

    private MediaTracks() {}

    static Tracks inspect(Context context, File input, Cancellation cancellation)
            throws IOException, InterruptedException {
        if (!input.isFile() || input.length() == 0) throw new IOException(PROBE_ERROR);
        String result = run(context, "libffprobe.so", Arrays.asList(
                "-v", "quiet", "-protocol_whitelist", "file",
                "-show_entries", "stream=codec_name,codec_type:stream_disposition=attached_pic",
                "-of", "json", "-i", input.getAbsolutePath()),
                PROBE_TIMEOUT_SECONDS, PROBE_ERROR, cancellation);
        try {
            JSONArray streams = new JSONObject(result).optJSONArray("streams");
            if (streams == null) throw new IOException(PROBE_ERROR);
            boolean hasVideo = false;
            boolean hasAudio = false;
            String firstAudioCodec = "";
            for (int i = 0; i < streams.length(); i++) {
                JSONObject stream = streams.getJSONObject(i);
                String type = stream.optString("codec_type");
                if ("video".equals(type)) {
                    JSONObject disposition = stream.optJSONObject("disposition");
                    if (disposition == null || disposition.optInt("attached_pic") != 1) hasVideo = true;
                } else if ("audio".equals(type) && !hasAudio) {
                    hasAudio = true;
                    firstAudioCodec = stream.optString("codec_name");
                }
            }
            return new Tracks(hasVideo, hasAudio, firstAudioCodec);
        } catch (JSONException error) {
            throw new IOException(PROBE_ERROR, error);
        }
    }

    static void audio(Context context, File input, File output, AudioFormat format, Cancellation cancellation)
            throws IOException, InterruptedException {
        Tracks tracks = inspect(context, input, cancellation);
        if (!tracks.hasAudio) throw new IOException("下载文件中没有音轨。");
        boolean copy = format.codec.equals(tracks.firstAudioCodec)
                || (format == AudioFormat.M4A && "alac".equals(tracks.firstAudioCodec));
        List<String> options = new ArrayList<>(Arrays.asList("-map", "0:a:0", "-c:a", copy ? "copy" : format.codec));
        if (format == AudioFormat.OPUS && !copy) options.addAll(Arrays.asList("-strict", "experimental", "-ac", "2"));
        options.addAll(Arrays.asList("-f", format.muxer));
        convert(context, input, output, options, true,
                "无法生成 " + format.extension.toUpperCase(java.util.Locale.ROOT) + " 音频。", cancellation);
    }

    static void silentVideo(Context context, File input, File output, Cancellation cancellation)
            throws IOException, InterruptedException {
        List<String> options = Arrays.asList("-map", "0:V:0", "-c:v", "copy", "-f", "mp4");
        convert(context, input, output, options, false, VIDEO_ERROR, cancellation);
    }

    private static void convert(Context context, File input, File output, List<String> options,
                                boolean audioOnly, String failure, Cancellation cancellation)
            throws IOException, InterruptedException {
        File destination = output.getAbsoluteFile();
        if (destination.exists()) throw new IOException("媒体处理的目标文件已存在。");
        checkCanceled(cancellation);
        File staging = File.createTempFile("media-", ".part", destination.getParentFile());
        try {
            List<String> arguments = new ArrayList<>(Arrays.asList(
                    "-nostdin", "-v", "quiet", "-y", "-protocol_whitelist", "file", "-i", input.getAbsolutePath(),
                    "-map_chapters", "-1", "-abort_on", "empty_output"));
            arguments.addAll(options);
            arguments.add(staging.getAbsolutePath());
            run(context, "libffmpeg.so", arguments, CONVERSION_TIMEOUT_SECONDS, failure, cancellation);
            Tracks tracks = inspect(context, staging, cancellation);
            boolean expectedTracks = audioOnly
                    ? tracks.hasAudio && !tracks.hasVideo
                    : tracks.hasVideo && !tracks.hasAudio;
            if (!expectedTracks) throw new IOException(failure);
            checkCanceled(cancellation);
            Files.move(staging.toPath(), destination.toPath());
        } finally {
            staging.delete();
        }
    }

    private static String run(Context context, String executableName, List<String> arguments,
                              int timeoutSeconds, String failure, Cancellation cancellation)
            throws IOException, InterruptedException {
        checkCanceled(cancellation);
        File executable = new File(context.getApplicationInfo().nativeLibraryDir, executableName);
        if (!executable.isFile()) throw new IOException("应用缺少媒体处理组件，请重新安装后重试。");

        File log = File.createTempFile("media-tracks-", ".txt", context.getCacheDir());
        Process process = null;
        try {
            List<String> command = new ArrayList<>();
            command.add(executable.getAbsolutePath());
            command.addAll(arguments);
            try {
                process = new ProcessBuilder(command)
                        .redirectErrorStream(true)
                        .redirectOutput(log)
                        .start();
                process.getOutputStream().close();
            } catch (IOException error) {
                throw new IOException(failure, error);
            }
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(timeoutSeconds);
            while (!process.waitFor(100, TimeUnit.MILLISECONDS)) {
                checkCanceled(cancellation);
                if (System.nanoTime() - deadline >= 0) throw new IOException("本地媒体处理超时。");
                if (log.length() > MAX_PROCESS_OUTPUT) throw new IOException(failure);
            }
            checkCanceled(cancellation);
            if (process.exitValue() != 0 || log.length() > MAX_PROCESS_OUTPUT) throw new IOException(failure);
            return new String(Files.readAllBytes(log.toPath()), StandardCharsets.UTF_8);
        } finally {
            if (process != null && process.isAlive()) {
                process.destroyForcibly();
                try {
                    process.waitFor(1, TimeUnit.SECONDS);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                }
            }
            log.delete();
        }
    }

    private static void checkCanceled(Cancellation cancellation) throws InterruptedException {
        cancellation.check();
        if (Thread.currentThread().isInterrupted()) throw new InterruptedException();
    }
}
