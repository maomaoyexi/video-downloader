import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { Window } from "happy-dom";

const html = await readFile(new URL("../app/src/main/assets/index.html", import.meta.url), "utf8");

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

    const intervals = new Map();
    let nextInterval = 0;
    window.setInterval = callback => {
        const id = ++nextInterval;
        intervals.set(id, callback);
        return id;
    };
    window.clearInterval = id => intervals.delete(id);
    if (downloader) window.Downloader = downloader;
    window.document.write(html);
    window.document.close();

    return {
        window,
        element: id => window.document.getElementById(id),
        tick: () => {
            for (const callback of intervals.values()) callback();
        },
    };
}

test("进度卡显示速度和剩余时间，下载完成后可播放和打开文件位置", context => {
    let state = { phase: "等待添加任务", detail: "等待下载", percent: -1, busy: false, canPlay: false };
    let clicks = 0;
    let locationOpens = 0;
    const page = openPage(context, {
        snapshot: () => JSON.stringify(state),
        playVideo: () => { clicks += 1; },
        openVideoLocation: () => ++locationOpens === 1 ? "视频文件已删除或已移动。" : "",
    });
    assert.equal(page.element("detail").textContent, "等待下载");
    const task = page.element("task");
    const stop = page.element("cancel");
    assert.equal(task.hidden, true, "首次打开应隐藏空任务卡");
    assert.equal(stop.hidden, true, "空闲时应隐藏停止操作");
    const play = page.element("playVideo");
    assert.ok(play, "任务卡缺少播放视频按钮");
    assert.equal(play.hidden, true, "初始状态应隐藏播放按钮");
    const location = page.element("openVideoLocation");
    assert.equal(location.hidden, true);
    const speed = page.element("speed");
    const eta = page.element("eta");
    assert.equal(speed.hidden, true);
    assert.equal(eta.hidden, true);

    state = { ...state, phase: "正在下载", busy: true, percent: 18.5, speed: "2.40 MiB/s", etaSeconds: 125 };
    page.tick();
    assert.equal(speed.hidden, false);
    assert.equal(speed.textContent, "2.40 MiB/s");
    assert.equal(eta.hidden, false);
    assert.equal(eta.textContent, "预计剩余 2 分 5 秒");
    assert.equal(page.element("percent").textContent, "18%");
    state.speed = "895.00 KiB/s";
    state.etaSeconds = -1;
    page.tick();
    assert.equal(speed.textContent, "895.00 KiB/s");
    assert.equal(eta.hidden, true);
    state.phase = "正在合并";
    state.etaSeconds = 25;
    page.tick();
    assert.equal(speed.hidden, true);
    assert.equal(speed.textContent, "");
    assert.equal(eta.hidden, true);

    state = { ...state, phase: "下载完成", detail: "已保存示例视频", percent: 100, busy: false, canPlay: true };
    page.tick();
    assert.equal(task.hidden, false, "完成后应显示任务卡");
    assert.equal(play.hidden, false, "原生完成状态应显示播放按钮");
    assert.equal(play.disabled, false, "完成状态应允许点击播放");
    assert.equal(play.textContent, "播放视频");
    play.click();
    assert.equal(clicks, 1, "点击一次应调用原生播放一次");
    state.audioOnly = true;
    page.tick();
    assert.equal(play.textContent, "播放音频");
    play.click();
    assert.equal(clicks, 2);
    assert.equal(location.hidden, false);
    location.click();
    assert.equal(locationOpens, 1);
    const locationNote = page.element("videoLocationNote");
    assert.match(locationNote.textContent, /已删除或已移动/);
    page.tick();
    assert.match(locationNote.textContent, /已删除或已移动/);
    location.click();
    assert.equal(locationOpens, 2);
    assert.equal(locationNote.textContent, "");

    for (const phase of ["正在下载", "下载失败", "已取消"]) {
        state = { phase, detail: phase, percent: -1, busy: phase === "正在下载", canPlay: false };
        page.tick();
        assert.equal(task.hidden, false, phase + "时应显示任务卡");
        assert.equal(stop.hidden, !state.busy, "停止操作只在任务运行时显示");
        assert.equal(page.element("start").hidden, state.busy, "开始按钮只在空闲时显示");
        assert.equal(play.hidden, true, phase + "时应隐藏播放按钮");
        assert.equal(location.hidden, true);
        assert.equal(speed.hidden, true);
    }
});

