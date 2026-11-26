import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { Window } from "happy-dom";

const html = await readFile(process.env.VD_SETTINGS_TEST_PAGE
    || new URL("../app/src/main/assets/index.html", import.meta.url), "utf8");
const url = "https://youtu.be/jNQXAC9IVRw";

function openPage(context, downloader) {
    const window = new Window({
        url: "file:///android_asset/index.html",
        settings: {
            enableJavaScriptEvaluation: true,
            disableJavaScriptFileLoading: true,
            disableCSSFileLoading: true,
            suppressInsecureJavaScriptEnvironmentWarning: true,
        },
    });
    context.after(() => window.close());
    let poll;
    window.setInterval = callback => { poll = callback; return 0; };
    window.Downloader = downloader;
    window.document.write(html);
    window.document.close();
    const element = id => window.document.getElementById(id);
    return {
        window,
        element,
        show: id => !element(id).closest("[hidden], [inert]"),
        click: id => element(id).click(),
        refresh: () => poll(),
    };
}

test("首次打开要滚到协议末尾，保存确认后再次打开不弹窗", context => {
    let accepted = false;
    let canSave = false;
    let saveAttempts = 0;
    const downloader = {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        isAgreementAccepted: () => accepted,
        acceptAgreement: () => {
            saveAttempts++;
            if (canSave) accepted = true;
            return canSave;
        },
    };
    const { window, element, click } = openPage(context, downloader);
    const dialog = element("agreementDialog");
    const text = element("agreementText");
    const confirm = element("agreementConfirm");
    Object.defineProperties(text, {
        clientHeight: { value: 120 },
        scrollHeight: { value: 360 },
    });

    assert.equal(dialog.open, true);
    assert.equal(confirm.disabled, true);
    assert.equal(element("agreementHint").textContent, "下滑阅读完整协议");
    const cancel = new window.Event("cancel", { cancelable: true });
    dialog.dispatchEvent(cancel);
    assert.equal(cancel.defaultPrevented, true);
    text.scrollTop = 100;
    text.dispatchEvent(new window.Event("scroll"));
    assert.equal(confirm.disabled, true);
    assert.equal(element("agreementHint").textContent, "下滑阅读完整协议");
    click("agreementConfirm");
    assert.equal(saveAttempts, 0);

    text.scrollTop = 240;
    text.dispatchEvent(new window.Event("scroll"));
    assert.equal(confirm.disabled, false);
    assert.equal(element("agreementHint").textContent, "已滑到底部");
    click("agreementConfirm");
    assert.equal(dialog.open, true);
    assert.match(element("agreementNote").textContent, /未能保存确认状态/);
    canSave = true;
    click("agreementConfirm");
    assert.equal(dialog.open, false);
    assert.equal(saveAttempts, 2);

    const reopened = openPage(context, downloader);
    assert.equal(reopened.element("agreementDialog").open, false);
    assert.equal(reopened.element("aboutAgreement").open, false);
    assert.equal(reopened.element("aboutAgreementText").textContent.trim(), text.textContent.trim());
});

test("设置目录定位并展开分类，再次选择同一项可折叠", { timeout: 4000 }, async context => {
    const { window, element, show, click } = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        cookieState: () => JSON.stringify({ configured: false, busy: false, enabled: false }),
        setPlatformCookiesEnabled: () => "",
        downloadDefaults: () => JSON.stringify({ height: 0, subtitles: false, rateLimitKiB: 0 }),
        saveDownloadDefaults: () => "",
        fanboxState: () => JSON.stringify({ status: "idle" }),
        inspectFanbox: () => "",
        archiveFanbox: () => "",
        cancelFanbox: () => {},
    });
    element("url").value = url;
    click("openSettings");
    const directory = element("settingsDirectory");
    assert.equal(directory.tagName, "NAV");
    assert.equal(directory.getAttribute("aria-label"), "设置目录");
    assert.equal(show("settingsDirectory"), true);

    const panels = {
        proxyDisclosure: "networkPanel",
        cookieDisclosure: "cookieList",
        fanboxDisclosure: "fanboxPanel",
    };
    const entry = id => directory.querySelector(`[data-settings-target="${id}"]`);
    const currentEntry = () => [...directory.querySelectorAll('[aria-current="location"]')];
    assert.equal(entry("defaultsDisclosure"), null);
    assert.equal(entry("outputDisclosure"), null);
    for (const [id, panel] of Object.entries(panels)) {
        assert.ok(entry(id), `目录缺少 ${id}`);
        assert.equal(entry(id).closest("[hidden], [inert]"), null);
        assert.equal(entry(id).getAttribute("aria-controls"), panel);
        assert.equal(entry(id).getAttribute("aria-expanded"), "false");
        assert.equal(show(panel), false);
    }

    const network = entry("proxyDisclosure");
    network.click();
    assert.equal(show("networkPanel"), true);
    assert.equal(network.getAttribute("aria-expanded"), "true");
    assert.deepEqual(currentEntry(), [network]);
    network.click();
    assert.equal(show("networkPanel"), false);
    assert.equal(network.getAttribute("aria-expanded"), "false");
    assert.deepEqual(currentEntry(), [network]);
    assert.equal(show("vpnHint"), true);
    assert.equal(show("cookieHint"), true);
    network.click();
    assert.equal(show("networkPanel"), true);

    const archive = entry("fanboxDisclosure");
    archive.click();
    assert.equal(show("fanboxPanel"), true);
    assert.equal(show("networkPanel"), true, "切换分类应保留已展开的面板");
    assert.deepEqual(currentEntry(), [archive]);
    network.click();
    assert.equal(show("networkPanel"), true, "选择另一项已展开的分类时应保持目标展开");
    assert.deepEqual(currentEntry(), [network]);
    click("proxyDisclosure");
    assert.equal(network.getAttribute("aria-expanded"), "false", "卡片收起按钮与目录开合状态应同步");
    assert.equal(window.history.state.settings, true);
    assert.equal(window.location.hash, "#settings");

    const navigated = new Promise(resolve => window.addEventListener("popstate", resolve, { once: true }));
    click("openSettings");
    await navigated;
    assert.equal(show("downloadForm"), true);
    assert.equal(element("url").value, url);
});

