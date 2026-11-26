import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { Window } from "happy-dom";

const html = await readFile(new URL("../app/src/main/assets/index.html", import.meta.url), "utf8");
const initialDefaults = {
    height: 0, subtitles: false, rateLimitKiB: 0, videoContainer: "mp4", videoCodec: "auto", fragments: 1,
    outputMode: "video", audioFormat: "m4a", cover: false,
};

function presetBridge(initialPresets = [], savedDefaults = initialDefaults) {
    const named = new Map(initialPresets.map(preset => [preset.name, preset]));
    const defaultWrites = [];
    const presetWrites = [];
    const deletions = [];
    let defaults = savedDefaults;
    const bridge = {
        snapshot: () => JSON.stringify({ phase: "等待添加任务", detail: "", percent: -1, busy: false }),
        downloadDefaults: () => JSON.stringify(defaults),
        saveDownloadDefaults(height, subtitles, rateLimitKiB, videoContainer, videoCodec, fragments, outputMode, audioFormat, cover) {
            defaults = { height, subtitles, rateLimitKiB, videoContainer, videoCodec, fragments, outputMode, audioFormat, cover };
            defaultWrites.push(defaults);
            return "";
        },
        downloadPresets: () => JSON.stringify([...named.values()]),
        saveDownloadPreset(name, height, subtitles, rateLimitKiB, videoContainer, videoCodec, fragments, outputMode, audioFormat, cover) {
            const preset = { name, height, subtitles, rateLimitKiB, videoContainer, videoCodec, fragments, outputMode, audioFormat, cover };
            presetWrites.push(preset);
            named.set(name, preset);
            return "";
        },
        deleteDownloadPreset(name) {
            deletions.push(name);
            named.delete(name);
            return "";
        },
    };
    return { bridge, named, defaultWrites, presetWrites, deletions };
}

function openPage(context, bridge) {
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
    window.setInterval = () => 0;
    window.Downloader = bridge;
    window.document.write(html);
    window.document.close();
    const element = id => window.document.getElementById(id);
    return {
        element,
        show: id => !element(id).closest("[hidden], [inert]"),
        click: id => element(id).click(),
        namePreset(name) {
            const input = element("downloadPresetName");
            input.value = name;
            input.dispatchEvent(new window.Event("input", { bubbles: true }));
        },
    };
}