test("普通浏览器模拟完成后仍隐藏播放按钮", context => {
    const page = openPage(context);
    assert.equal(page.element("playVideo")?.hidden ?? true, true, "预览初始状态应隐藏播放按钮");

    const youtube = page.element("youtubeChip");
    const bilibili = page.element("biliChip");
    assert.equal(youtube.getAttribute("aria-current"), "false");
    assert.equal(bilibili.getAttribute("aria-current"), "false");
    page.element("example").click();
    assert.equal(youtube.getAttribute("aria-current"), "true", "应高亮示例链接所属平台");
    assert.equal(bilibili.getAttribute("aria-current"), "false");
    page.element("start").click();
    for (let step = 0; step < 20; step += 1) page.tick();

    assert.equal(page.element("phase").textContent, "模拟完成");
    assert.equal(page.element("playVideo")?.hidden ?? true, true, "浏览器模拟完成应隐藏播放按钮");
    assert.equal(page.element("openVideoLocation").hidden, true);
});

test("清除视频链接会清除校验提示和平台高亮，下载中禁止清除", context => {
    let copied = "无效链接";
    let busy = false;
    const page = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy }),
        clipboardText: () => copied,
    });
    const clear = page.element("clearUrl");
    const input = page.element("url");
    assert.equal(clear.disabled, true);

    page.element("paste").click();
    page.element("start").click();
    assert.notEqual(page.element("formNote").textContent, "");
    clear.click();
    assert.equal(input.value, "");
    assert.equal(page.element("formNote").textContent, "");

    copied = "https://youtu.be/jNQXAC9IVRw";
    page.element("paste").click();
    const youtube = page.element("youtubeChip");
    assert.equal(youtube.getAttribute("aria-current"), "true");
    busy = true;
    page.tick();
    assert.equal(clear.disabled, true);
    busy = false;
    page.tick();
    clear.click();
    assert.equal(input.value, "");
    assert.equal(youtube.getAttribute("aria-current"), "false");
    assert.equal(clear.disabled, true);
});

test("视频画质和仅音频选项将对应的参数传给安卓桥接", context => {
    const heights = [];
    const page = openPage(context, {
        snapshot: () => JSON.stringify({
            phase: "等待添加任务", detail: "", percent: -1, busy: false,
        }),
        start: (_url, height) => {
            heights.push(height);
            return "";
        },
    });
    const start = page.element("start");
    const picker = page.element("resolutionPicker");
    const summary = page.element("resolutionSummary");
    const value = page.element("resolutionValue");
    const choices = page.element("downloadForm").querySelectorAll("[data-height]");
    page.element("url").value = "https://youtu.be/jNQXAC9IVRw";

    assert.equal(picker.open, false, "首次打开时应收起分辨率选项");
    assert.equal(value.textContent, "自动");
    start.click();
    assert.deepEqual(Array.from(choices, button => button.textContent), [
        "自动", "最高", "8K", "4K", "2K", "1080p60", "1080p", "720p", "480p", "仅音频",
    ]);
    for (const button of choices) {
        summary.click();
        assert.equal(picker.open, true, "点击当前档位应展开选项");
        button.click();
        assert.equal(picker.open, false, "选中档位后应收起选项");
        assert.equal(value.textContent, button.textContent);
        start.click();
    }
    assert.deepEqual(heights, [0, 0, -1, 4320, 2160, 1440, -2, 1080, 720, 480, -3]);
});