test("浏览器预览的设置目录只显示可用章节", context => {
    const { element, show, click } = openPage(context);
    click("openSettings");
    const directory = element("settingsDirectory");
    const visibleEntry = id => {
        const button = directory.querySelector(`[data-settings-target="${id}"]`);
        return Boolean(button && !button.closest("[hidden], [inert]"));
    };
    assert.equal(visibleEntry("proxyDisclosure"), true);
    assert.equal(visibleEntry("cookieDisclosure"), show("cookieSection"));
    assert.equal(show("transferFields"), false);
    assert.equal(element("outputSection"), null);
    assert.equal(show("downloadDestinationSection"), false);
    assert.equal(show("toolboxSection"), false);
    assert.equal(show("fanboxSection"), false);
    assert.equal(visibleEntry("outputDisclosure"), false);
    assert.equal(visibleEntry("destinationDisclosure"), false);
    assert.equal(visibleEntry("toolboxDisclosure"), false);
    assert.equal(visibleEntry("fanboxDisclosure"), false);
});

test("从设置打开帮助和关于页，返回时保留设置和下载链接", { timeout: 4000 }, async context => {
    let projectOpens = 0;
    const { window, element, show, click } = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        engineInfo: () => JSON.stringify({ appVersion: "1.2.3-test", engineVersion: "2026.11.23" }),
        openProjectPage: () => { projectOpens += 1; },
    });
    async function back(action) {
        const navigated = new Promise(resolve => window.addEventListener("popstate", resolve, { once: true }));
        action();
        await navigated;
    }

    element("url").value = url;
    click("openSettings");
    click("proxyDisclosure");
    element("proxyAddress").value = "127.0.0.1";
    element("proxyPort").value = "3128";
    assert.equal(show("openHelp"), true);
    assert.equal(show("openAbout"), true);

    click("openHelp");
    assert.equal(show("helpView"), true);
    assert.equal(show("settingsView"), false);
    assert.equal(show("aboutView"), false);
    assert.equal(show("downloadForm"), false);
    assert.equal(element("settingsAction").textContent, "返回设置");
    const topic = element("helpView").querySelector("details:not([open])");
    assert.ok(topic, "帮助页包含可展开的主题");
    topic.querySelector("summary").click();
    assert.equal(topic.open, true);
    const fileHelp = Array.from(element("helpView").querySelectorAll("details"))
        .find(section => section.querySelector("summary").textContent === "找不到下载的文件");
    assert.match(fileHelp.textContent, /按平台和作者.*平台目录下再按作者分文件夹/);
    await back(() => click("openSettings"));
    assert.equal(show("settingsView"), true);
    assert.equal(show("helpView"), false);
    assert.equal(window.document.activeElement, element("openHelp"));

    click("openAbout");
    assert.equal(show("aboutView"), true);
    assert.equal(show("settingsView"), false);
    assert.equal(element("settingsAction").textContent, "返回设置");
    assert.equal(element("aboutAppVersion").textContent, "1.2.3-test");
    assert.equal(element("aboutEngineVersion").textContent, "2026.11.23");
    assert.equal(element("aboutProjectLink").href, "https://github.com/maomaoyexi/video-downloader");
    click("aboutProjectLink");
    assert.equal(projectOpens, 1);
    assert.equal(element("aboutCredits").textContent, "安卓端作者与贡献者");
    const credits = element("aboutView").querySelector(".about-credits");
    assert.deepEqual(Array.from(credits.querySelectorAll("dt"), author => author.textContent),
        ["猫猫葉汐A_spy（@maomaoyexi）"]);
    assert.equal(credits.querySelector("dd").textContent, "安卓端移植、开发与维护");
    assert.equal(show("aboutView"), true);
    await back(() => window.history.back());
    assert.equal(show("settingsView"), true);
    assert.equal(show("aboutView"), false);
    assert.equal(window.document.activeElement, element("openAbout"));
    assert.equal(show("networkPanel"), true);
    assert.equal(element("proxyAddress").value, "127.0.0.1");
    assert.equal(element("proxyPort").value, "3128");
    await back(() => click("openSettings"));
    assert.equal(show("downloadForm"), true);
    assert.equal(element("url").value, url);
});

test("关于页可在浏览器预览及版本信息异常时打开", context => {
    const invalidVersionBridge = {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        engineInfo: () => "invalid json",
    };
    for (const bridge of [undefined, invalidVersionBridge]) {
        const { element, show, click } = openPage(context, bridge);
        click("openSettings");
        click("openAbout");
        assert.equal(show("aboutView"), true);
        assert.equal(element("settingsAction").textContent, "返回设置");
        assert.equal(element("aboutAppVersion").textContent, bridge ? "未读取" : "浏览器预览");
        assert.equal(element("aboutEngineVersion").textContent, "未读取");
        assert.equal(show("checkAppUpdate"), false);
    }
});

test("关于页检查应用更新，收到结果后提供手动下载", context => {
    let checks = 0;
    let downloads = 0;
    const { window, element, show, click } = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        checkAppUpdate: () => { checks++; },
        openAppUpdate: () => { downloads++; },
    });
    click("openSettings");
    click("openAbout");
    assert.equal(show("checkAppUpdate"), true);
    assert.equal(show("downloadAppUpdate"), false);
    assert.equal(checks, 0, "进入关于页时由用户决定是否检查");

    click("checkAppUpdate");
    assert.equal(element("checkAppUpdate").disabled, true);
    assert.match(element("appUpdateNote").textContent, /正在检查/);
    click("checkAppUpdate");
    assert.equal(checks, 1, "上一次检查结束前不能重复发起");

    const notes = "改进下载\n<img src=x onerror=alert(1)>";
    window.dispatchEvent(new window.CustomEvent("app-update-result", {
        detail: { status: "available", version: "1.2.0", notes },
    }));
    assert.equal(element("checkAppUpdate").disabled, false);
    assert.match(element("appUpdateNote").textContent, /1\.2\.0/);
    assert.equal(show("appUpdateNotes"), true);
    assert.equal(element("appUpdateNotes").textContent, notes);
    assert.equal(element("appUpdateNotes").childElementCount, 0);
    assert.equal(show("downloadAppUpdate"), true);
    assert.equal(downloads, 0, "检查完成后等待用户点下载");
    click("downloadAppUpdate");
    assert.equal(downloads, 1);

    click("checkAppUpdate");
    assert.equal(checks, 2);
    assert.equal(show("appUpdateNotes"), false);
    assert.equal(show("downloadAppUpdate"), false);
});

