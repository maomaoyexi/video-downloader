package io.github.maomaoyexi.videodownloader.prototype;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.provider.DocumentsContract.Document;
import android.provider.MediaStore;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.Collections;
import java.util.List;
import java.util.Set;

final class DownloadHistory {
    private static final Object LOCK = new Object();
    private static final String FILE_NAME = "download-history.json";
    private static final int LIMIT = 200;
    private static final String VIDEO_URI = "videoUri";
    private static final String AUDIO_URI = "audioUri";
    private static final String DIRECTORY_URI = "directoryUri";
    private static final String MAIN_NAME = "mainName";
    private static final String AUDIO_NAME = "audioName";
    private static final String ATTACHMENTS = "attachments";
    private static final String ATTACHMENT_URI = "uri";
    private static final String ATTACHMENT_NAME = "name";
    private static final String ATTACHMENT_MIME = "mimeType";
    static final String SUBTITLE_MIME = "application/x-subrip";
    private static final String EXTERNAL_STORAGE_DOCUMENTS = "com.android.externalstorage.documents";
    private static final String FILE_ERROR = "无法核实或删除下载文件。请检查文件位置和目录授权后重试。";
    private static final String[] PUBLIC_FIELDS = {"id", "title", "platform", "finishedAt", "status", "audioOnly"};

    enum Status {
        COMPLETED("completed"), FAILED("failed"), CANCELED("canceled");

        final String id;

        Status(String id) {
            this.id = id;
        }
    }

    private DownloadHistory() {}

    static final class Attachment {
        final Uri uri;
        final Uri directory;
        final String name;
        final String mimeType;

        Attachment(Uri uri, String name, String mimeType) {
            this(uri, null, name, mimeType);
        }

        Attachment(Uri uri, Uri directory, String name, String mimeType) {
            this.uri = uri;
            this.directory = directory;
            this.name = name;
            this.mimeType = mimeType;
        }
    }

    static void record(Context context, String id, String title, String platform, Status status, Uri media) {
        record(context, id, title, platform, status, media, false);
    }

    static void record(Context context, String id, String title, String platform, Status status, Uri media,
                       boolean audioOnly) {
        record(context, id, title, platform, status, media, null, audioOnly ? "audio" : "video");
    }

    static void record(Context context, String id, String title, String platform, Status status, Uri media,
                       Uri audio, String outputMode) {
        record(context, id, title, platform, status, media, audio, outputMode, null);
    }

    static void record(Context context, String id, String title, String platform, Status status, Uri media,
                       Uri audio, String outputMode, Uri directory) {
        record(context, id, title, platform, status, media, audio, outputMode, directory, null, null, null);
    }

    static void record(Context context, String id, String title, String platform, Status status, Uri media,
                       Uri audio, String outputMode, Uri directory, String authorFolder, String mainName,
                       String audioName) {
        record(context, id, title, platform, status, media, audio, outputMode, directory, authorFolder,
                mainName, audioName, Collections.emptyList());
    }

