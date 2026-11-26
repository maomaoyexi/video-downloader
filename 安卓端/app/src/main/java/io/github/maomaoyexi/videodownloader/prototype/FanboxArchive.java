package io.github.maomaoyexi.videodownloader.prototype;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Environment;
import android.os.SystemClock;
import android.provider.MediaStore;
import android.text.Html;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

final class FanboxArchive {
    private static final Object LOCK = new Object();
    private static final String WEB = "https://www.fanbox.cc";
    private static final String CREATOR = "[a-zA-Z0-9_][a-zA-Z0-9_-]{0,99}";
    private static final String POST_PATH = "/posts/([1-9][0-9]{0,17})/?";
    private static final Pattern WEB_POST = Pattern.compile("/@(" + CREATOR + ")" + POST_PATH);
    private static final Pattern CREATOR_HOST = Pattern.compile("(" + CREATOR + ")\\.fanbox\\.cc");
    private static final Pattern CREATOR_POST = Pattern.compile(POST_PATH);
    private static final Pattern RESERVED_HOST = Pattern.compile("www|api|downloads|static|help|fanbox");
    private static final Pattern INVALID_FILE_CHARS = Pattern.compile("[\\\\/:*?\"<>|\\p{Cntrl}\\p{Cf}]");
    private static final int MAX_METADATA_BYTES = 2 * 1024 * 1024;
    private static final int MAX_ASSETS = 60;
    private static final long MAX_FILE_BYTES = 128L * 1024 * 1024;
    private static final long MAX_POST_BYTES = 256L * 1024 * 1024;
    private static final int NETWORK_TIMEOUT_MS = 12_000;
    private static final int PREVIEW_TIMEOUT_MS = 30_000;
    private static final int ARCHIVE_TIMEOUT_MS = 300_000;

    private static Request active;
    private static Post post;
    private static String status = "idle";
    private static String detail = "";
    private static String filename = "";

    private FanboxArchive() {}

    static String inspect(Context context, String value) {
        synchronized (LOCK) {
            if (active != null) return "请等待上一次 FANBOX 操作结束。";
            post = null;
            filename = "";
            Source source;
            try {
                source = parseSource(value);
            } catch (IllegalArgumentException invalid) {
                status = "error";
                detail = "请输入 FANBOX 单篇投稿的完整链接。";
                return detail;
            }
            Request request = new Request(PREVIEW_TIMEOUT_MS);
            active = request;
            status = "loading";
            detail = "正在读取公开投稿。";
            new Thread(() -> inspectPost(request, source), "fanbox-preview").start();
        }
        return "";
    }

    static String archive(Context context) {
        synchronized (LOCK) {
            if (active != null) return "请等待上一次 FANBOX 操作结束。";
            if (post == null || !"ready".equals(status)) return "请先预览要归档的公开投稿。";
            Post selected = post;
            Request request = new Request(ARCHIVE_TIMEOUT_MS);
            active = request;
            status = "saving";
            detail = "正在生成 ZIP 归档。";
            new Thread(() -> archivePost(context, request, selected), "fanbox-archive").start();
        }
        return "";
    }

    static void cancel() {
        HttpURLConnection connection;
        synchronized (LOCK) {
            status = "idle";
            detail = "";
            filename = "";
            post = null;
            if (active == null) return;
            active.canceled = true;
            connection = active.connection;
        }
        // Closing a live socket can wait for its reader. Let the bridge return immediately.
        if (connection != null) new Thread(connection::disconnect, "fanbox-cancel").start();
    }

    static String snapshot() {
        synchronized (LOCK) {
            try {
                return new JSONObject().put("status", status)
                        .put("title", post == null ? "" : limitText(post.title, 160))
                        .put("detail", detail)
                        .put("preview", post == null ? "" : limitText(post.body, 800))
                        .put("files", post == null ? 0 : post.assets.size())
                        .put("filename", filename).toString();
            } catch (JSONException impossible) {
                throw new IllegalStateException(impossible);
            }
        }
    }