test("检查更新区区分已是最新版、尚未发布和检查错误，并允许重试", context => {
    let callFails = true;
    const { window, element, show, click } = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        checkAppUpdate: () => {
            if (callFails) throw new Error("Bridge unavailable");
        },
        openAppUpdate: () => {},
    });
    click("openSettings");
    click("openAbout");
    const note = element("appUpdateNote");
    click("checkAppUpdate");
    assert.equal(element("checkAppUpdate").disabled, false);
    assert.match(note.textContent, /检查更新失败/);
    assert.equal(note.dataset.error, "true");
    callFails = false;

    function result(detail) {
        click("checkAppUpdate");
        assert.equal(element("checkAppUpdate").disabled, true);
        window.dispatchEvent(new window.CustomEvent("app-update-result", { detail }));
        assert.equal(element("checkAppUpdate").disabled, false);
        assert.equal(show("appUpdateNotes"), false);
        assert.equal(show("downloadAppUpdate"), false);
    }

    result({ status: "current", version: "1.0.0" });
    assert.match(note.textContent, /已是最新版/);
    assert.equal(note.dataset.error, "false");
    result({ status: "unpublished" });
    assert.match(note.textContent, /暂无.*发布/);
    assert.equal(note.dataset.error, "false");
    result({ status: "error", message: "网络超时，请重试。" });
    assert.equal(note.textContent, "网络超时，请重试。");
    assert.equal(note.dataset.error, "true");
    result(null);
    assert.match(note.textContent, /检查更新失败/);
});

test("从设置配置代理并返回下载，原有任务参数保留", { timeout: 4000 }, async context => {
    let phase = "等待添加任务";
    let busy = false;
    const started = [];
    const { window, element, show, click } = openPage(context, {
        snapshot: () => JSON.stringify({ phase, detail: "", percent: -1, busy }),
        downloadDefaults: () => JSON.stringify({ height: 0, subtitles: false, rateLimitKiB: 512, fragments: 4 }),
        saveDownloadDefaults: () => "",
        start: (...options) => {
            started.push(options);
            phase = "正在下载";
            busy = true;
            return "";
        },
        cancel: () => {
            phase = "已取消";
            busy = false;
        },
    });
    async function returnToDownload() {
        const navigated = new Promise(resolve => window.addEventListener("popstate", resolve, { once: true }));
        click("openSettings");
        await navigated;
        assert.equal(show("downloadForm"), true);
        assert.equal(element("settingsAction").textContent, "设置");
        assert.equal(element("settingsIcon").getAttribute("href"), "#i-settings");
    }

    assert.ok(element("openSettings"), "下载页缺少设置入口");
    assert.equal(show("proxyEnabled"), false);
    assert.equal(element("proxyEnabled").checked, false);
    element("url").value = url;
    click("resolutionSummary");
    click("qualitySummary");
    window.document.querySelector('[data-height="720"]').click();
    click("openSettings");
    assert.equal(show("downloadForm"), false);
    assert.equal(element("settingsAction").textContent, "返回下载");
    assert.equal(element("settingsIcon").getAttribute("href"), "#i-back");
    assert.equal(show("proxyEnabled"), false);
    assert.equal(show("networkPanel"), false);
    assert.equal(show("vpnHint"), true);
    assert.equal(show("proxyFields"), false);
    click("proxyDisclosure");
    assert.equal(show("networkPanel"), true);
    assert.equal(show("proxyEnabled"), true);
    assert.ok(element("proxyFields").contains(element("proxyEnabled")));
    assert.equal(element("proxyEnabled").checked, false);
    assert.equal(show("proxyFields"), true, "关闭代理时仍可填写地址和端口");
    assert.equal(show("proxyHint"), true);
    click("proxyEnabled");
    assert.equal(show("networkPanel"), true, "开启代理不应折叠网络设置");
    await returnToDownload();

    click("start");
    assert.equal(started.length, 0, "错误代理参数不能开始下载");
    assert.equal(element("proxyDisclosure").getAttribute("aria-expanded"), "true");
    assert.equal(show("proxyFields"), true);
    assert.match(element("proxyNote").textContent, /有效的代理地址和端口/);

    click("proxySchemePicker");
    assert.equal(show("proxySchemeOptions"), true);
    element("proxySchemeOptions").querySelector('[value="socks5"]').click();
    assert.equal(show("proxySchemeOptions"), false);
    assert.equal(element("proxySchemePicker").textContent.trim(), "SOCKS5");
    assert.equal(element("proxyNote").textContent, "");
    element("proxyAddress").value = "127.0.0.1";
    element("proxyPort").value = "3128";
    await returnToDownload();
    assert.equal(element("url").value, url);
    assert.equal(element("resolutionValue").textContent, "720p");
    click("start");
    assert.deepEqual(started, [[url, 720, true, "127.0.0.1", "3128", false, 512, "mp4", "auto", "socks5", 4, "video", "m4a", false]]);

    click("openSettings");
    assert.equal(element("proxyEnabled").disabled, true);
    assert.equal(element("proxySchemePicker").disabled, true);
    assert.equal(element("fragments").disabled, true);
    await returnToDownload();
    click("cancel");
    assert.equal(element("phase").textContent, "已取消");
    click("openSettings");
    assert.equal(element("proxyEnabled").disabled, false);
    click("proxyEnabled");
    assert.equal(element("rateLimit").disabled, false);
    assert.equal(element("fragments").disabled, false);
    assert.equal(show("transferFields"), true);
    element("proxyPort").value = "";
    await returnToDownload();
    click("start");
    assert.deepEqual(started[1], [url, 720, false, "127.0.0.1", "", false, 512, "mp4", "auto", "socks5", 4, "video", "m4a", false]);
});