test("设置顶栏可保存命名预设，重新打开后可加载并记住", context => {
    const { bridge, named, defaultWrites, presetWrites } = presetBridge();
    const page = openPage(context, bridge);
    const { element, show, click } = page;

    click("resolutionSummary");
    click("qualitySummary");
    element("qualityPicker").querySelector('[data-height="720"]').click();
    click("outputModeSummary");
    element("outputModePicker").querySelector('[data-output-mode="video-and-audio"]').click();
    click("moreOptionsSummary");
    click("audioFormatSummary");
    element("audioFormatPicker").querySelector('[data-audio-format="opus"]').click();
    click("videoCodecSummary");
    element("videoCodecPicker").querySelector('[data-video-codec="av1"]').click();
    click("downloadSubtitles");
    click("downloadCover");
    click("openSettings");
    const heading = element("settingsHeading").closest(".settings-heading");
    assert.ok(heading?.contains(element("openDownloadPresets")));
    assert.equal(element("saveDownloadDefaults"), null);
    assert.doesNotMatch(heading.textContent, /保存为默认/);
    assert.equal(show("downloadPresetsPanel"), false);

    click("proxyDisclosure");
    element("rateLimit").value = "1600";
    element("fragments").value = "6";

    click("openDownloadPresets");
    assert.equal(show("downloadPresetsPanel"), true);
    click("newDownloadPreset");
    assert.equal(show("downloadPresetForm"), true);
    page.namePreset("常用配置");
    click("saveDownloadPreset");
    const configuration = {
        height: 720, subtitles: true, rateLimitKiB: 1600, videoContainer: "mp4", videoCodec: "av1", fragments: 6,
        outputMode: "video-and-audio", audioFormat: "opus", cover: true,
    };
    assert.deepEqual(presetWrites, [{ name: "常用配置", ...configuration }]);
    assert.deepEqual(named.get("常用配置"), { name: "常用配置", ...configuration });
    assert.deepEqual(defaultWrites, []);
    assert.equal(show("downloadPresetsPanel"), false);

    const reopened = openPage(context, bridge);
    assert.equal(reopened.element("resolutionValue").textContent, "自动");
    assert.equal(reopened.element("outputModeValue").textContent, "带声音的视频");
    reopened.click("openSettings");
    reopened.click("openDownloadPresets");
    const name = reopened.element("downloadPresetList").querySelectorAll(".preset-name")[1];
    assert.equal(name.textContent.trim(), "常用配置");
    assert.equal(name.closest('button, a, [role="button"]'), null);
    name.click();
    assert.deepEqual(defaultWrites, []);
    assert.equal(reopened.show("downloadPresetsPanel"), true);

    const load = name.closest(".preset-row").querySelector(".preset-load");
    assert.equal(load.textContent.trim(), "加载");
    load.click();
    assert.deepEqual(defaultWrites, [configuration]);
    assert.equal(reopened.show("downloadPresetsPanel"), false);
    assert.equal(reopened.element("resolutionValue").textContent, "视频 + 音频 · 720p");
    assert.equal(reopened.element("moreOptionsValue").textContent, "Opus · AV1 · 字幕 · 封面");
    assert.equal(reopened.element("outputModeValue").textContent, "视频 + 音频");
    assert.equal(reopened.element("audioFormatValue").textContent, "Opus");
    assert.equal(reopened.element("downloadCover").checked, true);
    assert.equal(reopened.element("downloadSubtitles").checked, true);
    assert.equal(reopened.element("rateLimit").value, "1600");
    assert.equal(reopened.element("fragments").value, "6");
    assert.equal(reopened.element("videoCodecValue").textContent, "AV1");

    const restarted = openPage(context, bridge);
    assert.equal(restarted.element("resolutionValue").textContent, "视频 + 音频 · 720p");
    assert.equal(restarted.element("moreOptionsValue").textContent, "Opus · AV1 · 字幕 · 封面");
    assert.equal(restarted.element("outputModeValue").textContent, "视频 + 音频");
    assert.equal(restarted.element("audioFormatValue").textContent, "Opus");
    assert.equal(restarted.element("downloadCover").checked, true);
    assert.equal(restarted.element("videoCodecValue").textContent, "AV1");
});

test("同名预设显示覆盖，删除需再次确认", context => {
    const original = { name: "通勤", ...initialDefaults, height: 480 };
    const { bridge, named, defaultWrites, presetWrites, deletions } = presetBridge([original]);
    const { element, show, click, namePreset } = openPage(context, bridge);

    click("openSettings");
    click("openDownloadPresets");
    const presets = element("downloadPresetList");
    assert.equal(presets.querySelectorAll(".preset-load").length, 2);
    click("newDownloadPreset");
    namePreset("通勤");
    assert.match(element("saveDownloadPreset").textContent, /覆盖/);
    assert.deepEqual(presetWrites, []);
    click("saveDownloadPreset");
    assert.deepEqual(presetWrites, [{ name: "通勤", ...initialDefaults }]);
    assert.equal(named.size, 1);
    assert.deepEqual(defaultWrites, []);

    click("openDownloadPresets");
    assert.equal(presets.querySelectorAll(".preset-load").length, 2);
    const deletePreset = () => presets.querySelector(".preset-delete");
    deletePreset().click();
    assert.match(deletePreset().textContent, /确认删除/);
    assert.deepEqual(deletions, []);
    assert.equal(presets.querySelectorAll(".preset-load").length, 2);
    deletePreset().click();
    assert.deepEqual(deletions, ["通勤"]);
    assert.equal(named.size, 0);
    assert.equal(show("downloadPresetsPanel"), true);
    assert.equal(presets.querySelectorAll(".preset-load").length, 1);
    assert.equal(presets.querySelector(".preset-name").textContent.trim(), "默认配置");
    assert.equal(presets.querySelector(".preset-delete"), null);
});