    private static void inspectPost(Request request, Source source) {
        try {
            URI endpoint = URI.create("https://api.fanbox.cc/post.info?postId=" + source.id);
            Post loaded;
            HttpURLConnection connection = connect(request, endpoint, true);
            try (InputStream input = connection.getInputStream();
                 ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                copy(request, input, output, MAX_METADATA_BYTES);
                loaded = parsePost(source, new JSONObject(output.toString(StandardCharsets.UTF_8.name())));
            } finally {
                closeConnection(request, connection);
            }
            synchronized (LOCK) {
                request.check();
                post = loaded;
                status = "ready";
                detail = loaded.skipped == 0 ? "确认后将保存正文和可下载的图片、附件。"
                        : "确认后将保存正文和可下载的文件。有 " + loaded.skipped + " 个资源不可直接归档。";
                active = null;
            }
        } catch (ArchiveError error) {
            fail(request, error.getMessage());
        } catch (JSONException error) {
            fail(request, "FANBOX 返回的投稿资料无法读取。");
        } catch (IOException | RuntimeException error) {
            fail(request, "无法读取 FANBOX 投稿，请检查网络后重试。");
        } finally {
            finish(request);
        }
    }

    private static void archivePost(Context context, Request request, Post selected) {
        ContentResolver resolver = context.getContentResolver();
        Uri pending = null;
        boolean published = false;
        try {
            request.check();
            String displayName = "FANBOX " + safeName(selected.title, "投稿", 45) + " [" + selected.source.id + "].zip";
            ContentValues values = new ContentValues();
            values.put(MediaStore.Downloads.DISPLAY_NAME, displayName);
            values.put(MediaStore.Downloads.MIME_TYPE, "application/zip");
            values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/多平台下载/FANBOX");
            values.put(MediaStore.Downloads.IS_PENDING, 1);
            pending = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (pending == null) throw new ArchiveError("无法写入手机的下载目录。");
            try (OutputStream output = resolver.openOutputStream(pending, "w")) {
                if (output == null) throw new ArchiveError("无法写入手机的下载目录。");
                writeZip(request, selected, output);
            }
            synchronized (LOCK) {
                request.check();
                values.clear();
                values.put(MediaStore.Downloads.IS_PENDING, 0);
                if (resolver.update(pending, values, null, null) != 1) {
                    throw new ArchiveError("无法确认归档已经保存。");
                }
                published = true;
                filename = publishedName(resolver, pending, displayName);
                status = "saved";
                detail = "已保存到「下载 / 多平台下载 / FANBOX」。";
                active = null;
            }
        } catch (ArchiveError error) {
            fail(request, error.getMessage());
        } catch (IOException | RuntimeException error) {
            fail(request, "归档未能保存，请检查网络和手机剩余空间后重试。");
        } finally {
            if (!published && pending != null) {
                try {
                    resolver.delete(pending, null, null);
                } catch (RuntimeException ignored) {
                    // An unpublished MediaStore item remains hidden and is eligible for expiration.
                }
            }
            finish(request);
        }
    }

    private static String publishedName(ContentResolver resolver, Uri uri, String fallback) {
        try (Cursor row = resolver.query(uri, new String[]{MediaStore.Downloads.DISPLAY_NAME}, null, null, null)) {
            if (row != null && row.moveToFirst() && row.getString(0) != null) return row.getString(0);
        } catch (RuntimeException ignored) {
            // Filename lookup cannot undo a published archive.
        }
        return fallback;
    }