test("加载默认画质和分片设置，使用 MP4 并保留编码偏好", { timeout: 4000 }, async context => {
    const defaults = { height: 720, subtitles: true, rateLimitKiB: 3500, videoContainer: "mkv", videoCodec: "h264", fragments: 8 };
    const starts = [];
    const bridge = {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        downloadDefaults: () => JSON.stringify(defaults),
        saveDownloadDefaults: () => "",
        start: (...options) => { starts.push(options); return ""; },
    };
    const { window, element, show, click } = openPage(context, bridge);
    const rate = element("rateLimit");
    const codec = element("videoCodecPicker");
    const fragmentsInput = element("fragments");
    const transferNote = element("transferNote");
    assert.ok(element("networkPanel").contains(fragmentsInput));
    assert.ok(element("networkPanel").contains(rate));
    element("url").value = url;
    assert.equal(element("resolutionValue").textContent, "720p");
    assert.equal(element("moreOptionsValue").textContent, "H.264 · 字幕");
    assert.equal(rate.value, "3500");
    assert.equal(element("videoContainer"), null);
    assert.equal(element("outputSection"), null);
    assert.ok(element("downloadForm").contains(codec));
    assert.equal(element("videoCodecValue").textContent, "H.264");
    assert.equal(fragmentsInput.value, "8");
    click("start");
    assert.deepEqual(starts, [[url, 720, false, "", "", true, 3500, "mp4", "h264", "http", 8, "video", "m4a", false]]);

    fragmentsInput.value = "17";
    click("start");
    assert.equal(starts.length, 1);
    assert.equal(show("networkPanel"), true);
    assert.match(transferNote.textContent, /1–16/);
    assert.equal(element("settingsDirectory").querySelector('[aria-current="location"]').dataset.settingsTarget,
        "proxyDisclosure");
    fragmentsInput.value = "6";
    fragmentsInput.dispatchEvent(new window.Event("input"));
    assert.equal(transferNote.textContent, "");
    let navigated = new Promise(resolve => window.addEventListener("popstate", resolve, { once: true }));
    click("openSettings");
    await navigated;

    rate.value = "102401";
    click("start");
    assert.equal(starts.length, 1);
    assert.equal(show("networkPanel"), true);
    assert.match(transferNote.textContent, /102400/);
    rate.value = "2048";
    navigated = new Promise(resolve => window.addEventListener("popstate", resolve, { once: true }));
    click("openSettings");
    await navigated;
    click("resolutionSummary");
    assert.equal(codec.open, false);
    click("moreOptionsSummary");
    click("videoCodecSummary");
    assert.equal(codec.open, true);
    assert.equal(codec.querySelector('[data-video-codec="h264"]').disabled, false);
    codec.querySelector('[data-video-codec="vp9"]').click();
    assert.equal(codec.open, false);
    assert.equal(element("videoCodecValue").textContent, "VP9");
    assert.equal(window.document.activeElement, element("videoCodecSummary"));
    click("outputModeSummary");
    element("outputModePicker").querySelector('[data-output-mode="audio"]').click();
    assert.equal(codec.hidden, true);
    click("start");
    assert.deepEqual(starts[1], [url, 720, false, "", "", false, 2048, "mp4", "vp9", "http", 6, "audio", "m4a", false]);
});

test("设置可异步读取所选下载目录、保存分类方式并恢复默认位置", context => {
    const defaultLabel = "下载 / 多平台下载";
    let destination = { custom: false, label: defaultLabel, classification: "none", message: "" };
    let choosing = 0;
    let busy = false;
    const classifications = [];
    const { element, show, click, refresh } = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy }),
        downloadDestination: () => JSON.stringify(destination),
        chooseDownloadDestination() { choosing++; },
        resetDownloadDestination() {
            destination = { ...destination, custom: false, label: defaultLabel, message: "已恢复默认下载目录。" };
            return "";
        },
        setDownloadClassification(value) {
            classifications.push(value);
            if (value === "output" && classifications.length === 2) return "无法保存分类方式。";
            destination = { ...destination, classification: value, message: "" };
            return "";
        },
    });
    const picker = element("downloadClassificationPicker");
    const options = element("downloadClassificationOptions");
    const status = element("downloadDestinationNote");
    const choose = element("chooseDownloadDestination");
    const reset = element("resetDownloadDestination");
    const setClassification = value => {
        picker.click();
        assert.equal(show("downloadClassificationOptions"), true);
        options.querySelector(`[value="${value}"]`).click();
        assert.equal(show("downloadClassificationOptions"), false);
    };

    click("openSettings");
    const entry = element("settingsDirectory").querySelector('[data-settings-target="destinationDisclosure"]');
    assert.equal(entry.hidden, false);
    assert.equal(show("downloadDestinationPanel"), false);
    entry.click();
    assert.equal(show("downloadDestinationPanel"), true);
    assert.equal(entry.getAttribute("aria-expanded"), "true");
    assert.equal(element("downloadDestinationLabel").textContent, "默认位置 · " + defaultLabel);
    assert.equal(element("downloadDestinationSummary").textContent, "保存到「" + defaultLabel + "」");
    assert.equal(reset.disabled, true);
    assert.equal(picker.textContent.trim(), "不分类");
    assert.deepEqual(Array.from(options.querySelectorAll("button"), button => [button.value, button.textContent]), [
        ["none", "不分类"], ["platform", "按平台"], ["platform-author", "按平台和作者"], ["output", "按输出模式"],
    ]);
    choose.click();
    assert.equal(choosing, 1);
    const customLabel = "媒体 / 安卓";
    destination = { ...destination, custom: true, label: customLabel, message: "已更改下载目录。" };
    refresh();
    assert.equal(element("downloadDestinationLabel").textContent, "自选位置 · " + customLabel);
    assert.equal(element("downloadDestinationSummary").textContent, "保存到「" + customLabel + "」");
    assert.equal(status.textContent, "已更改下载目录。");
    assert.equal(reset.disabled, false);

    setClassification("platform");
    assert.equal(picker.textContent.trim(), "按平台");
    setClassification("output");
    assert.equal(picker.textContent.trim(), "按平台");
    assert.equal(status.textContent, "无法保存分类方式。");
    assert.equal(status.dataset.error, "true");
    refresh();
    assert.equal(status.textContent, "无法保存分类方式。");
    setClassification("output");
    assert.equal(picker.textContent.trim(), "按输出模式");
    assert.equal(status.textContent, "");
    setClassification("platform-author");
    refresh();
    assert.equal(picker.textContent.trim(), "按平台和作者");
    assert.equal(options.querySelector('[value="platform-author"]').getAttribute("aria-pressed"), "true");
    assert.deepEqual(classifications, ["platform", "output", "output", "platform-author"]);

    picker.click();
    busy = true;
    refresh();
    assert.equal(choose.disabled, true);
    assert.equal(reset.disabled, true);
    assert.equal(picker.disabled, true);
    assert.equal(show("downloadClassificationOptions"), false);
    busy = false;
    refresh();
    reset.click();
    assert.equal(reset.disabled, true);
    assert.equal(element("downloadDestinationLabel").textContent, "默认位置 · " + defaultLabel);
    assert.equal(element("downloadDestinationSummary").textContent, "保存到「" + defaultLabel + "」");
    assert.equal(status.textContent, "已恢复默认下载目录。");
    assert.equal(picker.textContent.trim(), "按平台和作者");
});