    static void record(Context context, String id, String title, String platform, Status status, Uri media,
                       Uri audio, String outputMode, Uri directory, String authorFolder, String mainName,
                       String audioName, List<Attachment> attachments) {
        long finishedAt = System.currentTimeMillis();
        String mode = normalizeOutputMode(outputMode, false);
        synchronized (LOCK) {
            try {
                File target = new File(context.getNoBackupFilesDir(), FILE_NAME);
                JSONArray previous = read(target);
                JSONObject item = new JSONObject().put("id", id).put("title", title)
                        .put("platform", platform).put("finishedAt", finishedAt).put("status", status.id)
                        .put("audioOnly", "audio".equals(mode)).put("outputMode", mode);
                if (media != null) item.put(VIDEO_URI, media.toString()).put(MAIN_NAME, mainName);
                if (audio != null) item.put(AUDIO_URI, audio.toString()).put(AUDIO_NAME, audioName);
                if (directory != null) item.put(DIRECTORY_URI, directory.toString());
                item.put("authorFolder", authorFolder);
                if (!attachments.isEmpty()) {
                    JSONArray stored = new JSONArray();
                    for (Attachment attachment : attachments) {
                        JSONObject file = new JSONObject().put(ATTACHMENT_URI, attachment.uri.toString())
                                .put(ATTACHMENT_NAME, attachment.name).put(ATTACHMENT_MIME, attachment.mimeType);
                        if (attachment.directory != null) file.put(DIRECTORY_URI, attachment.directory.toString());
                        stored.put(file);
                    }
                    item.put(ATTACHMENTS, stored);
                }
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
                Set<Uri> readableTrees = DownloadDestination.readableTrees(context);
                JSONArray result = new JSONArray();
                for (int i = 0; i < stored.length() && i < LIMIT; i++) {
                    JSONObject item = stored.optJSONObject(i);
                    if (item == null) continue;
                    String mode = normalizeOutputMode(item.optString("outputMode"), item.optBoolean("audioOnly"));
                    boolean completed = Status.COMPLETED.id.equals(item.optString("status"));
                    boolean hasMainFile = completed && downloadUri(item, VIDEO_URI, readableTrees) != null;
                    boolean hasAudioFile = completed && downloadUri(item, AUDIO_URI, readableTrees) != null;
                    JSONArray mediaNames = new JSONArray();
                    if (completed && !item.isNull(VIDEO_URI)) addName(mediaNames, item.optString(MAIN_NAME));
                    if (completed && !item.isNull(AUDIO_URI)) addName(mediaNames, item.optString(AUDIO_NAME));
                    JSONArray attachmentNames = new JSONArray();
                    JSONArray attachments = item.optJSONArray(ATTACHMENTS);
                    if (completed && attachments != null) {
                        for (int index = 0; index < attachments.length(); index++) {
                            JSONObject file = attachments.optJSONObject(index);
                            if (file != null) addName(attachmentNames, file.optString(ATTACHMENT_NAME));
                        }
                    }
                    String author = item.optString("authorFolder");
                    result.put(new JSONObject(item, PUBLIC_FIELDS)
                            .put("outputMode", mode)
                            .put("hasMainFile", hasMainFile).put("hasAudioFile", hasAudioFile)
                            .put("authorFolder", author.isEmpty() ? "未知作者" : author)
                            .put("mediaNames", mediaNames)
                            .put("attachmentNames", attachmentNames));
                }
                return result.toString();
            } catch (IOException | JSONException | RuntimeException error) {
                return "[]";
            }
        }
    }

    static Uri completedVideo(Context context, String id) {
        return completedMedia(context, id, VIDEO_URI);
    }

    static Uri completedAudio(Context context, String id) {
        return completedMedia(context, id, AUDIO_URI);
    }

    static Uri completedDirectory(Context context, String id) {
        return completedMedia(context, id, DIRECTORY_URI);
    }

    static String delete(Context context, String id, boolean deleteFiles) {
        if (id == null || id.length() != 36) return "无法识别这条下载记录。";
        synchronized (LOCK) {
            try {
                File target = new File(context.getNoBackupFilesDir(), FILE_NAME);
                JSONArray records = read(target);
                for (int i = 0; i < records.length() && i < LIMIT; i++) {
                    JSONObject item = records.optJSONObject(i);
                    if (item == null || !id.equals(item.optString("id"))) continue;
                    if (deleteFiles && Status.COMPLETED.id.equals(item.optString("status"))) {
                        String mode = normalizeOutputMode(item.optString("outputMode"), item.optBoolean("audioOnly"));
                        if (!item.has(VIDEO_URI) || (mode.endsWith("-and-audio") && !item.has(AUDIO_URI))) {
                            return FILE_ERROR;
                        }
                        String failure = deleteMedia(context, target, records, item, VIDEO_URI, MAIN_NAME,
                                "audio".equals(mode) ? "audio/" : "video/");
                        if (!failure.isEmpty()) return failure;
                        failure = deleteMedia(context, target, records, item, AUDIO_URI, AUDIO_NAME, "audio/");
                        if (!failure.isEmpty()) return failure;
                        failure = deleteAttachments(context, target, records, item);
                        if (!failure.isEmpty()) return failure;
                    }
                    records.remove(i);
                    write(target, records);
                    break;
                }
                return "";
            } catch (IOException | JSONException | RuntimeException error) {
                return "无法更新下载历史，请稍后重试。";
            }
        }
    }

