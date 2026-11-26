package io.github.maomaoyexi.videodownloader.prototype;

import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.UriPermission;
import android.database.Cursor;
import android.net.Uri;
import android.os.Environment;
import android.provider.DocumentsContract;
import android.provider.DocumentsContract.Document;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

final class DownloadDestination {
    private static final Object SETTINGS_LOCK = new Object();
    private static final String PREFERENCES = "download-destination";
    private static final String TREE = "tree";
    private static final String CLASSIFICATION = "classification";
    private static final String NONE = "none";
    private static final String PLATFORM = "platform";
    static final String PLATFORM_AUTHOR = "platform-author";
    private static final String OUTPUT = "output";
    private static final String ROOT_DIRECTORY = "多平台下载";
    private static final String LOST_PERMISSION = "自选下载目录的授权已失效，请在设置中重新选择目录。";
    private static final String SAVE_FAILURE = "无法写入自选下载目录，请检查目录权限和剩余空间。";
    private static final int ACCESS = Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION;

    static final class Snapshot {
        final Uri tree;
        final String classification;

        private Snapshot(Uri tree, String classification) {
            this.tree = tree;
            this.classification = classification;
        }
    }

    static final class Output {
        final File source;
        final String displayName;
        final String mimeType;

        Output(File source, String displayName, String mimeType) {
            this.source = source;
            this.displayName = displayName;
            this.mimeType = mimeType;
        }
    }

    static final class Saved {
        final Uri directory;
        final List<Uri> files;

        private Saved(Uri directory, List<Uri> files) {
            this.directory = directory;
            this.files = Collections.unmodifiableList(files);
        }
    }

    private DownloadDestination() {}