test("工具箱显示版本并通过桥接打开下载目录", context => {
    const operations = [];
    const { element, show, click } = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        engineInfo: () => JSON.stringify({ appVersion: "0.1.0", engineVersion: "2026.11.23" }),
        openDownloadDirectory: () => operations.push("directory"),
    });
    click("openSettings");
    element("settingsDirectory").querySelector('[data-settings-target="toolboxDisclosure"]').click();
    assert.equal(show("toolboxPanel"), true);
    assert.equal(element("appVersion").textContent, "0.1.0");
    assert.equal(element("engineVersion").textContent, "2026.11.23");
    assert.deepEqual(Array.from(element("toolboxPanel").querySelectorAll("button"), button => button.textContent), ["打开下载目录"]);
    click("openDownloadDirectory");
    assert.deepEqual(operations, ["directory"]);
});

test("FANBOX 预览在专项归档内单独确认保存，支持取消和失败反馈", context => {
    const inspected = [];
    let saves = 0;
    let canceled = 0;
    let state = { status: "idle" };
    const { window, element, show, click, refresh } = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        fanboxState: () => JSON.stringify(state),
        inspectFanbox: value => { inspected.push(value); state = { status: "loading", detail: "正在读取帖子。" }; return ""; },
        archiveFanbox: () => { saves++; state = { ...state, status: "saving" }; return ""; },
        cancelFanbox: () => { canceled++; state = { status: "idle" }; },
    });
    click("openSettings");
    assert.equal(show("fanboxPanel"), false);
    click("fanboxDisclosure");
    const input = element("fanboxUrl");
    const link = "https://www.fanbox.cc/@creator/posts/123";
    input.value = link;
    input.dispatchEvent(new window.Event("input"));
    click("inspectFanbox");
    assert.deepEqual(inspected, [link]);
    assert.equal(show("fanboxProgress"), true);
    assert.equal(input.disabled, true);

    state = { status: "ready", title: "<作品标题>", preview: "第一行\n第二行", files: 3 };
    refresh();
    assert.equal(show("fanboxPreview"), true);
    assert.equal(element("fanboxTitle").textContent, "<作品标题>");
    assert.equal(element("fanboxTitle").children.length, 0);
    assert.equal(element("fanboxExcerpt").textContent, "第一行\n第二行");
    assert.match(element("fanboxFileCount").textContent, /3 项/);
    assert.equal(saves, 0);
    click("archiveFanbox");
    assert.equal(saves, 1);
    assert.equal(show("archiveFanbox"), false);
    assert.equal(show("cancelFanbox"), true);
    click("cancelFanbox");
    assert.equal(canceled, 1);
    assert.equal(show("fanboxPreview"), false);
    assert.equal(input.disabled, false);

    state = { status: "error", detail: "此帖子仅对赞助者开放。" };
    refresh();
    assert.match(element("fanboxNote").textContent, /赞助者/);
    assert.equal(show("archiveFanbox"), false);
    state = { status: "saved", filename: "作品.zip", detail: "已保存。" };
    refresh();
    assert.equal(element("fanboxFilename").textContent, "作品.zip");
});

test("各平台 Cookie 开关独立，关闭时仍可管理配置", context => {
    let downloading = false;
    let busy = false;
    let toggleError = "";
    const cookies = {
        bilibili: { configured: true, enabled: true, message: "" },
        youtube: { configured: false, enabled: false, message: "" },
    };
    const actions = [];
    const { element, show, click, refresh } = openPage(context, {
        snapshot: () => JSON.stringify({
            phase: downloading ? "正在下载" : "等待添加任务",
            detail: "", percent: -1, busy: downloading,
        }),
        cookieState: platform => JSON.stringify({ ...cookies[platform], busy }),
        setPlatformCookiesEnabled: (platform, value) => {
            if (!toggleError) cookies[platform].enabled = value;
            return toggleError;
        },
        importCookies: platform => {
            actions.push(["import", platform]);
            busy = true;
        },
        removeCookies: platform => {
            actions.push(["remove", platform]);
            Object.assign(cookies[platform], { configured: false, message: "已移除。" });
        },
    });
    const biliToggle = element("biliCookieEnabled");
    const youtubeToggle = element("youtubeCookieEnabled");
    const youtubeToggleNote = youtubeToggle.closest("[data-cookie-platform]").querySelector("[data-cookie-toggle-note]");
    const disclosure = element("cookieDisclosure");
    const status = element("youtubeCookieStatus");
    const note = element("youtubeCookieNote");
    const importButton = element("youtubeCookieImport");
    const removeButton = element("youtubeCookieRemove");

    assert.equal(show("cookieSection"), false);
    click("openSettings");
    assert.equal(show("cookieSection"), true);
    assert.equal(element("cookieEnabled"), null);
    assert.equal(show("cookieList"), false);
    assert.equal(show("cookieHint"), true);
    assert.equal(show("biliCookieEnabled"), false);
    assert.equal(show("youtubeCookieEnabled"), false);
    click("cookieDisclosure");
    assert.equal(show("cookieList"), true);
    assert.equal(disclosure.getAttribute("aria-expanded"), "true");
    assert.equal(biliToggle.checked, true);
    assert.equal(youtubeToggle.checked, false);
    toggleError = "无法保存 Cookie 开关。";
    click("youtubeCookieEnabled");
    assert.equal(youtubeToggle.checked, false);
    assert.match(youtubeToggleNote.textContent, /无法保存/);
    toggleError = "";
    click("youtubeCookieEnabled");
    assert.equal(youtubeToggle.checked, true);
    assert.equal(biliToggle.checked, true);
    assert.equal(youtubeToggleNote.textContent, "");
    click("biliCookieEnabled");
    assert.equal(biliToggle.checked, false);
    assert.equal(youtubeToggle.checked, true);
    assert.equal(show("cookieList"), true, "关闭 Cookie 不应收起列表");
    assert.equal(element("biliCookieStatus").textContent, "已配置");
    assert.equal(status.textContent, "未配置");
    assert.equal(removeButton.hidden, true);

    click("youtubeCookieEnabled");
    click("youtubeCookieImport");
    assert.match(element("cookieBusy").textContent, /正在处理/);
    assert.equal(importButton.disabled, true);
    assert.equal(youtubeToggle.disabled, true);
    assert.equal(biliToggle.disabled, true);
    assert.equal(disclosure.disabled, false);
    Object.assign(cookies.youtube, { configured: true, message: "已导入。" });
    busy = false;
    refresh();
    assert.equal(status.textContent, "已配置");
    assert.equal(youtubeToggle.checked, false);
    assert.equal(removeButton.hidden, false);
    assert.equal(note.textContent, "已导入。");

    click("youtubeCookieImport");
    cookies.youtube.message = "格式无效。";
    busy = false;
    refresh();
    assert.equal(status.textContent, "已配置");
    assert.equal(note.textContent, "格式无效。");

    downloading = true;
    refresh();
    assert.equal(importButton.disabled, true);
    assert.equal(removeButton.disabled, true);
    assert.equal(youtubeToggle.disabled, true);
    click("cookieDisclosure");
    assert.equal(show("cookieList"), false);
    assert.equal(disclosure.getAttribute("aria-expanded"), "false");
    click("cookieDisclosure");
    assert.equal(show("cookieList"), true);
    assert.match(element("cookieBusy").textContent, /任务结束/);
    downloading = false;
    refresh();
    click("youtubeCookieRemove");
    assert.equal(status.textContent, "未配置");
    assert.equal(removeButton.hidden, true);
    assert.equal(element("biliCookieStatus").textContent, "已配置");
    assert.deepEqual(actions, [["import", "youtube"], ["import", "youtube"], ["remove", "youtube"]]);
});