    private static String deleteMedia(Context context, File target, JSONArray records, JSONObject item,
                                      String field, String nameField, String mimePrefix)
            throws IOException, JSONException {
        if (item.isNull(field)) return "";
        Uri media = downloadUri(item, field, DownloadDestination.readableTrees(context));
        String failure = deleteFile(context, records, item, media, storedUri(item, DIRECTORY_URI),
                item.optString(nameField), mimePrefix);
        if (!failure.isEmpty()) return failure;
        // An explicit null preserves progress across retries, even if a later file cannot be deleted.
        item.put(field, JSONObject.NULL);
        item.remove(nameField);
        write(target, records);
        return "";
    }

    private static String deleteAttachments(Context context, File target, JSONArray records, JSONObject item)
            throws IOException {
        if (!item.has(ATTACHMENTS)) return "";
        JSONArray attachments = item.optJSONArray(ATTACHMENTS);
        if (attachments == null) return FILE_ERROR;
        while (attachments.length() > 0) {
            JSONObject attachment = attachments.optJSONObject(0);
            if (attachment == null) return FILE_ERROR;
            String name = attachment.optString(ATTACHMENT_NAME);
            String mime = attachment.optString(ATTACHMENT_MIME);
            if (name.isEmpty() || !(SUBTITLE_MIME.equals(mime) || mime.startsWith("image/"))) return FILE_ERROR;
            Uri directory = storedUri(attachment, DIRECTORY_URI);
            if (directory == null) directory = storedUri(item, DIRECTORY_URI);
            Uri file = storedUri(attachment, ATTACHMENT_URI);
            String failure = deleteFile(context, records, item, file, directory, name, mime);
            if (!failure.isEmpty()) return failure;
            attachments.remove(0);
            write(target, records);
        }
        return "";
    }

    private static String deleteFile(Context context, JSONArray records, JSONObject item, Uri media, Uri directory,
                                     String name, String mimeType) {
        if (media == null) return FILE_ERROR;
        for (int i = 0; i < records.length(); i++) {
            JSONObject other = records.optJSONObject(i);
            if (other != null && other != item && referencesFile(other, media)) {
                return "该文件还关联其他下载记录，可以仅删除当前记录。";
            }
        }
        try {
            if (downloadId(media) >= 0) {
                deleteMediaStoreFile(context, media, name, mimeType);
            } else {
                deleteDocument(context, media, directory, name, mimeType);
            }
        } catch (IOException | RuntimeException error) {
            return FILE_ERROR;
        }
        return "";
    }

    private static boolean referencesFile(JSONObject record, Uri media) {
        if (sameFile(media, storedUri(record, VIDEO_URI)) || sameFile(media, storedUri(record, AUDIO_URI))) return true;
        JSONArray attachments = record.optJSONArray(ATTACHMENTS);
        if (attachments == null) return false;
        for (int index = 0; index < attachments.length(); index++) {
            JSONObject file = attachments.optJSONObject(index);
            if (file != null && sameFile(media, storedUri(file, ATTACHMENT_URI))) return true;
        }
        return false;
    }

