package io.github.maomaoyexi.videodownloader.prototype;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.content.res.AssetFileDescriptor;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.PowerManager;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;
import android.provider.DocumentsContract;
import android.provider.MediaStore;
import android.provider.Settings;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import io.github.maomaoyexi.videodownloader.prototype.PlatformCookies.Platform;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public final class MainActivity extends Activity {
    private static final int REQUEST_NOTIFICATIONS = 1;
    private static final int PICK_COOKIES = 2;
    private static final int PICK_LINKS = 3;
    private static final int PICK_DOWNLOAD_DIRECTORY = 4;
    private static final String LINKS_PICKER_OPEN = "linksPickerOpen";
    private static final String DOWNLOAD_DEFAULTS = "download_defaults";
    private static final String DOWNLOAD_PRESETS = "download_presets";
    private static final String PRESET_ENTRIES = "presets";
    private static final Object DOWNLOAD_PRESETS_LOCK = new Object();
    private static final String AGREEMENT_PREFERENCES = "usage_agreement";
    private static final String ACCEPTED_AGREEMENT_VERSION = "accepted_version";
    private static final int AGREEMENT_VERSION = 1;
    private static final String BATTERY_SETUP_HANDLED = "battery_setup_handled";
    private static final String HEIGHT = "height";
    private static final String SUBTITLES = "subtitles";
    private static final String RATE_LIMIT = "rateLimitKiB";
    private static final String VIDEO_CONTAINER = "videoContainer";
    private static final String VIDEO_CODEC = "videoCodec";
    private static final String OUTPUT_MODE = "outputMode";
    private static final String AUDIO_FORMAT = "audioFormat";
    private static final String COVER = "cover";
    private static final String FRAGMENTS = "fragments";
    private static final String COOKIE_PICKER_TOKEN = "cookiePickerToken";
    private static final String COOKIE_PICKER_PLATFORM = "cookiePickerPlatform";
    private static final String EXTERNAL_STORAGE_DOCUMENTS = "com.android.externalstorage.documents";
    private static final String[] DIRECTORY_TYPES = {DocumentsContract.Document.MIME_TYPE_DIR, "resource/folder"};
    private static final String MT_MANAGER_PACKAGE = "bin.mt.plus";
    private static final String MT_LOCATE_ACTIVITY = MT_MANAGER_PACKAGE + ".OpenFileActivity";
    private static final Uri PROJECT_PAGE = Uri.parse("https://github.com/maomaoyexi/video-downloader");
    private WebView page;
    private boolean startupPageLoaded;
    private boolean notificationPermissionPending;
    private AlertDialog batterySetupDialog;
    private volatile String destinationMessage = "";
    private volatile String destinationLabel = "";
    private volatile Uri labeledDestination;
    private Platform cookiePickerPlatform;
    private String cookiePickerToken;
    private boolean linksPickerOpen;
    private boolean readingLinks;
    private long linksRevision;
    private String importedLinks = "";
    private String linksMessage = "";
    private boolean checkingAppUpdate;
    private AppUpdates.Release availableAppUpdate;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        DownloadService.cleanStaleCookieFiles(this);
        if (state != null) {
            linksPickerOpen = state.getBoolean(LINKS_PICKER_OPEN);
            String token = state.getString(COOKIE_PICKER_TOKEN);
            Platform platform = Platform.fromId(state.getString(COOKIE_PICKER_PLATFORM));
            if (token != null && platform != null && DownloadService.beginCookiePicker(platform, token)) {
                cookiePickerToken = token;
                cookiePickerPlatform = platform;
            }
        }
        getWindow().setStatusBarColor(Color.rgb(247, 247, 245));
        getWindow().setNavigationBarColor(Color.rgb(247, 247, 245));
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);

        page = new WebView(this);
        page.getSettings().setJavaScriptEnabled(true);
        page.getSettings().setAllowFileAccess(false);
        page.getSettings().setAllowContentAccess(false);
        page.getSettings().setBlockNetworkLoads(true);
        page.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                startupPageLoaded = true;
                maybeShowBatterySetup();
            }
        });
        page.addJavascriptInterface(new Bridge(), "Downloader");
        setContentView(page);
        page.loadUrl("file:///android_asset/index.html");

        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationPermissionPending = true;
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQUEST_NOTIFICATIONS);
        }
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) maybeShowBatterySetup();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_NOTIFICATIONS) {
            notificationPermissionPending = false;
            maybeShowBatterySetup();
        }
    }

    private boolean hasAcceptedAgreement() {
        SharedPreferences agreement = getSharedPreferences(AGREEMENT_PREFERENCES, MODE_PRIVATE);
        return agreement.getInt(ACCEPTED_AGREEMENT_VERSION, 0) == AGREEMENT_VERSION;
    }

    private void maybeShowBatterySetup() {
        if (!startupPageLoaded || notificationPermissionPending || batterySetupDialog != null
                || !hasWindowFocus() || isFinishing() || isDestroyed() || !hasAcceptedAgreement()) return;

        SharedPreferences onboarding = getSharedPreferences("onboarding", MODE_PRIVATE);
        if (onboarding.getBoolean(BATTERY_SETUP_HANDLED, false)) return;
        Runnable recordChoice = () -> onboarding.edit().putBoolean(BATTERY_SETUP_HANDLED, true).apply();
        PowerManager power = getSystemService(PowerManager.class);
        if (power != null && power.isIgnoringBatteryOptimizations(getPackageName())) {
            recordChoice.run();
            return;
        }

        batterySetupDialog = new AlertDialog.Builder(this)
                .setTitle("允许后台下载")
                .setMessage("允许应用在后台运行，可减少息屏或切到后台时的下载中断。"
                        + "如果手机还有单独的省电策略，请在「应用信息」的电池设置中选择「无限制」。")
                .setPositiveButton("去设置", (dialog, which) -> {
                    recordChoice.run();
                    openBatterySettings(true);
                })
                .setNeutralButton("应用信息", (dialog, which) -> {
                    recordChoice.run();
                    openBatterySettings(false);
                })
                .setNegativeButton("暂不设置", (dialog, which) -> recordChoice.run())
                .setOnCancelListener(dialog -> recordChoice.run())
                .show();
    }

    private void openBatterySettings(boolean requestExemption) {
        Uri app = Uri.fromParts("package", getPackageName(), null);
        if (requestExemption && launchSettings(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, app))) {
            return;
        }
        if (launchSettings(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, app))) return;
        if (launchSettings(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))) return;
        Toast.makeText(this, "请在系统设置的应用信息中检查本应用的电池设置。", Toast.LENGTH_LONG).show();
    }

    private boolean launchSettings(Intent intent) {
        try {
            startActivity(intent);
            return true;
        } catch (ActivityNotFoundException | SecurityException error) {
            return false;
        }
    }

    @Override
    public void onBackPressed() {
        if (page.canGoBack()) page.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state);
        synchronized (this) {
            state.putBoolean(LINKS_PICKER_OPEN, linksPickerOpen);
        }
        if (cookiePickerToken != null) {
            state.putString(COOKIE_PICKER_TOKEN, cookiePickerToken);
            state.putString(COOKIE_PICKER_PLATFORM, cookiePickerPlatform.id);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == PICK_DOWNLOAD_DIRECTORY) {
            if (resultCode == RESULT_OK && data != null) {
                Uri destination = data.getData();
                int flags = data.getFlags();
                new Thread(() -> {
                    try {
                        DownloadDestination.select(getApplicationContext(), destination, flags);
                        updateDestinationLabel(destination);
                        destinationMessage = "已更改下载目录。";
                    } catch (IOException | RuntimeException error) {
                        destinationMessage = "无法取得所选目录的写入权限，请选择其他目录。";
                    }
                }, "download-directory").start();
            }
            return;
        }
        if (requestCode == PICK_LINKS) {
            receiveLinkDocument(resultCode, data);
            return;
        }
        if (requestCode != PICK_COOKIES || cookiePickerToken == null) return;
        if (resultCode != RESULT_OK) {
            closeCookiePicker("");
            return;
        }
        Uri document = data == null ? null : data.getData();
        if (document == null || !"content".equals(document.getScheme())) {
            closeCookiePicker("无法打开选中的 Cookie 文件，请重新选择。");
            return;
        }
        DownloadService.changeCookies(getApplicationContext(), cookiePickerPlatform, document, cookiePickerToken);
        cookiePickerPlatform = null;
        cookiePickerToken = null;
    }

    private void closeCookiePicker(String message) {
        if (cookiePickerToken == null) return;
        DownloadService.closeCookiePicker(cookiePickerPlatform, cookiePickerToken, message);
        cookiePickerPlatform = null;
        cookiePickerToken = null;
    }

    private void pickCookies(Platform platform) {
        if (linksPickerOpen || readingLinks) return;
        String token = UUID.randomUUID().toString();
        if (!DownloadService.beginCookiePicker(platform, token)) return;
        cookiePickerPlatform = platform;
        cookiePickerToken = token;
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE)
                .setType("*/*")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivityForResult(picker, PICK_COOKIES);
        } catch (ActivityNotFoundException | SecurityException error) {
            closeCookiePicker("无法打开系统文件选择器。");
        }
    }

    private synchronized void pickLinkDocument() {
        if (linksPickerOpen || readingLinks || cookiePickerToken != null) return;
        linksPickerOpen = true;
        importedLinks = "";
        linksMessage = "";
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE)
                .setType("text/plain")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivityForResult(picker, PICK_LINKS);
        } catch (ActivityNotFoundException | SecurityException error) {
            finishLinkImport("", "无法打开系统文件选择器。");
        }
    }

    private synchronized void receiveLinkDocument(int resultCode, Intent data) {
        if (!linksPickerOpen) return;
        linksPickerOpen = false;
        if (resultCode != RESULT_OK) {
            finishLinkImport("", "");
            return;
        }
        Uri document = data == null ? null : data.getData();
        if (document == null || !"content".equals(document.getScheme())) {
            finishLinkImport("", "无法打开选中的 TXT 文件。");
            return;
        }
        readingLinks = true;
        new Thread(() -> {
            try (InputStream input = getContentResolver().openInputStream(document)) {
                if (input == null) throw new FileNotFoundException();
                String links = LinkTextImport.read(input);
                finishLinkImport(links, "");
            } catch (LinkTextImport.InvalidText error) {
                finishLinkImport("", error.getMessage());
            } catch (IOException | RuntimeException error) {
                finishLinkImport("", "无法读取选中的 TXT 文件。");
            }
        }, "import-links").start();
    }

    private synchronized void finishLinkImport(String text, String message) {
        linksPickerOpen = false;
        readingLinks = false;
        importedLinks = text;
        linksMessage = message;
        linksRevision++;
    }

    private synchronized String linkImportState() {
        try {
            return new JSONObject().put("revision", linksRevision).put("busy", linksPickerOpen || readingLinks)
                    .put("text", importedLinks).put("message", linksMessage).toString();
        } catch (JSONException error) {
            throw new IllegalStateException(error);
        }
    }

    private String savedMediaError(Uri media) {
        try (AssetFileDescriptor descriptor = getContentResolver().openAssetFileDescriptor(media, "r")) {
            if (descriptor == null) throw new IOException();
        } catch (FileNotFoundException error) {
            return "下载文件已删除或已移动，可在下载目录中确认。";
        } catch (IOException | RuntimeException error) {
            return "无法读取下载文件，请在下载目录中确认文件还在。";
        }
        return "";
    }

    private String openSavedMedia(Uri media) {
        String message = savedMediaError(media);
        if (!message.isEmpty()) return message;
        String type = savedMediaType(media);
        runOnUiThread(() -> {
            try {
                startActivity(savedMediaIntent(media, type));
            } catch (ActivityNotFoundException | SecurityException error) {
                Toast.makeText(MainActivity.this,
                        "无法打开播放器，可从下载目录打开文件。", Toast.LENGTH_SHORT).show();
            }
        });
        return "";
    }

    private String savedMediaType(Uri media) {
        try {
            String type = getContentResolver().getType(media);
            if (type != null && (type.startsWith("audio/") || type.startsWith("video/"))) return type;
        } catch (RuntimeException ignored) {
            // Fall back to the original MediaStore metadata query.
        }
        try (Cursor row = getContentResolver().query(media,
                new String[]{MediaStore.MediaColumns.MIME_TYPE}, null, null, null)) {
            if (row != null && row.moveToFirst()) return playbackType(row.getString(0));
        } catch (RuntimeException ignored) {
            // Legacy video records are still playable when metadata is unavailable.
        }
        return "video/mp4";
    }

    private static String playbackType(String type) {
        return type != null && (type.startsWith("audio/") || type.startsWith("video/")) ? type : "video/mp4";
    }

    private static Intent savedMediaIntent(Uri media, String type) {
        return new Intent(Intent.ACTION_VIEW)
                .setDataAndType(media, type)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
    }

    private String openSavedMediaLocation(Uri media, Uri directory) {
        String message = savedMediaError(media);
        if (!message.isEmpty()) return message;
        if (directory != null) {
            String type = savedMediaType(media);
            String label = DownloadDestination.directoryLabel(this, directory);
            runOnUiThread(() -> browseMediaDirectory(media, type, directory, label));
            return "";
        }
        try (Cursor row = getContentResolver().query(media,
                new String[]{MediaStore.MediaColumns.RELATIVE_PATH, MediaStore.MediaColumns.VOLUME_NAME,
                        MediaStore.MediaColumns.MIME_TYPE},
                null, null, null)) {
            if (row != null && row.moveToFirst()) {
                String relativePath = row.getString(0);
                String root = documentRoot(row.getString(1));
                if (relativePath != null && root != null) {
                    String path = relativePath.replaceFirst("/+$", "");
                    Uri mediaDirectory = DocumentsContract.buildDocumentUri(EXTERNAL_STORAGE_DOCUMENTS, root + ":" + path);
                    String type = playbackType(row.getString(2));
                    runOnUiThread(() -> browseMediaDirectory(media, type, mediaDirectory, path));
                    return "";
                }
            }
        } catch (RuntimeException error) {
            return "无法读取文件所在目录。";
        }
        return "找不到文件所在目录。";
    }

    private String documentRoot(String volumeName) {
        if (MediaStore.VOLUME_EXTERNAL_PRIMARY.equals(volumeName)) return "primary";
        StorageManager storage = getSystemService(StorageManager.class);
        if (storage == null || volumeName == null) return null;
        for (StorageVolume volume : storage.getStorageVolumes()) {
            if (volumeName.equalsIgnoreCase(volume.getUuid())) return volume.getUuid();
        }
        return null;
    }

    private void browseMediaDirectory(Uri media, String mediaType, Uri directory, String path) {
        PackageManager packages = getPackageManager();
        Map<String, Intent> candidates = new LinkedHashMap<>();
        if (media != null) addMtLocator(packages, candidates, media, mediaType);
        for (String type : DIRECTORY_TYPES) {
            // FilesActivity restores the old navigation stack when its document task is reused.
            Intent browse = new Intent(Intent.ACTION_VIEW).setDataAndType(directory, type)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_DOCUMENT | Intent.FLAG_ACTIVITY_MULTIPLE_TASK
                            | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS);
            if (DocumentsContract.isTreeUri(directory)) browse.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            for (ResolveInfo match : packages.queryIntentActivities(browse,
                    PackageManager.MATCH_DEFAULT_ONLY | PackageManager.GET_RESOLVED_FILTER)) {
                if (match.activityInfo == null || !match.activityInfo.exported || !supportsDirectory(match.filter, type)) {
                    continue;
                }
                String app = match.activityInfo.packageName;
                candidates.putIfAbsent(app, new Intent(browse).setClassName(app, match.activityInfo.name));
            }
        }
        if (candidates.isEmpty()) {
            openVideoDirectoryPicker(directory, path);
            return;
        }
        List<Intent> options = new ArrayList<>(candidates.values());
        Intent first = options.get(0);
        if (options.size() > 1) {
            Intent chooser = Intent.createChooser(first, "打开方式")
                    .putExtra(Intent.EXTRA_ALTERNATE_INTENTS, options.subList(1, options.size()).toArray(new Intent[0]));
            launchVideoLocation(chooser, directory, path);
            return;
        }
        // Some system choosers immediately launch a single handler. Keep the user's choice explicit.
        ResolveInfo only = packages.resolveActivity(first, 0);
        CharSequence label = only == null ? "打开文件夹" : only.activityInfo.applicationInfo.loadLabel(packages);
        new AlertDialog.Builder(this)
                .setTitle("打开方式")
                .setItems(new CharSequence[]{label}, (dialog, index) -> launchVideoLocation(first, directory, path))
                .setNegativeButton("取消", null)
                .show();
    }

    private static void addMtLocator(PackageManager packages, Map<String, Intent> candidates, Uri media, String mediaType) {
        // MT's locate entry takes the file URI. Its player uses a separate activity.
        Intent locate = savedMediaIntent(media, mediaType).setPackage(MT_MANAGER_PACKAGE);
        for (ResolveInfo match : packages.queryIntentActivities(locate, PackageManager.MATCH_DEFAULT_ONLY)) {
            if (match.activityInfo != null && match.activityInfo.exported
                    && MT_LOCATE_ACTIVITY.equals(match.activityInfo.name)) {
                candidates.put(MT_MANAGER_PACKAGE, locate.setClassName(MT_MANAGER_PACKAGE, MT_LOCATE_ACTIVITY));
                return;
            }
        }
    }

    private void browseDownloadDirectory() {
        Uri tree = DownloadDestination.currentTree(this);
        if (tree != null) {
            try {
                browseMediaDirectory(null, null, DownloadDestination.treeDocument(tree), "自选下载目录");
            } catch (RuntimeException error) {
                Toast.makeText(this, "无法打开自选下载目录，请在设置中重新选择。", Toast.LENGTH_SHORT).show();
            }
            return;
        }
        String downloads = Environment.DIRECTORY_DOWNLOADS;
        File folder = new File(Environment.getExternalStoragePublicDirectory(downloads), "多平台下载");
        String path = folder.isDirectory() ? downloads + "/多平台下载" : downloads;
        Uri directory = DocumentsContract.buildDocumentUri(EXTERNAL_STORAGE_DOCUMENTS, "primary:" + path);
        browseMediaDirectory(null, null, directory, path);
    }

    private void updateDestinationLabel(Uri tree) {
        String label = DownloadDestination.directoryLabel(getApplicationContext(), DownloadDestination.treeDocument(tree));
        destinationLabel = label == null || label.isEmpty() ? "自选下载目录" : label;
        labeledDestination = tree;
    }

    private static boolean supportsDirectory(IntentFilter filter, String type) {
        // Wildcard MIME filters also match directory VIEW, including apps that only open files.
        if (filter == null) return false;
        for (int index = 0; index < filter.countDataTypes(); index++) {
            if (type.equals(filter.getDataType(index))) return true;
        }
        return false;
    }

    private void launchVideoLocation(Intent intent, Uri directory, String path) {
        try {
            startActivity(intent);
        } catch (ActivityNotFoundException | SecurityException error) {
            openVideoDirectoryPicker(directory, path);
        }
    }

    private void openVideoDirectoryPicker(Uri directory, String path) {
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE)
                .setType("*/*")
                .putExtra(DocumentsContract.EXTRA_INITIAL_URI, directory);
        try {
            startActivity(picker);
        } catch (ActivityNotFoundException | SecurityException error) {
            String folder = path.isEmpty() ? "存储根目录" : "「" + path + "」";
            Toast.makeText(this, "无法打开系统文件管理器，请手动查看" + folder + "。", Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onDestroy() {
        if (batterySetupDialog != null) batterySetupDialog.dismiss();
        closeCookiePicker("");
        DownloadService.cancelCollection();
        page.removeJavascriptInterface("Downloader");
        page.destroy();
        super.onDestroy();
    }

    private static String validateDownloadOptions(int height, int rateLimitKiB,
                                                  String videoCodec, int fragments, String outputMode, String audioFormat) {
        if (!DownloadService.validResolution(height)) return "请选择有效的下载档位。";
        if (rateLimitKiB < 0 || rateLimitKiB > DownloadService.MAX_RATE_LIMIT_KIB) {
            return "请输入 0–102400 之间的整数限速。";
        }
        if (!DownloadService.validVideoCodec(videoCodec)) return "请选择有效的视频编码。";
        if (!DownloadService.validOutputMode(outputMode)) return "请选择有效的音画输出模式。";
        if (MediaTracks.AudioFormat.fromId(audioFormat) == null) return "请选择有效的音频格式。";
        if (!DownloadService.validFragments(fragments)) return "分片并发请输入 1–16 之间的整数。";
        return "";
    }

    private static String validatedPresetName(String input) {
        if (input == null) return null;
        String name = input.trim();
        return name.isEmpty() || name.length() > 40 ? null : name;
    }

    private static int downloadPresetIndex(JSONArray presets, String name) {
        for (int i = 0; i < presets.length(); i++) {
            JSONObject preset = presets.optJSONObject(i);
            if (preset != null && name.equals(preset.optString("name"))) return i;
        }
        return -1;
    }

    private static boolean writeDownloadPresets(SharedPreferences store, String previous, JSONArray presets) {
        if (store.edit().putString(PRESET_ENTRIES, presets.toString()).commit()) return true;
        // A failed commit can still change the in-memory value.
        store.edit().putString(PRESET_ENTRIES, previous).apply();
        return false;
    }

    private void checkAppUpdate() {
        if (checkingAppUpdate || isFinishing() || isDestroyed()) return;
        checkingAppUpdate = true;
        availableAppUpdate = null;
        new Thread(() -> {
            AppUpdates.Result result;
            try {
                String version = getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
                result = AppUpdates.check(version);
            } catch (PackageManager.NameNotFoundException error) {
                result = AppUpdates.Result.error("无法读取当前应用版本。");
            }
            AppUpdates.Result completed = result;
            runOnUiThread(() -> showAppUpdate(completed));
        }, "app-update-check").start();
    }

    private void showAppUpdate(AppUpdates.Result result) {
        checkingAppUpdate = false;
        if (isFinishing() || isDestroyed()) return;
        availableAppUpdate = result.release;
        JSONObject detail = new JSONObject();
        try {
            detail.put("status", result.status).put("message", result.message);
            if (result.release != null) {
                detail.put("version", result.release.versionName).put("notes", result.release.notes);
            }
        } catch (JSONException error) {
            throw new IllegalStateException(error);
        }
        String json = detail.toString().replace("\u2028", "\\u2028").replace("\u2029", "\\u2029");
        page.evaluateJavascript("window.dispatchEvent(new CustomEvent('app-update-result', {detail:" + json + "}))", null);
    }

    private final class Bridge {
        @JavascriptInterface
        public String clipboardText() {
            ClipboardManager clipboard = getSystemService(ClipboardManager.class);
            ClipData clip = clipboard.getPrimaryClip();
            if (clip == null || clip.getItemCount() == 0) return "";
            CharSequence text = clip.getItemAt(0).getText();
            return text == null ? "" : text.toString();
        }

        @JavascriptInterface
        public String start(String url, int height, boolean proxyEnabled, String proxyAddress, String proxyPort,
                            boolean subtitles, int rateLimitKiB, String videoContainer, String videoCodec,
                            String proxyScheme, int fragments, String outputMode, String audioFormat, boolean cover) {
            return DownloadService.enqueue(MainActivity.this, url, height, proxyEnabled, proxyAddress, proxyPort,
                    subtitles, rateLimitKiB, outputMode, videoCodec, proxyScheme, fragments, audioFormat, cover, null);
        }

        @JavascriptInterface
        public String startWithSubtitles(String url, int height, boolean proxyEnabled, String proxyAddress,
                                         String proxyPort, boolean subtitles, int rateLimitKiB, String videoContainer,
                                         String videoCodec, String proxyScheme, int fragments, String outputMode,
                                         String audioFormat, boolean cover, String selection) {
            if (selection == null) return "请选择有效的字幕轨道。";
            return DownloadService.enqueue(MainActivity.this, url, height, proxyEnabled, proxyAddress, proxyPort,
                    subtitles, rateLimitKiB, outputMode, videoCodec, proxyScheme, fragments, audioFormat, cover, selection);
        }

        @JavascriptInterface
        public String downloadDestination() {
            DownloadDestination.Snapshot settings = DownloadDestination.snapshot(getApplicationContext());
            Uri tree = settings.tree;
            if (tree != null && !tree.equals(labeledDestination)) {
                try {
                    updateDestinationLabel(tree);
                } catch (RuntimeException error) {
                    destinationLabel = "自选下载目录";
                    labeledDestination = tree;
                }
            }
            try {
                return new JSONObject().put("custom", tree != null)
                        .put("label", tree == null ? "下载 / 多平台下载" : destinationLabel)
                        .put("classification", settings.classification).put("message", destinationMessage).toString();
            } catch (JSONException error) {
                throw new IllegalStateException(error);
            }
        }

        @JavascriptInterface
        public void chooseDownloadDestination() {
            runOnUiThread(() -> {
                destinationMessage = "";
                try {
                    Intent picker = DownloadDestination.pickerIntent();
                    Uri tree = DownloadDestination.currentTree(getApplicationContext());
                    if (tree != null) picker.putExtra(DocumentsContract.EXTRA_INITIAL_URI, DownloadDestination.treeDocument(tree));
                    startActivityForResult(picker, PICK_DOWNLOAD_DIRECTORY);
                } catch (RuntimeException error) {
                    destinationMessage = "无法打开系统目录选择器。";
                }
            });
        }

        @JavascriptInterface
        public String resetDownloadDestination() {
            try {
                DownloadDestination.reset(getApplicationContext());
                destinationMessage = "已恢复默认下载目录。";
                return "";
            } catch (IOException | RuntimeException error) {
                return "无法恢复默认下载目录。";
            }
        }

        @JavascriptInterface
        public String setDownloadClassification(String classification) {
            destinationMessage = "";
            return DownloadDestination.setClassification(getApplicationContext(), classification);
        }

        @JavascriptInterface
        public void importLinks() {
            runOnUiThread(MainActivity.this::pickLinkDocument);
        }

        @JavascriptInterface
        public String linksImportState() {
            return linkImportState();
        }

        @JavascriptInterface
        public String downloadDefaults() {
            SharedPreferences defaults = getSharedPreferences(DOWNLOAD_DEFAULTS, MODE_PRIVATE);
            try {
                return new JSONObject().put(HEIGHT, defaults.getInt(HEIGHT, 0))
                        .put(SUBTITLES, defaults.getBoolean(SUBTITLES, false))
                        .put(RATE_LIMIT, defaults.getInt(RATE_LIMIT, 0))
                        .put(VIDEO_CONTAINER, defaults.getString(VIDEO_CONTAINER, "mp4"))
                        .put(VIDEO_CODEC, defaults.getString(VIDEO_CODEC, "auto"))
                        .put(OUTPUT_MODE, defaults.getString(OUTPUT_MODE, defaults.getInt(HEIGHT, 0) == -3 ? "audio" : "video"))
                        .put(AUDIO_FORMAT, defaults.getString(AUDIO_FORMAT, "m4a"))
                        .put(COVER, defaults.getBoolean(COVER, false))
                        .put(FRAGMENTS, defaults.getInt(FRAGMENTS, 1)).toString();
            } catch (JSONException error) {
                throw new IllegalStateException(error);
            }
        }

        @JavascriptInterface
        public String saveDownloadDefaults(int height, boolean subtitles, int rateLimitKiB,
                                           String videoContainer, String videoCodec, int fragments, String outputMode,
                                           String audioFormat, boolean cover) {
            String error = validateDownloadOptions(height, rateLimitKiB, videoCodec, fragments, outputMode, audioFormat);
            if (!error.isEmpty()) return error;
            boolean written = getSharedPreferences(DOWNLOAD_DEFAULTS, MODE_PRIVATE).edit()
                    .putInt(HEIGHT, height).putBoolean(SUBTITLES, subtitles).putInt(RATE_LIMIT, rateLimitKiB)
                    .putString(VIDEO_CONTAINER, "mp4").putString(VIDEO_CODEC, videoCodec).putString(OUTPUT_MODE, outputMode)
                    .putString(AUDIO_FORMAT, audioFormat).putBoolean(COVER, cover)
                    .putInt(FRAGMENTS, fragments).commit();
            return written ? "" : "无法保存默认下载选项。";
        }

        @JavascriptInterface
        public String downloadPresets() {
            synchronized (DOWNLOAD_PRESETS_LOCK) {
                try {
                    SharedPreferences store = getSharedPreferences(DOWNLOAD_PRESETS, MODE_PRIVATE);
                    return new JSONArray(store.getString(PRESET_ENTRIES, "[]")).toString();
                } catch (JSONException | RuntimeException error) {
                    return null;
                }
            }
        }

        @JavascriptInterface
        public String saveDownloadPreset(String input, int height, boolean subtitles, int rateLimitKiB,
                                         String videoContainer, String videoCodec, int fragments, String outputMode,
                                         String audioFormat, boolean cover) {
            String name = validatedPresetName(input);
            if (name == null) return "预设名称需为 1–40 个字符。";
            String invalidOptions = validateDownloadOptions(height, rateLimitKiB, videoCodec, fragments, outputMode, audioFormat);
            if (!invalidOptions.isEmpty()) return invalidOptions;
            synchronized (DOWNLOAD_PRESETS_LOCK) {
                try {
                    SharedPreferences store = getSharedPreferences(DOWNLOAD_PRESETS, MODE_PRIVATE);
                    String previous = store.getString(PRESET_ENTRIES, "[]");
                    JSONArray presets = new JSONArray(previous);
                    JSONObject item = new JSONObject().put("name", name).put(HEIGHT, height)
                            .put(SUBTITLES, subtitles).put(RATE_LIMIT, rateLimitKiB)
                            .put(VIDEO_CONTAINER, "mp4").put(VIDEO_CODEC, videoCodec).put(FRAGMENTS, fragments)
                            .put(OUTPUT_MODE, outputMode).put(AUDIO_FORMAT, audioFormat).put(COVER, cover);
                    int index = downloadPresetIndex(presets, name);
                    presets.put(index == -1 ? presets.length() : index, item);
                    return writeDownloadPresets(store, previous, presets) ? "" : "无法保存配置预设。";
                } catch (JSONException | RuntimeException error) {
                    return "无法保存配置预设。";
                }
            }
        }

        @JavascriptInterface
        public String deleteDownloadPreset(String input) {
            String name = validatedPresetName(input);
            if (name == null) return "预设名称需为 1–40 个字符。";
            synchronized (DOWNLOAD_PRESETS_LOCK) {
                try {
                    SharedPreferences store = getSharedPreferences(DOWNLOAD_PRESETS, MODE_PRIVATE);
                    String previous = store.getString(PRESET_ENTRIES, "[]");
                    JSONArray presets = new JSONArray(previous);
                    int index = downloadPresetIndex(presets, name);
                    if (index == -1) return "";
                    presets.remove(index);
                    return writeDownloadPresets(store, previous, presets) ? "" : "无法删除配置预设。";
                } catch (JSONException | RuntimeException error) {
                    return "无法删除配置预设。";
                }
            }
        }

        @JavascriptInterface
        public String engineInfo() {
            try {
                String version = getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
                return new JSONObject().put("appVersion", version)
                        .put("engineVersion", getString(R.string.bundled_engine_version)).toString();
            } catch (PackageManager.NameNotFoundException | JSONException error) {
                return "{}";
            }
        }

        @JavascriptInterface
        public void checkAppUpdate() {
            runOnUiThread(MainActivity.this::checkAppUpdate);
        }

        @JavascriptInterface
        public void openAppUpdate() {
            runOnUiThread(() -> {
                if (!isFinishing() && !isDestroyed() && availableAppUpdate != null) {
                    openProjectLink(Uri.parse(availableAppUpdate.downloadUrl), "无法打开更新下载，请检查是否安装了浏览器。");
                }
            });
        }

        @JavascriptInterface
        public boolean isAgreementAccepted() {
            return hasAcceptedAgreement();
        }

        @JavascriptInterface
        public boolean acceptAgreement() {
            SharedPreferences agreement = getSharedPreferences(AGREEMENT_PREFERENCES, MODE_PRIVATE);
            int previousVersion = agreement.getInt(ACCEPTED_AGREEMENT_VERSION, 0);
            if (previousVersion == AGREEMENT_VERSION) return true;
            if (agreement.edit().putInt(ACCEPTED_AGREEMENT_VERSION, AGREEMENT_VERSION).commit()) {
                runOnUiThread(MainActivity.this::maybeShowBatterySetup);
                return true;
            }
            agreement.edit().putInt(ACCEPTED_AGREEMENT_VERSION, previousVersion).apply();
            return false;
        }

        @JavascriptInterface
        public void openDownloadDirectory() {
            runOnUiThread(MainActivity.this::browseDownloadDirectory);
        }

        @JavascriptInterface
        public void openProjectPage() {
            openProjectLink(PROJECT_PAGE, "无法打开项目主页。");
        }

        private void openProjectLink(Uri uri, String errorMessage) {
            runOnUiThread(() -> {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE));
                } catch (ActivityNotFoundException | SecurityException error) {
                    Toast.makeText(MainActivity.this, errorMessage, Toast.LENGTH_SHORT).show();
                }
            });
        }

        @JavascriptInterface
        public String inspectFanbox(String url) {
            return FanboxArchive.inspect(getApplicationContext(), url);
        }

        @JavascriptInterface
        public String archiveFanbox() {
            return FanboxArchive.archive(getApplicationContext());
        }

        @JavascriptInterface
        public void cancelFanbox() {
            FanboxArchive.cancel();
        }

        @JavascriptInterface
        public String fanboxState() {
            return FanboxArchive.snapshot();
        }

        @JavascriptInterface
        public String inspectCollection(String url, boolean proxyEnabled, String proxyAddress, String proxyPort,
                                        String proxyScheme) {
            return DownloadService.inspectCollection(getApplicationContext(), url, proxyEnabled, proxyAddress,
                    proxyPort, proxyScheme);
        }

        @JavascriptInterface
        public String collectionState() {
            return DownloadService.collectionState();
        }

        @JavascriptInterface
        public void cancelCollection() {
            DownloadService.cancelCollection();
        }

        @JavascriptInterface
        public String inspectSubtitles(String url, boolean proxyEnabled, String proxyAddress, String proxyPort,
                                       String proxyScheme) {
            return DownloadService.inspectSubtitles(getApplicationContext(), url, proxyEnabled, proxyAddress,
                    proxyPort, proxyScheme);
        }

        @JavascriptInterface
        public String subtitleState() {
            return DownloadService.collectionState();
        }

        @JavascriptInterface
        public void cancelSubtitles() {
            DownloadService.cancelCollection();
        }

        @JavascriptInterface
        public void cancel() {
            DownloadService.cancel();
        }

        @JavascriptInterface
        public void skipCurrent() {
            DownloadService.skipCurrent();
        }

        @JavascriptInterface
        public String snapshot() {
            return DownloadService.snapshot();
        }

        @JavascriptInterface
        public String downloadHistory() {
            return DownloadHistory.list(getApplicationContext());
        }

        @JavascriptInterface
        public String deleteDownloadHistory(String id, boolean deleteFiles) {
            Context context = getApplicationContext();
            String message = DownloadHistory.delete(context, id, deleteFiles);
            if (deleteFiles && message.isEmpty() && id != null) DownloadService.refreshDeletedMedia(context, id);
            return message;
        }

        @JavascriptInterface
        public String playHistoryVideo(String id) {
            Uri media = DownloadHistory.completedVideo(getApplicationContext(), id);
            return media == null ? "找不到可播放的下载记录。" : openSavedMedia(media);
        }

        @JavascriptInterface
        public String playHistoryAudio(String id) {
            Uri media = DownloadHistory.completedAudio(getApplicationContext(), id);
            return media == null ? "找不到可播放的独立音频。" : openSavedMedia(media);
        }

        @JavascriptInterface
        public String openHistoryVideoLocation(String id) {
            Uri media = DownloadHistory.completedVideo(getApplicationContext(), id);
            if (media == null) media = DownloadHistory.completedAudio(getApplicationContext(), id);
            return media == null ? "找不到包含文件的下载记录。"
                    : openSavedMediaLocation(media, DownloadHistory.completedDirectory(getApplicationContext(), id));
        }

        @JavascriptInterface
        public String cookieState(String id) {
            return DownloadService.cookieState(getApplicationContext(), Platform.fromId(id));
        }

        @JavascriptInterface
        public String setPlatformCookiesEnabled(String id, boolean enabled) {
            return DownloadService.setPlatformCookiesEnabled(getApplicationContext(), Platform.fromId(id), enabled);
        }

        @JavascriptInterface
        public void importCookies(String id) {
            Platform platform = Platform.fromId(id);
            if (platform != null) runOnUiThread(() -> pickCookies(platform));
        }

        @JavascriptInterface
        public void removeCookies(String id) {
            Platform platform = Platform.fromId(id);
            if (platform != null) {
                runOnUiThread(() -> DownloadService.changeCookies(getApplicationContext(), platform, null, null));
            }
        }

        @JavascriptInterface
        public void playVideo() {
            Uri media = DownloadService.completedVideo();
            if (media == null) return;
            String message = openSavedMedia(media);
            if (!message.isEmpty()) {
                runOnUiThread(() -> Toast.makeText(MainActivity.this, message, Toast.LENGTH_SHORT).show());
            }
        }

        @JavascriptInterface
        public String playCompanionAudio() {
            Uri media = DownloadService.completedAudio();
            return media == null ? "找不到本次下载的独立音频。" : openSavedMedia(media);
        }

        @JavascriptInterface
        public String openVideoLocation() {
            Uri media = DownloadService.completedVideo();
            if (media == null) media = DownloadService.completedAudio();
            return media == null ? "找不到本次下载的文件。" : openSavedMediaLocation(media, DownloadService.completedDirectory());
        }
    }
}