test("历史刷新并通过记录 ID 播放和打开文件位置，返回下载保留链接", { timeout: 4000 }, async context => {
    const history = [];
    const opened = [];
    const companion = [];
    const locations = [];
    const { window, element, show, click, refresh } = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        downloadDestination: () => JSON.stringify({ custom: false, label: "下载 / 多平台下载", classification: "none" }),
        downloadHistory: () => JSON.stringify(history),
        playHistoryVideo: id => {
            opened.push(id);
            return "找不到视频文件。";
        },
        playHistoryAudio: id => {
            companion.push(id);
            return "找不到独立音频文件。";
        },
        openHistoryVideoLocation: id => {
            locations.push(id);
            return "文件已移出下载目录。";
        },
    });
    const link = element("url");
    link.value = url;
    assert.equal(show("historyView"), false);
    click("openHistory");
    assert.equal(show("historyView"), true);
    assert.equal(show("downloadForm"), false);
    assert.equal(show("historyEmpty"), true);

    history.push(
        { id: "saved", title: "<已保存的示例>", platform: "bilibili", finishedAt: 1700000000000, status: "completed" },
        { id: "failed", title: "", platform: "youtube", finishedAt: 1699999999000, status: "failed" },
        { id: "canceled", title: "", platform: "bilibili", finishedAt: 1699999998000, status: "canceled" },
        { id: "audio", title: "示例音频", platform: "youtube", finishedAt: 1699999997000, status: "completed", audioOnly: true },
        { id: "dual", title: "双文件", platform: "youtube", finishedAt: 1699999996000, status: "completed",
          outputMode: "silent-video-and-audio", hasAudioFile: true },
    );
    refresh();
    assert.equal(show("historyEmpty"), false);
    const list = element("historyList");
    const records = Array.from(list.querySelectorAll("[data-history-id]"));
    assert.deepEqual(records.map(record => record.dataset.historyId), ["saved", "failed", "canceled", "audio", "dual"]);
    assert.match(records[0].textContent, /<已保存的示例>/);
    assert.match(records[1].textContent, /YouTube/);
    assert.match(records[1].textContent, /失败/);
    assert.match(records[2].textContent, /取消/);
    const plays = list.querySelectorAll("button[data-history-play]");
    assert.equal(plays.length, 3);
    assert.equal(plays[0].textContent, "播放视频");
    assert.equal(plays[1].textContent, "播放音频");
    assert.equal(plays[1].getAttribute("aria-label"), "播放音频：示例音频");
    assert.equal(plays[2].textContent, "播放无声视频");
    assert.deepEqual([0, 3, 4].map(index => records[index].querySelector("[data-history-audio]").hidden), [true, true, false]);
    plays[0].click();
    assert.deepEqual(opened, ["saved"]);
    assert.ok(window.document.body.textContent.includes("找不到视频文件。"));
    plays[1].click();
    assert.deepEqual(opened, ["saved", "audio"]);
    const locationButtons = list.querySelectorAll("button[data-history-location]");
    assert.equal(locationButtons.length, 3);
    assert.equal(locationButtons[0].hidden, false);
    locationButtons[0].focus();
    locationButtons[0].click();
    assert.deepEqual(locations, ["saved"]);
    assert.match(records[0].querySelector(".note").textContent, /移出下载目录/);

    const companionButton = list.querySelector('[data-history-id="dual"] [data-history-audio]');
    assert.equal(companionButton.getAttribute("aria-label"), "播放独立音频：双文件");
    companionButton.focus();
    companionButton.click();
    assert.deepEqual(companion, ["dual"]);
    assert.match(records[4].querySelector(".note").textContent, /找不到独立音频/);
    history.push({ id: "newer", title: "新任务", platform: "youtube", finishedAt: 1700000001000, status: "completed" });
    refresh();
    assert.equal(window.document.activeElement, list.querySelector('[data-history-id="dual"] [data-history-audio]'));
    list.querySelector('[data-history-id="saved"] [data-history-location]').focus();

    history.push({ id: "newest", title: "最新任务", platform: "youtube", finishedAt: 1700000002000, status: "completed" });
    refresh();
    assert.equal(window.document.activeElement, list.querySelector('[data-history-id="saved"] [data-history-location]'));

    const navigated = new Promise(resolve => window.addEventListener("popstate", resolve, { once: true }));
    click("openSettings");
    await navigated;
    assert.equal(show("downloadForm"), true);
    assert.equal(show("historyView"), false);
    assert.equal(link.value, url);
});

