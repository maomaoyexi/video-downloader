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
    let audioOpens = 0;
    const page = openPage(context, {
        snapshot: () => JSON.stringify(state),
        playVideo: () => { clicks += 1; },
        playCompanionAudio: () => ++audioOpens === 1 ? "独立音频文件已删除或已移动。" : "",
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
    const companion = page.element("playCompanionAudio");
    assert.equal(companion.hidden, true);
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
    assert.equal(companion.hidden, true);
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

    state = { ...state, audioOnly: false, outputMode: "silent-video-and-audio", hasAudioFile: true };
    page.tick();
    assert.equal(play.textContent, "播放无声视频");
    assert.equal(companion.hidden, false);
    companion.click();
    assert.equal(audioOpens, 1);
    assert.match(locationNote.textContent, /独立音频文件已删除或已移动/);
    companion.click();
    assert.equal(audioOpens, 2);
    assert.equal(locationNote.textContent, "");

    state.canPlay = false;
    page.tick();
    assert.equal(play.hidden, true);
    assert.equal(companion.hidden, false);
    assert.equal(location.hidden, false);

    for (const phase of ["正在下载", "下载失败", "已取消"]) {
        state = { phase, detail: phase, percent: -1, busy: phase === "正在下载", canPlay: false };
        page.tick();
        assert.equal(task.hidden, false, phase + "时应显示任务卡");
        assert.equal(stop.hidden, !state.busy, "停止操作只在任务运行时显示");
        assert.equal(page.element("start").hidden, state.busy, "开始按钮只在空闲时显示");
        assert.equal(play.hidden, true, phase + "时应隐藏播放按钮");
        assert.equal(companion.hidden, true, phase + "时应隐藏独立音频按钮");
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

test("所有视频画质可从折叠菜单选取并传给安卓桥接", context => {
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
    const downloadSummary = page.element("resolutionSummary");
    const picker = page.element("qualityPicker");
    const summary = page.element("qualitySummary");
    const value = page.element("resolutionValue");
    const choices = page.element("downloadForm").querySelectorAll("[data-height]");
    page.element("url").value = "https://youtu.be/jNQXAC9IVRw";

    assert.equal(picker.open, false, "首次打开时应收起画质选项");
    assert.equal(value.textContent, "自动");
    start.click();
    assert.deepEqual(Array.from(choices, button => button.textContent), [
        "自动", "最高", "8K", "4K", "2K", "1080p60", "1080p", "720p", "480p",
    ]);
    downloadSummary.click();
    for (const button of choices) {
        summary.click();
        assert.equal(picker.open, true, "点击画质档位应展开选项");
        button.click();
        assert.equal(picker.open, false, "选中档位后应收起画质选项");
        assert.equal(downloadSummary.closest("details").open, true, "选中档位后仍保留下载选项面板");
        assert.equal(value.textContent, button.textContent);
        start.click();
    }
    assert.deepEqual(heights, [0, 0, -1, 4320, 2160, 1440, -2, 1080, 720, 480]);
});

test("四种音画输出提交独立模式，音频模式保留原画质及字幕选择", context => {
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
    const cover = page.element("downloadCover");
    const audioPicker = page.element("audioFormatPicker");
    const audioSummary = page.element("audioFormatSummary");
    const outputPicker = page.element("outputModePicker");
    const outputSummary = page.element("outputModeSummary");
    const outputValue = page.element("outputModeValue");
    const qualityPicker = page.element("qualityPicker");
    const qualitySummary = page.element("qualitySummary");
    const moreOptionsPicker = page.element("moreOptionsPicker");
    const moreOptionsSummary = page.element("moreOptionsSummary");
    const moreOptionsValue = page.element("moreOptionsValue");
    const chooseMode = mode => {
        outputSummary.click();
        assert.equal(outputPicker.open, true);
        const button = outputPicker.querySelector(`[data-output-mode="${mode}"]`);
        button.click();
        assert.equal(button.getAttribute("aria-pressed"), "true");
        assert.equal(outputPicker.open, false);
        assert.equal(page.window.document.activeElement, outputSummary);
    };
    const chooseFormat = format => {
        if (!moreOptionsPicker.open) moreOptionsSummary.click();
        audioSummary.click();
        assert.equal(audioPicker.open, true);
        const button = audioPicker.querySelector(`[data-audio-format="${format}"]`);
        button.click();
        assert.equal(button.getAttribute("aria-pressed"), "true");
        assert.equal(audioPicker.open, false);
        assert.equal(page.window.document.activeElement, audioSummary);
    };
    const chooseCodec = codec => {
      if (!moreOptionsPicker.open) moreOptionsSummary.click();
      const summary = page.element("videoCodecSummary");
      const picker = page.element("videoCodecPicker");
      summary.click();
      assert.equal(picker.open, true);
      const button = picker.querySelector(`[data-video-codec="${codec}"]`);
      button.click();
      assert.equal(button.getAttribute("aria-pressed"), "true");
      assert.equal(picker.open, false);
      assert.equal(page.window.document.activeElement, summary);
    };
    const start = page.element("start");
    page.element("url").value = url;

    assert.equal(outputPicker.open, false);
    assert.deepEqual(Array.from(outputPicker.querySelectorAll("[data-output-mode]"), button => button.textContent), [
        "带声音的视频", "只输出音频", "带声音的视频 + 独立音频", "无声视频 + 独立音频",
    ]);
    assert.equal(outputValue.textContent, "带声音的视频");
    assert.equal(page.element("outputModePicker").parentElement.className, "download-primary-options");
    assert.equal(page.element("qualityPicker").parentElement.className, "download-primary-options");
    assert.equal(audioPicker.hidden, true);
    assert.equal(cover.checked, false);
    assert.equal(moreOptionsValue.textContent, "默认");
    page.element("resolutionSummary").click();
    qualitySummary.click();
    qualityPicker.querySelector('[data-height="720"]').click();
    assert.equal(qualityPicker.open, false);
    assert.equal(page.window.document.activeElement, qualitySummary);
    assert.equal(page.element("qualityValue").textContent, "720p");
    assert.equal(subtitles.checked, false);
    moreOptionsSummary.click();
    subtitles.click();
    assert.equal(value.textContent, "720p");
    assert.equal(moreOptionsValue.textContent, "字幕");
    start.click();

    cover.click();
    assert.equal(value.textContent, "720p");
    assert.equal(moreOptionsValue.textContent, "字幕 · 封面");
    start.click();
    busy = true;
    page.tick();
    assert.equal(subtitles.disabled, true);
    assert.equal(cover.disabled, true);
    assert.equal(Array.from(outputPicker.querySelectorAll("button")).every(button => button.disabled), true);
    busy = false;
    page.tick();
    chooseMode("audio");
    assert.equal(value.textContent, "只输出音频");
    assert.equal(outputValue.textContent, "只输出音频");
    assert.equal(audioPicker.hidden, false);
    assert.equal(page.element("audioFormatValue").textContent, "M4A");
    assert.deepEqual(Array.from(audioPicker.querySelectorAll("button"), option => option.textContent),
        ["M4A", "FLAC", "Opus", "WAV"]);
    assert.equal(page.element("qualityChoices").hidden, true);
    assert.equal(qualityPicker.hidden, true);
    assert.equal(page.element("subtitleOption").hidden, true);
    assert.equal(subtitles.disabled, true);
    assert.equal(cover.disabled, false);
    chooseFormat("flac");
    assert.equal(page.element("audioFormatValue").textContent, "FLAC");
    start.click();

    chooseMode("video-and-audio");
    assert.equal(page.element("qualityChoices").hidden, false);
    assert.equal(qualityPicker.hidden, false);
    assert.equal(audioPicker.hidden, false);
    assert.equal(page.element("audioFormatValue").textContent, "FLAC");
    assert.equal(page.element("subtitleOption").hidden, false);
    assert.equal(subtitles.checked, true);
    assert.equal(subtitles.disabled, false);
    assert.equal(value.textContent, "视频 + 音频 · 720p");
    chooseFormat("opus");
    assert.equal(moreOptionsValue.textContent, "Opus · 字幕 · 封面");
    chooseCodec("av1");
    assert.equal(moreOptionsValue.textContent, "Opus · AV1 · 字幕 · 封面");
    start.click();
    chooseMode("silent-video-and-audio");
    assert.equal(audioPicker.hidden, false);
    assert.equal(value.textContent, "无声视频 + 音频 · 720p");
    chooseFormat("wav");
    start.click();
    chooseMode("video");
    assert.equal(audioPicker.hidden, true);
    chooseMode("audio");
    assert.equal(page.element("audioFormatValue").textContent, "WAV");
    assert.deepEqual(started, [
        [url, 720, false, "", "", true, 0, "mp4", "auto", "http", 1, "video", "m4a", false],
        [url, 720, false, "", "", true, 0, "mp4", "auto", "http", 1, "video", "m4a", true],
        [url, 720, false, "", "", false, 0, "mp4", "auto", "http", 1, "audio", "flac", true],
        [url, 720, false, "", "", true, 0, "mp4", "av1", "http", 1, "video-and-audio", "opus", true],
        [url, 720, false, "", "", true, 0, "mp4", "av1", "http", 1, "silent-video-and-audio", "wav", true],
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
    assert.deepEqual(accepted[0], [input.value, 0, false, "", "", true, 0, "mp4", "auto", "http", 1, "video", "m4a", false]);
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

test("任务卡分别显示输出项序号和队列条数", context => {
    let state = {
        phase: "正在下载", detail: "", percent: 42, speed: "825.00 KiB/s", busy: true, batchTotal: 2, batchIndex: 1,
        mediaStep: 1, mediaStepTotal: 3, mediaStepLabel: "视频",
    };
    const page = openPage(context, { snapshot: () => JSON.stringify(state) });
    const mediaPosition = page.element("mediaPosition");
    const batchPosition = page.element("batchPosition");
    assert.equal(mediaPosition.hidden, false);
    assert.equal(mediaPosition.textContent, "1/3 · 视频");
    assert.equal(page.element("progress").hidden, false);
    assert.equal(page.element("percent").textContent, "42%");
    assert.equal(page.element("speed").textContent, "825.00 KiB/s");
    assert.equal(batchPosition.hidden, false);
    assert.equal(batchPosition.textContent, "第 1 / 2 条");

    state = { ...state, phase: "正在提取音频", percent: -1, mediaStep: 2, mediaStepLabel: "独立音频" };
    page.tick();
    assert.equal(mediaPosition.hidden, false);
    assert.equal(mediaPosition.textContent, "2/3 · 独立音频");
    assert.equal(page.element("progress").hidden, false);
    assert.equal(page.element("progress").hasAttribute("value"), false);
    assert.equal(page.element("speed").hidden, true);
    assert.equal(batchPosition.textContent, "第 1 / 2 条");

    state = { ...state, phase: "正在下载字幕", percent: 25, speed: "18.00 KiB/s", mediaStep: 3, mediaStepLabel: "字幕" };
    page.tick();
    assert.equal(mediaPosition.hidden, false);
    assert.equal(mediaPosition.textContent, "3/3 · 字幕");
    assert.equal(page.element("percent").textContent, "25%");
    assert.equal(page.element("speed").textContent, "18.00 KiB/s");
    assert.equal(batchPosition.textContent, "第 1 / 2 条");

    state = { ...state, phase: "正在解析", batchIndex: 2, mediaStep: 1, mediaStepLabel: "视频" };
    page.tick();
    assert.equal(mediaPosition.textContent, "1/3 · 视频");
    assert.equal(batchPosition.textContent, "第 2 / 2 条");

    state = { ...state, busy: false, phase: "下载完成", batchCompleted: 2, batchFailed: 0 };
    page.tick();
    assert.equal(mediaPosition.hidden, true);
    assert.equal(batchPosition.hidden, true);

    state = { ...state, busy: true, phase: "正在下载", batchTotal: 1, mediaStepTotal: 1, mediaStepLabel: "音频" };
    page.tick();
    assert.equal(mediaPosition.hidden, true);
    assert.equal(batchPosition.hidden, true);
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

function openCollectionPage(context, additionalBridge = {}) {
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
        ...additionalBridge,
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
    page.element("videoCodecPicker").querySelector('[data-video-codec="av1"]').click();
    page.element("rateLimit").value = "2048";
    page.element("downloadForm").querySelector('[data-height="1080"]').click();
    page.element("outputModePicker").querySelector('[data-output-mode="silent-video-and-audio"]').click();
    page.element("audioFormatPicker").querySelector('[data-audio-format="opus"]').click();
    page.element("downloadCover").click();
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
        true, 2048, "mp4", "av1", "socks5", 5, "silent-video-and-audio", "opus", true]]);
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
    page.element("outputModePicker").querySelector('[data-output-mode="audio"]').click();
    page.submit(url);
    page.result({ status: "single" });
    assert.equal(page.element("collectionDialog").open, false);

    const watch = "https://youtu.be/jNQXAC9IVRw?list=PLplayback123";
    page.submit(watch);
    page.result({ status: "error" });
    assert.equal(page.element("collectionSingle").hidden, false);
    page.element("collectionSingle").click();
    assert.deepEqual(page.downloads, [
        [url + "?p=2", 0, false, "", "", true, 0, "mp4", "auto", "http", 1, "video", "m4a", false],
        [url, 0, false, "", "", false, 0, "mp4", "auto", "http", 1, "audio", "m4a", false],
        [watch, 0, false, "", "", false, 0, "mp4", "auto", "http", 1, "audio", "m4a", false],
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

function openSubtitlePage(context) {
    const subtitleInspections = [];
    const subtitleDownloads = [];
    let subtitleState = { status: "idle" };
    let subtitleCancellations = 0;
    const page = openCollectionPage(context, {
        inspectSubtitles: (...args) => {
            subtitleInspections.push(args);
            subtitleState = { status: "loading" };
            return "";
        },
        subtitleState: () => JSON.stringify(subtitleState),
        cancelSubtitles: () => {
            subtitleCancellations++;
            subtitleState = { status: "idle" };
        },
        startWithSubtitles: (...args) => {
            subtitleDownloads.push(args);
            return "";
        },
    });
    page.element("downloadSubtitles").click();
    return {
        ...page,
        subtitleInspections,
        subtitleDownloads,
        subtitleCancellations: () => subtitleCancellations,
        subtitleResult: value => {
            subtitleState = value;
            page.tick();
        },
        searchSubtitles: value => {
            const search = page.element("subtitleSearch");
            search.value = value;
            search.dispatchEvent(new page.window.Event("input"));
        },
    };
}

test("人工和自动字幕可分别勾选，搜索语言时保留已选轨道", context => {
    const page = openSubtitlePage(context);
    const url = "https://youtu.be/jNQXAC9IVRw";
    page.element("proxyEnabled").checked = true;
    page.element("proxyAddress").value = "127.0.0.1";
    page.element("proxyPort").value = "7890";
    page.element("proxyScheme").value = "socks5";
    page.submit(url);
    assert.deepEqual(page.subtitleInspections, [[url, true, "127.0.0.1", "7890", "socks5"]]);
    assert.equal(page.element("subtitleProgress").hidden, false);
    page.subtitleResult({ status: "ready", tracks: [
        { language: "en", label: "英语", source: "manual" },
        { language: "en", label: "英语（自动生成）", source: "auto" },
        { language: "ja", label: "日语（自动翻译）", source: "auto" },
    ] });

    const list = page.element("subtitleList");
    const checks = Array.from(list.querySelectorAll("input"));
    assert.match(list.textContent, /人工字幕/);
    assert.match(list.textContent, /自动字幕/);
    assert.match(list.textContent, /自动生成/);
    assert.match(list.textContent, /自动翻译/);
    assert.equal(checks.length, 3);
    assert.ok(checks.every(check => !check.checked));
    assert.equal(page.element("subtitleStart").disabled, true);
    checks[0].click();
    page.searchSubtitles("JA");
    assert.deepEqual(checks.filter(check => !check.closest("[hidden]")), [checks[2]]);
    checks[2].click();
    page.searchSubtitles("英语");
    assert.deepEqual(checks.filter(check => !check.closest("[hidden]")), checks.slice(0, 2));
    assert.equal(checks[0].checked, true);
    checks[1].click();
    page.element("subtitleStart").click();

    assert.equal(page.element("subtitleDialog").open, false);
    assert.equal(page.downloads.length, 0);
    assert.deepEqual(page.subtitleDownloads, [[url, 0, true, "127.0.0.1", "7890", true,
        0, "mp4", "auto", "socks5", 1, "video", "m4a", false, JSON.stringify([
            { language: "en", source: "manual" }, { language: "en", source: "auto" },
            { language: "ja", source: "auto" },
        ])]]);
});

test("字幕目录读取失败可重试，无可用字幕仍可下载视频", context => {
    const page = openSubtitlePage(context);
    const url = "https://youtu.be/jNQXAC9IVRw";
    page.element("downloadCover").click();
    page.submit(url);
    page.subtitleResult({ status: "error", message: "字幕读取超时。" });
    assert.equal(page.element("subtitleError").textContent, "字幕读取超时。");
    assert.equal(page.element("subtitleRetry").hidden, false);
    assert.equal(page.element("subtitleSkip").hidden, false);
    assert.equal(page.downloads.length, 0);
    page.element("subtitleRetry").click();
    assert.equal(page.subtitleInspections.length, 2);
    assert.equal(page.element("subtitleProgress").hidden, false);
    assert.equal(page.element("subtitleError").textContent, "");
    page.subtitleResult({ status: "ready", tracks: [] });
    assert.match(page.element("subtitleStatus").textContent, /没有可下载的字幕/);
    assert.equal(page.element("subtitleStart").hidden, true);
    page.element("subtitleSkip").click();

    assert.deepEqual(page.downloads, [[url, 0, false, "", "", false, 0, "mp4", "auto", "http", 1, "video", "m4a", true]]);
    assert.equal(page.subtitleDownloads.length, 0);
    assert.equal(page.element("downloadSubtitles").checked, true);
});

test("单分集可以选择字幕，返回键取消读取并忽略迟到结果", async context => {
    const page = openSubtitlePage(context);
    const url = "https://www.bilibili.com/video/BV1ZMoeBPEqs";
    const part = url + "?p=2";
    const initialHistory = page.window.history.state;
    page.submit(url);
    page.result({ status: "ready", entries: [
        { ordinal: 1, title: "中文字幕", url: url + "?p=1" },
        { ordinal: 2, title: "日文原版", url: part },
    ] });
    page.element("collectionEntry2").click();
    page.element("collectionStart").click();
    assert.equal(page.element("collectionDialog").open, false);
    assert.equal(page.element("subtitleDialog").open, true);
    assert.equal(page.subtitleInspections[0]?.[0], part);
    await new Promise(resolve => {
        page.window.addEventListener("popstate", resolve, { once: true });
        page.window.history.back();
    });
    assert.equal(page.window.history.state, initialHistory);
    assert.equal(page.element("subtitleDialog").open, false);
    assert.equal(page.subtitleCancellations(), 1);
    page.subtitleResult({ status: "ready", tracks: [{ language: "ja", label: "日语", source: "manual" }] });
    assert.equal(page.subtitleDownloads.length, 0);
    assert.equal(page.downloads.length, 0);

    page.submit(part);
    assert.equal(page.subtitleInspections[1]?.[0], part);
    page.element("subtitleCancel").click();
    assert.equal(page.subtitleCancellations(), 2);
    assert.equal(page.element("subtitleDialog").open, false);
});

test("字幕最多选择 20 条，搜索隐藏的轨道仍计入上限", context => {
    const page = openSubtitlePage(context);
    page.submit("https://youtu.be/jNQXAC9IVRw");
    page.subtitleResult({ status: "ready", tracks: Array.from({ length: 21 }, (_, index) => ({
        language: `en-${index + 1}`, label: `英语 ${index + 1}`, source: "auto",
    })) });
    const checks = Array.from(page.element("subtitleList").querySelectorAll("input"));
    for (const check of checks.slice(0, 20)) check.click();
    page.searchSubtitles("en-21");
    assert.match(page.element("subtitleCount").textContent, /20\s*\/\s*20/);
    assert.equal(checks[20].disabled, true);
    page.searchSubtitles("en-20");
    checks[19].click();
    page.searchSubtitles("en-21");
    assert.equal(checks[20].disabled, false);
    checks[20].click();
    page.element("subtitleStart").click();
    const submitted = JSON.parse(page.subtitleDownloads[0].at(-1));
    assert.equal(submitted.length, 20);
    assert.deepEqual(submitted.at(-1), { language: "en-21", source: "auto" });
    assert.ok(!submitted.some(track => track.language === "en-20"));
});

test("批量下载沿用人工字幕，只输出音频时不读取字幕轨道", context => {
    const page = openSubtitlePage(context);
    const url = "https://youtu.be/jNQXAC9IVRw";
    const batch = url + "\nhttps://bili2233.cn/vaopxkP";
    page.submit(batch);
    assert.equal(page.subtitleInspections.length, 0);
    assert.equal(page.downloads[0][0], batch);
    assert.equal(page.downloads[0][5], true);

    page.element("outputModePicker").querySelector('[data-output-mode="audio"]').click();
    page.submit(url);
    assert.equal(page.subtitleInspections.length, 0);
    assert.equal(page.downloads[1][5], false);
    assert.equal(page.downloads[1][11], "audio");
});