test("仅音频忽略字幕，切回视频后恢复字幕选择，下载中锁定选项", context => {
    const url = "https://youtu.be/jNQXAC9IVRw";
    const started = [];
    let busy = false;
    const page = openPage(context, {
        snapshot: () => JSON.stringify({ phase: busy ? "正在下载" : "等待添加任务", detail: "", percent: -1, busy }),
        start: (...args) => {
            started.push(args);
            return "";
        },
    });
    const value = page.element("resolutionValue");
    const subtitles = page.element("downloadSubtitles");
    const audio = page.element("audioOnlyChoice");
    const start = page.element("start");
    page.element("url").value = url;

    page.element("resolutionSummary").click();
    assert.equal(subtitles.checked, false);
    subtitles.click();
    assert.equal(value.textContent, "自动 · 字幕");
    start.click();

    busy = true;
    page.tick();
    assert.equal(subtitles.disabled, true);
    assert.equal(audio.disabled, true);
    busy = false;
    page.tick();
    audio.click();
    assert.equal(value.textContent, "仅音频");
    assert.equal(page.element("subtitleOption").hidden, true);
    assert.equal(subtitles.disabled, true);
    start.click();

    page.element("resolutionSummary").click();
    page.element("downloadForm").querySelector('[data-height="720"]').click();
    assert.equal(page.element("subtitleOption").hidden, false);
    assert.equal(subtitles.checked, true);
    assert.equal(subtitles.disabled, false);
    assert.equal(value.textContent, "720p · 字幕");
    start.click();
    assert.deepEqual(started, [
        [url, 0, false, "", "", true, 0, "mp4", "auto", "http", 1],
        [url, -3, false, "", "", false, 0, "mp4", "auto", "http", 1],
        [url, 720, false, "", "", true, 0, "mp4", "auto", "http", 1],
    ]);
});

test("TXT 导入保留旧链接，忽略注释，并在校验后追加", context => {
    const youtube = "https://youtu.be/jNQXAC9IVRw";
    const bilibili = "https://www.bilibili.com/video/av114868162141203";
    let importState = { revision: 0, busy: false, text: "", message: "" };
    let starts = 0;
    const page = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        importLinks: () => { importState.busy = true; },
        linksImportState: () => JSON.stringify(importState),
        start: () => { starts++; return ""; },
    });
    const input = page.element("url");
    const button = page.element("importLinks");
    const note = page.element("linksImportNote");
    const start = page.element("start");
    assert.equal(button.hidden, false);
    input.value = youtube;
    button.click();
    assert.equal(start.disabled, true);
    assert.equal(button.disabled, true);
    importState = { revision: 1, busy: false, text: `# 示例\r\n  ${bilibili} \r\n`, message: "" };
    page.tick();
    assert.equal(input.value, `${youtube}\n${bilibili}`);
    assert.match(note.textContent, /已导入 1 条/);
    page.tick();
    assert.equal(input.value, `${youtube}\n${bilibili}`, "同一导入结果只处理一次");
    assert.equal(starts, 0, "导入后由用户确认是否开始任务");
    assert.equal(start.disabled, false);

    button.click();
    importState = { revision: 2, busy: false, text: "# 注释\n错误内容", message: "" };
    page.tick();
    assert.match(note.textContent, /第 2 行/);
    assert.equal(input.value, `${youtube}\n${bilibili}`);
    button.click();
    importState = { revision: 3, busy: false, text: Array(19).fill(bilibili).join("\n"), message: "" };
    page.tick();
    assert.match(note.textContent, /20 条/);
    assert.equal(input.value, `${youtube}\n${bilibili}`);
    button.click();
    importState = { revision: 4, busy: false, text: "", message: "" };
    page.tick();
    assert.equal(note.textContent, "");
    assert.equal(input.value, `${youtube}\n${bilibili}`);
});