test("下载历史可用平台和作者下拉筛选，列表倒序并保留播放和定位", context => {
    const records = [
        { id: "old", platform: "bilibili", title: "旧音频", audioOnly: true, finishedAt: 1700000000000 },
        { id: "youtube", platform: "youtube", title: "音画", authorFolder: "作者甲", outputMode: "video-and-audio",
          finishedAt: 1700000001000, hasAudioFile: true },
        { id: "bilibilinew", platform: "bilibili", title: "视频", authorFolder: "作者甲", outputMode: "video",
          finishedAt: 1700000002000 },
        { id: "youtubeold", platform: "youtube", title: "无声视频", authorFolder: "作者乙",
          outputMode: "silent-video-and-audio", finishedAt: 1699999999000 },
        { id: "bilibilisecond", platform: "bilibili", title: "另一个视频", authorFolder: "作者甲", outputMode: "video",
          finishedAt: 1700000001500 },
    ].map(record => ({ status: "completed", ...record }));
    const actions = [];
    const { window, element, click, refresh } = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        downloadHistory: () => JSON.stringify(records),
        playHistoryAudio(id) { actions.push(["audio", id]); return ""; },
        openHistoryVideoLocation(id) { actions.push(["location", id]); return ""; },
    });
    click("openHistory");
    const list = element("historyList");
    const ids = () => Array.from(list.querySelectorAll(":scope > [data-history-id]"), row => row.dataset.historyId);
    const action = (id, name) => list.querySelector(`[data-history-id="${id}"] [data-history-${name}]`);
    const select = (id, value) => {
        element(id + "Picker").click();
        element(id + "Options").querySelector(`button[value="${value}"]`).click();
    };
    const platforms = element("historyPlatformFilterOptions");
    const authors = element("historyAuthorFilterOptions");
    assert.deepEqual(ids(), ["bilibilinew", "bilibilisecond", "youtube", "old", "youtubeold"]);
    assert.deepEqual(Array.from(platforms.querySelectorAll("button"), button => button.value), ["", "bilibili", "youtube"]);
    assert.deepEqual(Array.from(authors.querySelectorAll("button"), button => button.value), ["", "未知作者", "作者甲", "作者乙"]);

    select("historyPlatformFilter", "youtube");
    assert.deepEqual(ids(), ["youtube", "youtubeold"]);
    assert.equal(window.document.activeElement, element("historyPlatformFilterPicker"));
    assert.deepEqual(Array.from(authors.querySelectorAll("button"), button => button.value), ["", "作者甲", "作者乙"]);
    select("historyAuthorFilter", "作者甲");
    assert.deepEqual(ids(), ["youtube"]);
    assert.equal(window.document.activeElement, element("historyAuthorFilterPicker"));
    action("youtube", "audio").click();

    const matching = element("historySearch");
    matching.value = "音画";
    matching.dispatchEvent(new window.Event("input"));
    assert.deepEqual(ids(), ["youtube"]);
    action("youtube", "location").click();
    assert.deepEqual(actions, [["audio", "youtube"], ["location", "youtube"]]);
    matching.value = "";
    matching.dispatchEvent(new window.Event("input"));

    select("historyPlatformFilter", "");
    assert.equal(element("historyAuthorFilter").value, "");
    assert.deepEqual(ids(), ["bilibilinew", "bilibilisecond", "youtube", "old", "youtubeold"]);
    assert.equal(list.querySelectorAll(".history-group, .history-disclosure").length, 0);
    assert.equal(element("historyEmpty").hidden, true);
});

test("批量删除只处理已筛选结果中的勾选记录，取消不删除，失败可重试", { timeout: 4000 }, async context => {
    const records = [
        { id: "main", title: "VIDEO 主文件", authorFolder: "作者甲", mediaNames: ["video.mp4"], attachmentNames: ["video.webp"] },
        { id: "audio", title: "Video 音频", authorFolder: "作者甲", mediaNames: ["video.m4a"] },
        { id: "other", title: "VIDEO 其他作者", authorFolder: "另一作者" },
    ].map((record, index) => ({platform: "bilibili", status: "completed", finishedAt: 1700000002000 - index, ...record}));
    const calls = [];
    let failAudio = true;
    const { window, element, click, show } = openPage(context, {
        snapshot: () => '{"busy":false}',
        downloadHistory: () => JSON.stringify(records),
        deleteDownloadHistory(id, deleteFiles) {
            calls.push([id, deleteFiles]);
            if (id === "audio" && failAudio) return "没有目录授权。";
            records.splice(records.findIndex(record => record.id === id), 1);
            return "";
        },
    });
    const closeDialog = action => new Promise(resolve => {
        window.addEventListener("popstate", resolve, { once: true });
        action();
    });
    const search = value => {
        element("historySearch").value = value;
        element("historySearch").dispatchEvent(new window.Event("input"));
    };
    const row = id => element("historyList").querySelector(`[data-history-id="${id}"]`);
    click("openHistory");
    click("historyBulkToggle");
    row("other").querySelector("[data-history-select]").click();
    assert.equal(element("historySelectionCount").textContent, "已选 1 条");
    element("historyAuthorFilterPicker").click();
    element("historyAuthorFilterOptions").querySelector('button[value="作者甲"]').click();
    assert.equal(row("other"), null);
    assert.equal(element("historySelectionCount").textContent, "已选 0 条");
    search("  video  ");
    assert.equal(row("other"), null);
    assert.equal(element("historyBulkDelete").disabled, true);
    click("historySelectAll");
    assert.equal(element("historySelectionCount").textContent, "已选 2 条");
    click("historySelectAll");
    assert.equal(element("historyBulkDelete").disabled, true);
    click("historySelectAll");
    click("historyBulkDelete");
    assert.match(element("historyDeleteTitle").textContent, /2 条/);
    assert.match(element("historyDeleteEffect").textContent, /只删除/);
    assert.equal(element("historyDeleteMediaNames").children.length, 2);
    await closeDialog(() => click("historyDeleteCancel"));
    assert.deepEqual(calls, []);

    click("historyDeleteFiles");
    click("historyBulkDelete");
    assert.deepEqual(Array.from(element("historyDeleteMediaNames").children, item => item.textContent), [
        "VIDEO 主文件", "VIDEO 主文件 · video.mp4", "VIDEO 主文件 · video.webp",
        "Video 音频", "Video 音频 · video.m4a",
    ]);
    assert.match(element("historyDeleteEffect").textContent, /关联的本地文件/);
    await closeDialog(() => click("historyDeleteConfirm"));
    assert.deepEqual(calls, [["main", true], ["audio", true]]);
    assert.equal(row("main"), null);
    assert.equal(row("audio").querySelector("[data-history-select]").checked, true);
    assert.match(element("historyNote").textContent, /1 条未能删除.*没有目录授权/);
    failAudio = false;
    search("音频");
    click("historyBulkDelete");
    await closeDialog(() => click("historyDeleteConfirm"));
    assert.equal(show("historyEmpty"), true);
    assert.equal(element("historyEmpty").textContent, "没有符合筛选条件的下载记录。");
    search("");
    assert.ok(row("other"));
    assert.deepEqual(calls, [["main", true], ["audio", true], ["audio", true]]);
});