    static Intent pickerIntent() {
        return new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                .addFlags(ACCESS | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
    }

    static Snapshot snapshot(Context context) {
        synchronized (SETTINGS_LOCK) {
            SharedPreferences store = settings(context);
            Uri tree = Uri.parse(store.getString(TREE, ""));
            String classification = store.getString(CLASSIFICATION, PLATFORM_AUTHOR);
            return new Snapshot(isTree(tree) ? tree : null,
                    validClassification(classification) ? classification : PLATFORM_AUTHOR);
        }
    }

    static Uri currentTree(Context context) {
        return snapshot(context).tree;
    }

    static String classification(Context context) {
        return snapshot(context).classification;
    }

    static void select(Context context, Uri tree, int resultFlags) throws IOException {
        if (!isTree(tree)) throw new IOException("请选择有效的下载目录。");
        if ((resultFlags & ACCESS) != ACCESS) throw new IOException("所选目录没有授予读写权限。");

        ContentResolver resolver = context.getContentResolver();
        try {
            requireWritableDirectory(resolver, treeDocument(tree));
            resolver.takePersistableUriPermission(tree, ACCESS);
        } catch (RuntimeException error) {
            throw new IOException("无法保存所选目录的访问权限，请重新选择。", error);
        }
        saveTree(context, tree.toString());
    }

    static void reset(Context context) throws IOException {
        // Older downloads and queued jobs may still need their original tree grants.
        saveTree(context, null);
    }

    private static void saveTree(Context context, String value) throws IOException {
        synchronized (SETTINGS_LOCK) {
            SharedPreferences store = settings(context);
            String previous = store.getString(TREE, null);
            if (!store.edit().putString(TREE, value).commit()) {
                store.edit().putString(TREE, previous).apply();
                throw new IOException("无法保存下载目录设置。");
            }
        }
    }

    static String setClassification(Context context, String value) {
        if (!validClassification(value)) return "请选择有效的下载分类。";
        synchronized (SETTINGS_LOCK) {
            SharedPreferences store = settings(context);
            String previous = store.getString(CLASSIFICATION, null);
            if (store.edit().putString(CLASSIFICATION, value).commit()) return "";
            store.edit().putString(CLASSIFICATION, previous).apply();
            return "无法保存下载分类设置。";
        }
    }

    static List<String> folders(String classification, String platformLabel, String outputMode, String author) {
        if ("B 站".equals(platformLabel) || "YouTube".equals(platformLabel)) {
            if (PLATFORM_AUTHOR.equals(classification)) return Arrays.asList(platformLabel, authorFolder(author));
            if (PLATFORM.equals(classification)) return Collections.singletonList(platformLabel);
        }
        if (OUTPUT.equals(classification)) {
            String folder;
            switch (outputMode == null ? "" : outputMode) {
                case "audio": folder = "仅音频"; break;
                case "video-and-audio": folder = "有声视频与独立音频"; break;
                case "silent-video-and-audio": folder = "无声视频与独立音频"; break;
                default: folder = "有声视频";
            }
            return Collections.singletonList(folder);
        }
        return Collections.emptyList();
    }

    static String authorFolder(String author) {
        if (author == null) return "未知作者";
        String name = Normalizer.normalize(author, Normalizer.Form.NFC)
                .replaceAll("[\\p{Cntrl}\\p{Cf}\\\\/:*?\"<>|]+", "_")
                .replaceAll("^[\\p{Z}.]+|[\\p{Z}.]+$", "");
        if (name.isEmpty() || "NA".equals(name)) return "未知作者";
        if (name.codePointCount(0, name.length()) > 60) {
            name = name.substring(0, name.offsetByCodePoints(0, 60)).replaceAll("[\\p{Z}.]+$", "");
        }
        if (name.toUpperCase(Locale.ROOT).matches("(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\\..*)?")) name = "_" + name;
        return name;
    }

    static String mediaStorePath(String... folders) {
        StringBuilder path = new StringBuilder(Environment.DIRECTORY_DOWNLOADS).append('/').append(ROOT_DIRECTORY);
        for (String folder : folders) {
            if (!validName(folder)) throw new IllegalArgumentException("无效的下载分类目录。");
            path.append('/').append(folder);
        }
        return path.toString();
    }

    static Uri treeDocument(Uri tree) {
        return isTree(tree) ? DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree)) : null;
    }

    static String directoryLabel(Context context, Uri document) {
        if (document == null) return "下载 / " + ROOT_DIRECTORY;
        Uri uri = isTree(document) ? treeDocument(document) : document;
        try (Cursor row = context.getContentResolver().query(uri, new String[]{Document.COLUMN_DISPLAY_NAME},
                null, null, null)) {
            if (row != null && row.moveToFirst()) {
                String name = row.getString(0);
                if (name != null && !name.trim().isEmpty()) return name;
            }
        } catch (RuntimeException ignored) {
            // A removed volume or revoked grant can make the provider unavailable.
        }
        return "自选下载目录";
    }

    static Uri documentTree(Uri document) {
        if (!isContentUri(document)) return null;
        List<String> path = document.getPathSegments();
        if (path.size() != 4 || !"tree".equals(path.get(0)) || !"document".equals(path.get(2))) return null;
        return DocumentsContract.buildTreeDocumentUri(document.getAuthority(), path.get(1));
    }

    static Set<Uri> readableTrees(Context context) {
        Set<Uri> trees = new HashSet<>();
        for (UriPermission permission : context.getContentResolver().getPersistedUriPermissions()) {
            if (permission.isReadPermission() && isTree(permission.getUri())) trees.add(permission.getUri());
        }
        return trees;
    }

    static boolean hasReadAccess(Context context, Uri document) {
        Uri tree = isTree(document) ? document : documentTree(document);
        return tree != null && readableTrees(context).contains(tree);
    }

    static boolean hasWriteAccess(Context context, Uri tree) {
        if (!isTree(tree)) return false;
        for (UriPermission permission : context.getContentResolver().getPersistedUriPermissions()) {
            if (tree.equals(permission.getUri()) && permission.isReadPermission() && permission.isWritePermission()) {
                return true;
            }
        }
        return false;
    }

    static Saved save(Context context, Uri tree, List<String> folders, List<Output> outputs,
                      Runnable checkCanceled, Runnable commit) throws IOException {
        if (outputs.isEmpty()) throw new IOException("没有可保存的下载文件。");
        checkCanceled.run();
        if (!hasWriteAccess(context, tree)) throw new IOException(LOST_PERMISSION);

        for (String folder : folders) {
            if (!validName(folder)) throw new IOException("下载分类目录无效。");
        }
        for (Output output : outputs) {
            if (!output.source.isFile() || output.source.length() <= 0 || !validName(output.displayName)) {
                throw new IOException("下载文件不完整或文件名无效。");
            }
        }

        ContentResolver resolver = context.getContentResolver();
        List<Uri> created = new ArrayList<>(outputs.size());
        boolean committed = false;
        try {
            Uri directory = treeDocument(tree);
            for (String folder : folders) {
                checkCanceled.run();
                directory = childDirectory(resolver, tree, directory, folder);
            }
            byte[] buffer = new byte[64 * 1024];
            for (Output output : outputs) {
                checkCanceled.run();
                Uri document = DocumentsContract.createDocument(resolver, directory, output.mimeType, output.displayName);
                if (!tree.equals(documentTree(document)) || directory.equals(document) || created.contains(document)) {
                    throw new IOException(SAVE_FAILURE);
                }
                created.add(document);
                try (FileInputStream input = new FileInputStream(output.source);
                     OutputStream stream = resolver.openOutputStream(document, "w")) {
                    if (stream == null) throw new IOException(SAVE_FAILURE);
                    for (int count; (count = input.read(buffer)) != -1; ) {
                        checkCanceled.run();
                        stream.write(buffer, 0, count);
                    }
                }
            }
            Saved saved = new Saved(directory, created);
            checkCanceled.run();
            commit.run();
            committed = true;
            return saved;
        } catch (SecurityException error) {
            throw new IOException(LOST_PERMISSION, error);
        } catch (IllegalArgumentException | UnsupportedOperationException error) {
            throw new IOException(SAVE_FAILURE, error);
        } finally {
            if (!committed) discardCreated(resolver, created);
        }
    }

    private static Uri childDirectory(ContentResolver resolver, Uri tree, Uri parent, String folder) throws IOException {
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(parent, DocumentsContract.getDocumentId(parent));
        boolean nameInUse = false;
        try (Cursor rows = resolver.query(children, new String[]{Document.COLUMN_DOCUMENT_ID,
                Document.COLUMN_DISPLAY_NAME, Document.COLUMN_MIME_TYPE}, null, null, null)) {
            if (rows == null) throw new IOException(SAVE_FAILURE);
            while (rows.moveToNext()) {
                if (!folder.equals(rows.getString(1))) continue;
                if (Document.MIME_TYPE_DIR.equals(rows.getString(2))) {
                    String id = rows.getString(0);
                    if (id == null || id.isEmpty()) throw new IOException(SAVE_FAILURE);
                    return DocumentsContract.buildDocumentUriUsingTree(tree, id);
                }
                nameInUse = true;
            }
        }
        if (nameInUse) throw new IOException("所选下载目录内有同名文件，无法创建分类目录。");
        Uri directory = DocumentsContract.createDocument(resolver, parent, Document.MIME_TYPE_DIR, folder);
        if (!tree.equals(documentTree(directory)) || parent.equals(directory)) throw new IOException(SAVE_FAILURE);
        return directory;
    }

    private static void discardCreated(ContentResolver resolver, List<Uri> files) {
        for (int i = files.size() - 1; i >= 0; i--) {
            try {
                if (!DocumentsContract.deleteDocument(resolver, files.get(i))) {
                    Log.w("DownloadDestination", "Could not remove a partially saved document");
                }
            } catch (IOException | RuntimeException error) {
                Log.w("DownloadDestination", "Could not remove a partially saved document");
            }
        }
    }

    private static void requireWritableDirectory(ContentResolver resolver, Uri document) throws IOException {
        try (Cursor row = resolver.query(document, new String[]{Document.COLUMN_MIME_TYPE, Document.COLUMN_FLAGS},
                null, null, null)) {
            if (row != null && row.moveToFirst() && Document.MIME_TYPE_DIR.equals(row.getString(0))
                    && (row.getLong(1) & Document.FLAG_DIR_SUPPORTS_CREATE) != 0) {
                return;
            }
        }
        throw new IOException("所选目录不支持保存文件，请选择其他目录。");
    }

    private static SharedPreferences settings(Context context) {
        return context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }

    private static boolean validClassification(String value) {
        return NONE.equals(value) || PLATFORM.equals(value) || PLATFORM_AUTHOR.equals(value) || OUTPUT.equals(value);
    }

    private static boolean isTree(Uri uri) {
        if (!isContentUri(uri)) return false;
        List<String> path = uri.getPathSegments();
        return path.size() == 2 && "tree".equals(path.get(0));
    }

    private static boolean isContentUri(Uri uri) {
        return uri != null && ContentResolver.SCHEME_CONTENT.equals(uri.getScheme())
                && uri.getAuthority() != null && !uri.getAuthority().isEmpty()
                && uri.getQuery() == null && uri.getFragment() == null;
    }

    private static boolean validName(String name) {
        return name != null && !name.trim().isEmpty() && !".".equals(name) && !"..".equals(name)
                && name.indexOf('/') < 0 && name.indexOf('\\') < 0 && name.indexOf('\0') < 0;
    }
}
