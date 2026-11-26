package io.github.maomaoyexi.videodownloader.prototype;

import android.content.Context;
import android.net.Uri;
import android.provider.MediaStore;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.List;

final class DownloadHistory {
    private static final Object LOCK = new Object();
    private static final String FILE_NAME = "download-history.json";
    private static final int LIMIT = 200;
    private static final String[] PUBLIC_FIELDS = {"id", "title", "platform", "finishedAt", "status", "audioOnly"};

    enum Status {
        COMPLETED("completed"), FAILED("failed"), CANCELED("canceled");

        final String id;

        Status(String id) {
            this.id = id;
        }
    }

    private DownloadHistory() {}

    static void record(Context context, String id, String title, String platform, Status status, Uri media) {
        record(context, id, title, platform, status, media, false);
    }

    static void record(Context context, String id, String title, String platform, Status status, Uri media,
                       boolean audioOnly) {
        long finishedAt = System.currentTimeMillis();
        synchronized (LOCK) {
            try {
                File target = new File(context.getNoBackupFilesDir(), FILE_NAME);
                JSONArray previous = read(target);
                JSONObject item = new JSONObject().put("id", id).put("title", title)
                        .put("platform", platform).put("finishedAt", finishedAt).put("status", status.id)
                        .put("audioOnly", audioOnly);
                if (media != null) item.put("videoUri", media.toString());
                JSONArray next = new JSONArray().put(item);
                for (int i = 0; i < previous.length() && next.length() < LIMIT; i++) {
                    JSONObject entry = previous.optJSONObject(i);
                    if (entry != null && !id.equals(entry.optString("id"))) next.put(entry);
                }
                write(target, next);
            } catch (IOException | JSONException | RuntimeException error) {
                // History failure cannot change the outcome of a download.
                Log.w("DownloadHistory", "Could not store download history");
            }
        }
    }

    static String list(Context context) {
        synchronized (LOCK) {
            try {
                JSONArray stored = read(new File(context.getNoBackupFilesDir(), FILE_NAME));
                JSONArray result = new JSONArray();
                for (int i = 0; i < stored.length() && i < LIMIT; i++) {
                    JSONObject item = stored.optJSONObject(i);
                    if (item != null) result.put(new JSONObject(item, PUBLIC_FIELDS));
                }
                return result.toString();
            } catch (IOException | JSONException | RuntimeException error) {
                return "[]";
            }
        }
    }

    static Uri completedVideo(Context context, String id) {
        if (id == null || id.length() != 36) return null;
        synchronized (LOCK) {
            try {
                JSONArray records = read(new File(context.getNoBackupFilesDir(), FILE_NAME));
                for (int i = 0; i < records.length() && i < LIMIT; i++) {
                    JSONObject item = records.optJSONObject(i);
                    if (item != null && id.equals(item.optString("id"))
                            && Status.COMPLETED.id.equals(item.optString("status"))) {
                        Uri video = Uri.parse(item.optString("videoUri"));
                        List<String> path = video.getPathSegments();
                        if ("content".equals(video.getScheme()) && MediaStore.AUTHORITY.equals(video.getAuthority())
                                && path.size() == 3 && "downloads".equals(path.get(1))
                                && path.get(2).matches("[0-9]+")) return video;
                    }
                }
            } catch (IOException | JSONException | RuntimeException error) {
                return null;
            }
            return null;
        }
    }

    private static JSONArray read(File file) throws IOException, JSONException {
        if (Files.notExists(file.toPath())) return new JSONArray();
        return new JSONArray(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
    }

    private static void write(File target, JSONArray records) throws IOException {
        File staging = new File(target.getParentFile(), FILE_NAME + ".new");
        try {
            try (FileOutputStream stream = new FileOutputStream(staging)) {
                stream.write(records.toString().getBytes(StandardCharsets.UTF_8));
                stream.getFD().sync();
            }
            Files.move(staging.toPath(), target.toPath(),
                    StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally {
            Files.deleteIfExists(staging.toPath());
        }
    }
}