    private static void deleteMediaStoreFile(Context context, Uri media, String name, String mimePrefix)
            throws IOException {
        ContentResolver resolver = context.getContentResolver();
        try (Cursor row = resolver.query(media, new String[]{MediaStore.MediaColumns._ID,
                MediaStore.MediaColumns.OWNER_PACKAGE_NAME, MediaStore.MediaColumns.DISPLAY_NAME,
                MediaStore.MediaColumns.MIME_TYPE}, null, null, null)) {
            if (!completeQuery(row)) throw new IOException();
            if (!row.moveToFirst()) return;
            if (row.getLong(0) != downloadId(media) || !context.getPackageName().equals(row.getString(1))
                    || !matchesMedia(name, row.getString(2), mimePrefix, row.getString(3)) || row.moveToNext()) {
                throw new IOException();
            }
        }
        int deleted = resolver.delete(media, null, null);
        if (deleted == 1) return;
        if (deleted != 0 || !queryIsEmpty(resolver, media, MediaStore.MediaColumns._ID)) throw new IOException();
    }

    private static void deleteDocument(Context context, Uri media, Uri directory, String name, String mimePrefix)
            throws IOException {
        Uri tree = DownloadDestination.documentTree(media);
        if (tree == null || media.equals(directory) || !tree.equals(DownloadDestination.documentTree(directory))
                || !DownloadDestination.hasWriteAccess(context, tree)) {
            throw new IOException();
        }
        ContentResolver resolver = context.getContentResolver();
        String parentId = DocumentsContract.getDocumentId(directory);
        String id = DocumentsContract.getDocumentId(media);
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(directory, parentId);
        if (containsDocument(resolver, children, id, name, mimePrefix)) {
            try {
                if (DocumentsContract.deleteDocument(resolver, media)) return;
            } catch (FileNotFoundException missing) {
                // The file manager may have removed it after the directory query.
            }
            if (containsDocument(resolver, children, id, name, mimePrefix)) throw new IOException();
        }
        // The system provider uses volume-and-path IDs. A complete listing of the exact parent
        // can confirm absence even when querying the missing document would fail.
        if (EXTERNAL_STORAGE_DOCUMENTS.equals(media.getAuthority()) && isDirectChild(parentId, id)) return;
        if (!queryIsEmpty(resolver, media, Document.COLUMN_DOCUMENT_ID)) throw new IOException();
    }

    private static boolean containsDocument(ContentResolver resolver, Uri children, String id,
                                            String name, String mimePrefix) throws IOException {
        boolean found = false;
        try (Cursor rows = resolver.query(children, new String[]{Document.COLUMN_DOCUMENT_ID,
                Document.COLUMN_DISPLAY_NAME, Document.COLUMN_MIME_TYPE, Document.COLUMN_FLAGS},
                null, null, null)) {
            if (!completeQuery(rows)) throw new IOException();
            while (rows.moveToNext()) {
                if (!id.equals(rows.getString(0))) continue;
                if (found || !matchesMedia(name, rows.getString(1), mimePrefix, rows.getString(2))
                        || (rows.getLong(3) & Document.FLAG_SUPPORTS_DELETE) == 0) {
                    throw new IOException();
                }
                found = true;
            }
        }
        return found;
    }

    private static boolean isDirectChild(String parentId, String id) {
        String prefix = parentId.endsWith(":") ? parentId : parentId + "/";
        if (!id.startsWith(prefix)) return false;
        String child = id.substring(prefix.length());
        return !child.isEmpty() && child.indexOf('/') < 0 && !".".equals(child) && !"..".equals(child);
    }

    private static boolean queryIsEmpty(ContentResolver resolver, Uri uri, String column) {
        try (Cursor row = resolver.query(uri, new String[]{column}, null, null, null)) {
            return completeQuery(row) && !row.moveToFirst();
        }
    }

    private static boolean completeQuery(Cursor rows) {
        if (rows == null) return false;
        Bundle extras = rows.getExtras();
        return extras == null || (!extras.getBoolean(DocumentsContract.EXTRA_LOADING)
                && !extras.containsKey(DocumentsContract.EXTRA_ERROR));
    }

    private static boolean matchesMedia(String name, String actualName, String mimeType, String actualMime) {
        if (actualName == null || actualName.isEmpty() || (!name.isEmpty() && !name.equals(actualName))
                || actualMime == null) return false;
        if (mimeType.endsWith("/")) return actualMime.startsWith(mimeType);
        if (mimeType.equals(actualMime)) return true;
        // Some document providers report SRT as plain text or a generic binary file.
        return SUBTITLE_MIME.equals(mimeType) && !name.isEmpty()
                && ("text/plain".equals(actualMime) || "application/octet-stream".equals(actualMime));
    }