test("批量链接按行校验并一次提交，任务卡显示队列进度和结果", context => {
    const youtube = "https://youtu.be/jNQXAC9IVRw";
    const bilibili = "https://www.bilibili.com/video/av114868162141203";
    const accepted = [];
    let stopCount = 0;
    let state = { phase: "等待添加任务", detail: "", percent: -1, busy: false };
    const page = openPage(context, {
        snapshot: () => JSON.stringify(state),
        start: (...args) => {
            accepted.push(args);
            state = { ...state, phase: "正在解析", busy: true, batchIndex: 1, batchTotal: 2 };
            return "";
        },
        cancel: () => {
            stopCount++;
            state = { ...state, busy: false, phase: "已取消", batchStopped: true };
        },
    });
    const input = page.element("url");
    const start = page.element("start");
    input.value = youtube + "\n\n无效链接";
    start.click();
    assert.equal(accepted.length, 0, "有无效行时整批不得启动");
    assert.match(page.element("formNote").textContent, /第\s*3\s*行/);

    input.value = Array(21).fill(youtube).join("\n");
    start.click();
    assert.equal(accepted.length, 0);
    assert.match(page.element("formNote").textContent, /20/);

    input.value = " " + youtube + "\n\n " + bilibili + " ";
    input.dispatchEvent(new page.window.Event("input"));
    assert.equal(page.element("youtubeChip").getAttribute("aria-current"), "true");
    assert.equal(page.element("biliChip").getAttribute("aria-current"), "true");
    const enter = new page.window.KeyboardEvent("keydown", { key: "Enter", cancelable: true });
    input.dispatchEvent(enter);
    assert.equal(enter.defaultPrevented, false, "普通回车应允许换行");
    assert.equal(accepted.length, 0);

    page.element("downloadSubtitles").click();
    start.click();
    assert.equal(accepted.length, 1);
    assert.deepEqual(accepted[0], [input.value, 0, false, "", "", true, 0, "mp4", "auto", "http", 1]);
    assert.match(page.element("batchPosition").textContent, /1\s*\/\s*2/);
    assert.match(page.element("cancel").textContent, /停止队列/);

    state = { ...state, batchIndex: 2, batchCompleted: 1, canPlay: true };
    page.tick();
    assert.match(page.element("batchPosition").textContent, /2\s*\/\s*2/);
    page.element("cancel").click();
    assert.equal(stopCount, 1);
    assert.match(page.element("batchSummary").textContent, /(?:完成|成功)\s*1/);
    assert.equal(page.element("playVideo").hidden, false);
});

test("只在队列允许时跳过当前条，结算区分跳过与未开始", context => {
    let state = { phase: "正在下载", detail: "", percent: 42, busy: true, batchTotal: 3, batchIndex: 1, canSkip: true };
    let skips = 0;
    const page = openPage(context, {
        snapshot: () => JSON.stringify(state),
        skipCurrent: () => {
            skips++;
            state = { ...state, phase: "正在跳过", percent: -1, canSkip: false };
        },
    });
    const skip = page.element("skipCurrent");
    assert.equal(skip.hidden, false);
    skip.click();
    assert.equal(skips, 1);
    assert.equal(skip.hidden, true);
    state = { ...state, batchIndex: 3, batchSkipped: 1, batchCompleted: 1, batchFailed: 0, canSkip: false };
    page.tick();
    assert.equal(skip.hidden, true);
    state = { ...state, busy: false, phase: "下载完成", batchCompleted: 2 };
    page.tick();
    assert.equal(page.element("phase").textContent, "队列已结束");
    assert.match(page.element("batchSummary").textContent, /成功 2 · 失败 0 · 跳过 1/);
    state = { ...state, batchStopped: true, batchCompleted: 1 };
    page.tick();
    assert.match(page.element("batchSummary").textContent, /跳过 1 · 未完成 1 条/);
});

test("队列详情按原顺序更新每条任务状态和链接", context => {
    const urls = ["https://youtu.be/jNQXAC9IVRw", "https://www.bilibili.com/video/av114868162141203?p=2"];
    let state = {
        phase: "正在下载", detail: "", percent: 42, busy: true, batchTotal: 2, batchIndex: 1,
        batchItems: [{ url: urls[0], status: "downloading" }, { url: urls[1], status: "waiting" }],
    };
    const page = openPage(context, { snapshot: () => JSON.stringify(state) });
    const details = page.element("batchDetails");
    assert.equal(details.hidden, false);
    assert.equal(details.open, false);
    page.element("batchDetailsSummary").click();
    assert.equal(details.open, true);
    const list = page.element("batchList");
    const labels = () => Array.from(list.querySelectorAll(".batch-status"), item => item.textContent);
    assert.deepEqual(labels(), ["进行中", "等待中"]);
    assert.deepEqual(Array.from(list.querySelectorAll(".batch-url"), item => item.textContent), urls);

    const firstRow = list.firstElementChild;
    page.tick();
    assert.equal(list.firstElementChild, firstRow, "状态相同的轮询应保留队列列表节点");
    state.batchItems[0].status = "completed";
    state.batchItems[1].status = "skipped";
    page.tick();
    assert.equal(details.open, true);
    assert.deepEqual(labels(), ["已完成", "已跳过"]);
    state = { ...state, batchTotal: 1, batchItems: [state.batchItems[0]] };
    page.tick();
    assert.equal(details.hidden, true);
    assert.equal(details.open, false);
});