    private static void writeZip(Request request, Post post, OutputStream output) throws IOException {
        try (ZipOutputStream zip = new ZipOutputStream(output, StandardCharsets.UTF_8)) {
            zip.putNextEntry(new ZipEntry("正文.txt"));
            String text = post.title + "\n" + post.source.canonicalUrl() + "\n\n" + post.body;
            zip.write(text.getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
            long remaining = MAX_POST_BYTES;
            int index = 0;
            for (Asset asset : post.assets.values()) {
                synchronized (LOCK) {
                    request.check();
                    detail = "正在保存文件 " + (++index) + " / " + post.assets.size() + "。";
                }
                remaining -= writeAsset(request, asset, zip, Math.min(MAX_FILE_BYTES, remaining));
            }
        }
    }

    private static long writeAsset(Request request, Asset asset, ZipOutputStream zip, long limit) throws IOException {
        if (limit == 0 || asset.size > limit) throw new ArchiveError("投稿文件超过单次归档的大小上限。");
        HttpURLConnection connection = connect(request, asset.url, false);
        try {
            long advertised = connection.getContentLengthLong();
            if (advertised > limit) throw new ArchiveError("投稿文件超过单次归档的大小上限。");
            String mime = connection.getContentType();
            if (mime != null && mime.toLowerCase(Locale.ROOT).contains("text/html")
                    && !asset.name.toLowerCase(Locale.ROOT).matches(".*\\.html?")) {
                throw new ArchiveError("附件地址未返回可保存的文件。");
            }
            try (InputStream input = connection.getInputStream()) {
                zip.putNextEntry(new ZipEntry(asset.name));
                long size = copy(request, input, zip, limit);
                if (size == 0 || (advertised >= 0 && size != advertised) || (asset.size > 0 && size != asset.size)) {
                    throw new ArchiveError("投稿文件下载不完整。");
                }
                zip.closeEntry();
                return size;
            }
        } finally {
            closeConnection(request, connection);
        }
    }

    private static HttpURLConnection connect(Request request, URI uri, boolean api) throws IOException {
        for (int redirects = 0; redirects <= 3; redirects++) {
            int timeout = request.timeout();
            HttpURLConnection connection = (HttpURLConnection) uri.toURL().openConnection();
            request.connection = connection;
            boolean opened = false;
            try {
                request.check();
                connection.setConnectTimeout(timeout);
                connection.setReadTimeout(timeout);
                connection.setInstanceFollowRedirects(false);
                connection.setUseCaches(false);
                connection.setRequestProperty("Origin", WEB);
                connection.setRequestProperty("Referer", WEB + "/");
                connection.setRequestProperty("Accept", api ? "application/json" : "*/*");
                connection.setRequestProperty("Accept-Encoding", "identity");
                int response = connection.getResponseCode();
                if (response == HttpURLConnection.HTTP_OK) {
                    String mime = connection.getContentType();
                    if (api && (mime == null || !mime.toLowerCase(Locale.ROOT).contains("json"))) {
                        throw new ArchiveError("FANBOX 未返回投稿资料，可能需要浏览器验证。");
                    }
                    opened = true;
                    return connection;
                }
                if (response == 401 || response == 403) {
                    throw new ArchiveError("FANBOX 拒绝匿名访问，投稿或文件可能需要登录、验证或赞助。");
                }
                if (response == 429) throw new ArchiveError("FANBOX 暂时限制了请求，请稍后再试。");
                if (response == 404) throw new ArchiveError("投稿或文件不存在，或当前不可公开访问。");
                if (api || response < 300 || response >= 400 || redirects == 3) {
                    throw new ArchiveError("FANBOX 未提供可读取的内容（HTTP " + response + "）。");
                }
                String location = connection.getHeaderField("Location");
                try {
                    if (location == null) throw new IllegalArgumentException();
                    uri = resourceUrl(uri.resolve(location).toString());
                    if (uri == null) throw new IllegalArgumentException();
                } catch (IllegalArgumentException invalid) {
                    throw new ArchiveError("投稿文件重定向到未知地址，已停止归档。");
                }
            } finally {
                if (!opened) closeConnection(request, connection);
            }
        }
        throw new ArchiveError("投稿文件重定向次数过多。");
    }

    private static void closeConnection(Request request, HttpURLConnection connection) {
        request.connection = null;
        connection.disconnect();
    }

    private static long copy(Request request, InputStream input, OutputStream output, long limit) throws IOException {
        byte[] buffer = new byte[32 * 1024];
        long size = 0;
        while (true) {
            request.check();
            int count = input.read(buffer);
            if (count == -1) return size;
            if (count > limit - size) throw new ArchiveError("投稿内容超过单次归档的大小上限。");
            output.write(buffer, 0, count);
            size += count;
        }
    }

    private static void fail(Request request, String message) {
        synchronized (LOCK) {
            if (request.canceled) return;
            status = "error";
            detail = message;
        }
    }

    private static void finish(Request request) {
        synchronized (LOCK) {
            if (active == request) active = null;
        }
    }

    static Source parseSource(String value) {
        if (value == null || value.length() > 2048) throw new IllegalArgumentException();
        URI uri = URI.create(value.trim());
        String scheme = uri.getScheme();
        boolean secure = "https".equalsIgnoreCase(scheme);
        String authority = uri.getRawAuthority();
        String path = uri.getRawPath();
        if ((!secure && !"http".equalsIgnoreCase(scheme)) || authority == null || path == null) {
            throw new IllegalArgumentException();
        }
        String host = authority.toLowerCase(Locale.ROOT).replaceFirst(secure ? ":443$" : ":80$", "");
        if ("www.fanbox.cc".equals(host) || "fanbox.cc".equals(host)) {
            Matcher post = WEB_POST.matcher(path);
            if (post.matches()) return new Source(post.group(1).toLowerCase(Locale.ROOT), post.group(2));
        } else {
            Matcher creator = CREATOR_HOST.matcher(host);
            Matcher post = CREATOR_POST.matcher(path);
            if (creator.matches() && !RESERVED_HOST.matcher(creator.group(1)).matches() && post.matches()) {
                return new Source(creator.group(1), post.group(1));
            }
        }
        throw new IllegalArgumentException();
    }

    static Post parsePost(Source source, JSONObject result) throws JSONException, IOException {
        JSONObject payload = result.getJSONObject("body");
        JSONObject item = payload.has("post") ? payload.getJSONObject("post") : payload;
        if (!source.id.equals(item.optString("id")) || !source.creator.equalsIgnoreCase(item.optString("creatorId"))) {
            throw new ArchiveError("FANBOX 返回的投稿与输入链接不一致。");
        }
        Object fee = item.opt("feeRequired");
        JSONObject body = item.optJSONObject("body");
        if (!(fee instanceof Number) || ((Number) fee).doubleValue() != 0 || body == null
                || (item.has("isRestricted") && !Boolean.FALSE.equals(item.opt("isRestricted")))) {
            throw new ArchiveError("该投稿无法公开读取。首版支持匿名可见的免费投稿。");
        }
        String title = item.getString("title").trim();
        Post post = new Post(source, title.isEmpty() ? "FANBOX 投稿 " + source.id : title);
        StringBuilder text = new StringBuilder();
        String type = item.getString("type");
        switch (type) {
            case "article":
                JSONArray blocks = body.getJSONArray("blocks");
                for (int i = 0; i < blocks.length(); i++) {
                    JSONObject block = blocks.getJSONObject(i);
                    String kind = block.getString("type");
                    if ("p".equals(kind) || "header".equals(kind)) {
                        text.append(block.optString("text", "")).append("\n\n");
                    } else if ("image".equals(kind) || "file".equals(kind)) {
                        JSONObject map = body.optJSONObject(kind + "Map");
                        String id = block.optString(kind + "Id");
                        appendAsset(post, text, map == null ? null : map.optJSONObject(id), "image".equals(kind));
                    }
                }
                break;
            case "entry":
                text.append(Html.fromHtml(body.getString("html"), Html.FROM_HTML_MODE_LEGACY, src -> {
                    post.addAsset(src, "", -1, true);
                    return null;
                }, null).toString().replace("\uFFFC", ""));
                break;
            case "image":
            case "file":
            case "text":
            case "video":
                text.append(body.optString("text", ""));
                JSONArray files = "image".equals(type) ? body.getJSONArray("images")
                        : "file".equals(type) ? body.getJSONArray("files") : null;
                if (files != null) {
                    text.append("\n\n");
                    boolean images = "image".equals(type);
                    for (int i = 0; i < files.length(); i++) appendAsset(post, text, files.optJSONObject(i), images);
                }
                break;
            default:
                throw new ArchiveError("暂不支持这一类 FANBOX 投稿。");
        }
        post.body = text.toString().trim();
        if (post.body.isEmpty() && post.assets.isEmpty()) throw new ArchiveError("这篇公开投稿没有可保存的正文、图片或附件。");
        return post;
    }

    private static void appendAsset(Post post, StringBuilder text, JSONObject data, boolean image) {
        Asset asset = data == null ? null : post.addAsset(data.optString(image ? "originalUrl" : "url"),
                data.optString("name"), data.optLong("size", -1), image);
        if (data == null) post.skipped++;
        if (asset != null) text.append('〔').append(asset.name).append("〕\n\n");
    }

    private static URI resourceUrl(String value) {
        try {
            URI uri = URI.create(value);
            String host = uri.getHost();
            if (!"https".equalsIgnoreCase(uri.getScheme()) || host == null || uri.getUserInfo() != null
                    || (uri.getPort() != -1 && uri.getPort() != 443) || uri.getRawFragment() != null) return null;
            host = host.toLowerCase(Locale.ROOT);
            return host.equals("downloads.fanbox.cc") || host.equals("fanbox.pixiv.net")
                    || host.equals("pximg.net") || host.endsWith(".pximg.net") ? uri : null;
        } catch (IllegalArgumentException invalid) {
            return null;
        }
    }

    private static String safeName(String name, String fallback, int maxCodePoints) {
        String cleaned = INVALID_FILE_CHARS.matcher(name).replaceAll("_").trim().replaceAll("^[. ]+|[. ]+$", "");
        return cleaned.isEmpty() ? fallback : limitText(cleaned, maxCodePoints).trim();
    }

    private static String limitText(String text, int maxCodePoints) {
        int count = text.codePointCount(0, text.length());
        return count > maxCodePoints ? text.substring(0, text.offsetByCodePoints(0, maxCodePoints)) : text;
    }

    static final class Source {
        final String creator;
        final String id;

        Source(String creator, String id) {
            this.creator = creator;
            this.id = id;
        }

        String canonicalUrl() {
            return WEB + "/@" + creator + "/posts/" + id;
        }
    }

    static final class Post {
        final Source source;
        final String title;
        final Map<URI, Asset> assets = new LinkedHashMap<>();
        String body;
        int skipped;

        Post(Source source, String title) {
            this.source = source;
            this.title = title;
        }

        private Asset addAsset(String value, String originalName, long size, boolean image) {
            URI url = resourceUrl(value);
            if (url != null && assets.containsKey(url)) return assets.get(url);
            if (url == null || assets.size() >= MAX_ASSETS || size > MAX_FILE_BYTES) {
                skipped++;
                return null;
            }
            String path = url.getPath();
            String leaf = path.substring(path.lastIndexOf('/') + 1);
            String extension = leaf.contains(".") ? leaf.substring(leaf.lastIndexOf('.') + 1) : "";
            if (!extension.matches("[A-Za-z0-9]{1,10}")) extension = "";
            String name = safeName(originalName, image ? "图片" : "附件", 48);
            if (!extension.isEmpty() && !name.toLowerCase(Locale.ROOT).endsWith("." + extension.toLowerCase(Locale.ROOT))) {
                name += "." + extension;
            }
            String entryName = (image ? "图片/" : "附件/") + (assets.size() + 1) + "-" + name;
            Asset asset = new Asset(url, entryName, size);
            assets.put(url, asset);
            return asset;
        }
    }

    private static final class Asset {
        final URI url;
        final String name;
        final long size;

        Asset(URI url, String name, long size) {
            this.url = url;
            this.name = name;
            this.size = size;
        }
    }

    private static final class Request {
        final long deadline;
        volatile boolean canceled;
        volatile HttpURLConnection connection;

        Request(int timeout) {
            deadline = SystemClock.elapsedRealtime() + timeout;
        }

        int timeout() throws ArchiveError {
            check();
            return (int) Math.max(1, Math.min(NETWORK_TIMEOUT_MS, deadline - SystemClock.elapsedRealtime()));
        }

        void check() throws ArchiveError {
            if (canceled) throw new ArchiveError("已取消。");
            if (SystemClock.elapsedRealtime() >= deadline) throw new ArchiveError("FANBOX 操作超时，请重试。");
        }
    }

    private static final class ArchiveError extends IOException {
        ArchiveError(String message) {
            super(message);
        }
    }
}