    private static boolean sameFile(Uri first, Uri second) {
        if (second == null) return false;
        if (first.equals(second)) return true;
        long firstId = downloadId(first);
        if (firstId >= 0 && firstId == downloadId(second)) {
            String firstVolume = first.getPathSegments().get(0);
            String secondVolume = second.getPathSegments().get(0);
            return firstVolume.equals(secondVolume) || MediaStore.VOLUME_EXTERNAL.equals(firstVolume)
                    || MediaStore.VOLUME_EXTERNAL.equals(secondVolume);
        }
        return DownloadDestination.documentTree(first) != null && DownloadDestination.documentTree(second) != null
                && first.getAuthority().equals(second.getAuthority())
                && DocumentsContract.getDocumentId(first).equals(DocumentsContract.getDocumentId(second));
    }

    private static long downloadId(Uri media) {
        if (media == null || !ContentResolver.SCHEME_CONTENT.equals(media.getScheme())
                || !MediaStore.AUTHORITY.equals(media.getAuthority()) || media.getQuery() != null
                || media.getFragment() != null) return -1;
        List<String> path = media.getPathSegments();
        if (path.size() != 3 || !"downloads".equals(path.get(1))) return -1;
        String volume = path.get(0);
        if (!MediaStore.VOLUME_EXTERNAL.equals(volume) && !MediaStore.VOLUME_EXTERNAL_PRIMARY.equals(volume)
                && !volume.matches("[0-9a-f]+-[0-9a-f]+")) return -1;
        try {
            long id = Long.parseLong(path.get(2));
            return id > 0 && media.equals(MediaStore.Downloads.getContentUri(volume, id)) ? id : -1;
        } catch (NumberFormatException error) {
            return -1;
        }
    }

    private static Uri completedMedia(Context context, String id, String field) {
        if (id == null || id.length() != 36) return null;
        synchronized (LOCK) {
            try {
                JSONArray records = read(new File(context.getNoBackupFilesDir(), FILE_NAME));
                for (int i = 0; i < records.length() && i < LIMIT; i++) {
                    JSONObject item = records.optJSONObject(i);
                    if (item != null && id.equals(item.optString("id"))
                            && Status.COMPLETED.id.equals(item.optString("status"))) {
                        Uri media = downloadUri(item, field, DownloadDestination.readableTrees(context));
                        if (media != null) return media;
                    }
                }
            } catch (IOException | JSONException | RuntimeException error) {
                return null;
            }
            return null;
        }
    }

    private static Uri downloadUri(JSONObject item, String field, Set<Uri> readableTrees) {
        Uri media = storedUri(item, field);
        boolean directory = DIRECTORY_URI.equals(field);
        if (!directory && downloadId(media) >= 0) return media;
        Uri tree = DownloadDestination.documentTree(media);
        Uri counterpart = storedUri(item, directory ? VIDEO_URI : DIRECTORY_URI);
        if (directory && counterpart == null) counterpart = storedUri(item, AUDIO_URI);
        return tree != null && readableTrees.contains(tree) && !media.equals(counterpart)
                && tree.equals(DownloadDestination.documentTree(counterpart)) ? media : null;
    }

    private static Uri storedUri(JSONObject item, String field) {
        return item.isNull(field) || item.optString(field).isEmpty() ? null : Uri.parse(item.optString(field));
    }

    private static void addName(JSONArray names, String name) {
        if (!name.isEmpty()) names.put(name);
    }

    private static String normalizeOutputMode(String mode, boolean audioOnly) {
        if ("video".equals(mode) || "audio".equals(mode) || "video-and-audio".equals(mode)
                || "silent-video-and-audio".equals(mode)) return mode;
        return audioOnly ? "audio" : "video";
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