function openCollectionPage(context) {
    const inspections = [];
    const downloads = [];
    let status = { status: "idle" };
    let cancellations = 0;
    const page = openPage(context, {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        downloadDefaults: () => JSON.stringify({ height: 0, subtitles: false, rateLimitKiB: 0 }),
        saveDownloadDefaults: () => "",
        inspectCollection: (...args) => {
            inspections.push(args);
            status = { status: "loading" };
            return "";
        },
        collectionState: () => JSON.stringify(status),
        cancelCollection: () => {
            cancellations++;
            status = { status: "idle" };
        },
        start: (...args) => {
            downloads.push(args);
            return "";
        },
    });
    return {
        ...page,
        inspections,
        downloads,
        cancellations: () => cancellations,
        result: value => {
            status = value;
            page.tick();
        },
        submit: value => {
            page.element("url").value = value;
            page.element("start").click();
        },
    };
}

test("B 站多 P 初始不选，按分 P 顺序提交，单次限选 20 条", context => {
    const page = openCollectionPage(context);
    const url = "https://www.bilibili.com/video/BV1Ni4y1F7wa";
    page.element("proxyEnabled").checked = true;
    page.element("proxyAddress").value = "127.0.0.1";
    page.element("proxyPort").value = "7890";
    page.element("proxyScheme").value = "socks5";
    page.element("fragments").value = "5";
    page.element("videoContainer").value = "mkv";
    page.element("videoCodec").value = "av1";
    page.element("rateLimit").value = "2048";
    page.element("downloadForm").querySelector('[data-height="1080"]').click();
    page.element("downloadSubtitles").click();
    page.submit(url);
    assert.deepEqual(page.inspections, [[url, true, "127.0.0.1", "7890", "socks5"]]);
    assert.equal(page.element("collectionDialog").open, true);
    assert.equal(page.element("collectionProgress").hidden, false);
    assert.equal(page.downloads.length, 0);

    const entries = Array.from({ length: 21 }, (_, index) => ({
        ordinal: index + 1,
        title: index === 0 ? "<视频标题>" : `第 ${index + 1} P`,
        url: url + "?p=" + (index + 1),
    }));
    page.result({ status: "ready", title: "合集示例", entries: [...entries].reverse(), truncated: true });
    assert.equal(page.element("collectionList").querySelectorAll("input").length, 21);
    assert.equal(page.element("collectionStatus").textContent, "合集示例");
    assert.match(page.element("collectionLimit").textContent, /100/);
    assert.match(page.element("collectionList").textContent, /<视频标题>/);
    assert.equal(page.element("collectionStart").disabled, true);
    assert.equal(page.element("collectionSingle").hidden, true);
    for (let index = 20; index >= 1; index--) page.element(`collectionEntry${index}`).click();
    assert.match(page.element("collectionCount").textContent, /20\s*\/\s*20/);
    assert.equal(page.element("collectionEntry21").disabled, true);
    page.element("collectionEntry20").click();
    assert.equal(page.element("collectionEntry21").disabled, false);
    page.element("collectionEntry21").click();
    page.element("collectionStart").click();
    assert.equal(page.element("collectionDialog").open, false);
    const picked = [...entries.slice(0, 19), entries[20]];
    assert.deepEqual(page.downloads, [[picked.map(entry => entry.url).join("\n"), 1080, true, "127.0.0.1", "7890",
        true, 2048, "mkv", "av1", "socks5", 5]]);
    assert.equal(page.cancellations(), 1);
});