test("逐条删除列出媒体和附件，重试时只列出剩余文件，离开历史后关闭本地文件删除", { timeout: 4000 }, async context => {
    const records = [
        { id: "dual", platform: "youtube", title: "<示例音画>", outputMode: "video-and-audio", status: "completed",
          finishedAt: 1700000002000, hasMainFile: true, hasAudioFile: true, mediaNames: ["示例.mp4", "<示例>.opus"],
          attachmentNames: ["示例.webp", "示例.zh-Hans.srt", "<示例>.auto.en.srt"] },
        { id: "failed", platform: "bilibili", title: "解析失败", status: "failed", finishedAt: 1700000001000 },
        { id: "old", platform: "bilibili", title: "旧下载", status: "completed", finishedAt: 1700000000000 },
    ];
    const calls = [];
    const { window, element, show, click, refresh } = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        downloadHistory: () => JSON.stringify(records),
        playHistoryAudio: () => "",
        openHistoryVideoLocation: () => "",
        deleteDownloadHistory(id, deleteFiles) {
            calls.push([id, deleteFiles]);
            const index = records.findIndex(record => record.id === id);
            if (id === "dual" && deleteFiles) {
                if (records[index].hasMainFile) {
                    records[index] = { ...records[index], hasMainFile: false, mediaNames: ["<示例>.opus"] };
                    return "无法删除独立音频。";
                }
                if (records[index].hasAudioFile) {
                    records[index] = { ...records[index], hasAudioFile: false,
                        mediaNames: [], attachmentNames: ["<示例>.auto.en.srt"] };
                    return "无法删除字幕。";
                }
            }
            records.splice(index, 1);
            return "";
        },
    });
    const away = async action => {
        const navigated = new Promise(resolve => window.addEventListener("popstate", resolve, { once: true }));
        action();
        await navigated;
    };
    const row = id => element("historyList").querySelector(`[data-history-id="${id}"]`);
    const remove = id => row(id).querySelector("[data-history-delete]");
    const dialog = element("historyDeleteDialog");
    const mode = element("historyDeleteFiles");
    const files = element("historyDeleteMediaNames");
    const effect = element("historyDeleteEffect");
    const fileNames = () => Array.from(files.children, file => file.textContent);

    click("openHistory");
    assert.equal(show("historyDeleteFilesOption"), true);
    assert.equal(mode.checked, false);
    remove("old").click();
    assert.equal(dialog.open, true);
    assert.equal(window.document.activeElement, element("historyDeleteCancel"));
    assert.equal(element("historyDeleteTitle").textContent, "旧下载");
    assert.match(element("historyDeleteMetadata").textContent, /B 站/);
    assert.match(effect.textContent, /只删除.*记录/);
    assert.equal(files.hidden, true);
    assert.deepEqual(calls, []);
    await away(() => window.history.back());
    assert.equal(dialog.open, false);
    assert.equal(window.document.activeElement, remove("old"));
    assert.deepEqual(calls, []);

    remove("old").click();
    await away(() => click("historyDeleteConfirm"));
    assert.equal(row("old"), null);
    assert.deepEqual(calls, [["old", false]]);

    mode.click();
    remove("dual").click();
    assert.equal(element("historyDeleteTitle").textContent, "<示例音画>");
    assert.deepEqual(fileNames(), ["示例.mp4", "<示例>.opus", "示例.webp", "示例.zh-Hans.srt", "<示例>.auto.en.srt"]);
    assert.match(effect.textContent, /关联的本地文件/);
    assert.equal(files.querySelector("img, script"), null);
    await away(() => click("historyDeleteCancel"));
    assert.deepEqual(calls, [["old", false]]);

    remove("dual").click();
    await away(() => click("historyDeleteConfirm"));
    assert.equal(row("dual").querySelector("[data-history-play]").hidden, true);
    assert.equal(row("dual").querySelector("[data-history-audio]").hidden, false);
    assert.equal(row("dual").querySelector("[data-history-location]").hidden, false);
    assert.equal(row("dual").querySelector(".note").textContent, "无法删除独立音频。");
    refresh();
    assert.equal(element("historyNote").textContent, "无法删除独立音频。");
    remove("dual").click();
    assert.deepEqual(fileNames(), ["<示例>.opus", "示例.webp", "示例.zh-Hans.srt", "<示例>.auto.en.srt"]);
    await away(() => click("historyDeleteConfirm"));
    assert.equal(row("dual").querySelector("[data-history-audio]").hidden, true);
    assert.equal(row("dual").querySelector(".note").textContent, "无法删除字幕。");
    remove("dual").click();
    assert.deepEqual(fileNames(), ["<示例>.auto.en.srt"]);
    assert.match(effect.textContent, /关联的本地文件/);
    await away(() => click("historyDeleteConfirm"));
    assert.equal(row("dual"), null);
    assert.equal(element("historyNote").textContent, "");

    remove("failed").click();
    assert.match(effect.textContent, /只删除.*记录/);
    await away(() => click("historyDeleteCancel"));
    assert.equal(mode.checked, true);
    await away(() => click("openSettings"));
    click("openHistory");
    assert.equal(mode.checked, false);
    remove("failed").click();
    await away(() => click("historyDeleteConfirm"));
    assert.equal(show("historyEmpty"), true);
    assert.deepEqual(calls, [["old", false], ["dual", true], ["dual", true], ["dual", true], ["failed", false]]);
});