test("读取旧视频配置时保留画质和编码，并可恢复内置默认配置", context => {
    const priorDefaults = {
        height: 1080, subtitles: true, rateLimitKiB: 3500, videoContainer: "mkv", videoCodec: "h264", fragments: 8,
    };
    const priorPreset = { name: "默认配置", ...initialDefaults, height: 480 };
    const { bridge, named, defaultWrites, presetWrites, deletions } = presetBridge([priorPreset], priorDefaults);
    const { element, click } = openPage(context, bridge);
    assert.equal(element("resolutionValue").textContent, "1080p");
    assert.equal(element("moreOptionsValue").textContent, "H.264 · 字幕");
    assert.equal(element("outputModeValue").textContent, "带声音的视频");
    assert.equal(element("videoCodecValue").textContent, "H.264");
    assert.equal(element("rateLimit").value, "3500");
    assert.equal(element("fragments").value, "8");
    assert.deepEqual(defaultWrites, []);

    click("openSettings");
    click("openDownloadPresets");
    const rows = element("downloadPresetList").querySelectorAll(".preset-row");
    assert.deepEqual(Array.from(rows, row => row.querySelector(".preset-name").textContent.trim()),
        ["默认配置", "默认配置（自定义）"]);
    assert.equal(rows[0].querySelector(".preset-delete"), null);
    assert.ok(rows[1].querySelector(".preset-delete"));
    rows[0].querySelector(".preset-name").click();
    assert.deepEqual(defaultWrites, []);
    rows[0].querySelector(".preset-load").click();
    assert.deepEqual(defaultWrites, [initialDefaults]);
    assert.equal(element("resolutionValue").textContent, "自动");
    assert.equal(element("outputModeValue").textContent, "带声音的视频");
    assert.equal(element("downloadSubtitles").checked, false);
    assert.equal(element("videoCodecValue").textContent, "自动");
    assert.equal(element("rateLimit").value, "0");
    assert.equal(element("fragments").value, "1");
    assert.deepEqual([...named.values()], [priorPreset]);
    assert.deepEqual(presetWrites, []);
    assert.deepEqual(deletions, []);

    const restarted = openPage(context, bridge);
    assert.equal(restarted.element("resolutionValue").textContent, "自动");
    assert.equal(restarted.element("rateLimit").value, "0");
    assert.equal(restarted.element("fragments").value, "1");
    restarted.click("openSettings");
    restarted.click("openDownloadPresets");
    restarted.element("downloadPresetList").querySelectorAll(".preset-load")[1].click();
    assert.deepEqual(defaultWrites, [initialDefaults, { ...initialDefaults, height: 480 }]);
    assert.equal(restarted.element("resolutionValue").textContent, "480p");
});

test("旧版仅音频预设加载为自动画质和独立音频模式", context => {
    const legacy = {
        height: -3, subtitles: true, rateLimitKiB: 1000, videoContainer: "webm", videoCodec: "vp9", fragments: 3,
    };
    const { bridge, defaultWrites } = presetBridge([{ name: "通勤音频", ...legacy }], legacy);
    const { element, click } = openPage(context, bridge);
    assert.equal(element("outputModeValue").textContent, "只输出音频");
    assert.equal(element("qualityChoices").hidden, true);
    assert.equal(element("subtitleOption").hidden, true);
    assert.equal(element("audioFormatValue").textContent, "M4A");
    assert.equal(element("downloadCover").checked, false);
    assert.deepEqual(defaultWrites, []);

    click("openSettings");
    click("openDownloadPresets");
    element("downloadPresetList").querySelectorAll(".preset-load")[1].click();
    assert.deepEqual(defaultWrites, [{
        height: 0, subtitles: false, rateLimitKiB: 1000, videoContainer: "mp4",
        videoCodec: "vp9", fragments: 3, outputMode: "audio", audioFormat: "m4a", cover: false,
    }]);
    assert.equal(element("outputModeValue").textContent, "只输出音频");
    assert.equal(element("qualityChoices").querySelector('[aria-pressed="true"]').dataset.height, "0");
});