test("YouTube 播放列表需单独提交，读取失败可重试并选择独立视频", context => {
    const page = openCollectionPage(context);
    const url = "https://www.youtube.com/playlist?list=PLplayback123";
    const video = "https://www.youtube.com/watch?v=jNQXAC9IVRw";
    page.submit(video + "\n" + url);
    assert.match(page.element("formNote").textContent, /第 2 行.*单独提交/);
    assert.equal(page.inspections.length, 0);
    assert.equal(page.downloads.length, 0);

    page.submit(url);
    assert.equal(page.inspections.length, 1);
    page.result({ status: "error", message: "暂时无法访问该播放列表。" });
    assert.equal(page.element("collectionError").textContent, "暂时无法访问该播放列表。");
    assert.equal(page.element("collectionSingle").hidden, true);
    page.element("collectionRetry").click();
    assert.equal(page.inspections.length, 2);
    page.result({ status: "ready", entries: [{ ordinal: 1, title: "公开视频", url: video }] });
    page.element("collectionEntry1").click();
    page.element("collectionStart").click();
    assert.deepEqual(page.downloads.map(args => args[0]), [video]);
});

test("B 站单 P 自动下载，显式分 P 不做预检，带列表的单视频保留单条入口", context => {
    const page = openCollectionPage(context);
    const url = "https://www.bilibili.com/video/BV1Ni4y1F7wa";
    page.element("downloadSubtitles").click();
    page.submit(url + "?p=2");
    assert.equal(page.inspections.length, 0);
    page.element("audioOnlyChoice").click();
    page.submit(url);
    page.result({ status: "single" });
    assert.equal(page.element("collectionDialog").open, false);

    const watch = "https://youtu.be/jNQXAC9IVRw?list=PLplayback123";
    page.submit(watch);
    page.result({ status: "error" });
    assert.equal(page.element("collectionSingle").hidden, false);
    page.element("collectionSingle").click();
    assert.deepEqual(page.downloads, [
        [url + "?p=2", 0, false, "", "", true, 0, "mp4", "auto", "http", 1],
        [url, -3, false, "", "", false, 0, "mp4", "auto", "http", 1],
        [watch, -3, false, "", "", false, 0, "mp4", "auto", "http", 1],
    ]);
});

test("返回键关闭分集列表并丢弃已取消的解析结果", async context => {
    const page = openCollectionPage(context);
    const url = "https://b23.tv/example";
    page.submit(url);
    assert.equal(page.element("collectionDialog").open, true);
    await new Promise(resolve => {
        page.window.addEventListener("popstate", resolve, { once: true });
        page.window.history.back();
    });
    assert.equal(page.element("collectionDialog").open, false);
    assert.equal(page.cancellations(), 1);
    page.result({ status: "single" });
    assert.equal(page.downloads.length, 0);
    page.submit("https://youtu.be/jNQXAC9IVRw");
    assert.equal(page.downloads.length, 1);
});

test("B 站 bili2233.cn 短链可从分集解析和批量下载入口提交", context => {
    const page = openCollectionPage(context);
    const url = "https://bili2233.cn/HnN7afH";
    const input = page.element("url");
    input.value = url;
    input.dispatchEvent(new page.window.Event("input"));
    assert.equal(page.element("biliChip").getAttribute("aria-current"), "true");
    page.submit(url);
    assert.equal(page.element("formNote").textContent, "");
    assert.equal(page.inspections[0]?.[0], url);
    page.result({ status: "single" });
    assert.equal(page.downloads[0]?.[0], url);

    const batch = url + "\nhttps://youtu.be/jNQXAC9IVRw";
    page.submit(batch);
    assert.equal(page.downloads[1]?.[0], batch);

    page.submit("https://bili2233.cn/");
    assert.match(page.element("formNote").textContent, /短链接不完整/);
    page.submit("https://bili2233.cn.example/HnN7afH");
    assert.match(page.element("formNote").textContent, /安卓端支持/);
    assert.equal(page.inspections.length, 1);
    assert.equal(page.downloads.length, 2);
});
