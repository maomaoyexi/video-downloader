# 多平台视频下载工具 · 安卓端

![Version](https://img.shields.io/badge/Android-v1.1.0-purple) ![Platform](https://img.shields.io/badge/platform-Android%2010%2B%20ARM64-blue) ![License](https://img.shields.io/badge/license-MIT-green)

面向 Android 10 及以上 ARM64 设备的点播下载工具。使用应用内 WebUI 下载哔哩哔哩和 YouTube 视频、处理批量队列及归档 FANBOX 公开单帖。

**[下载安卓 APK](https://github.com/maomaoyexi/video-downloader/releases/download/android-v1.1.0/video-downloader-android-1.1.0-arm64-v8a.apk)** · **[安卓发布说明与校验](https://github.com/maomaoyexi/video-downloader/releases/tag/android-v1.1.0)** · **[Windows 版](https://github.com/maomaoyexi/video-downloader#readme)**

[下载安装](#下载安装) · [支持平台](#支持平台) · [功能与使用](#功能与使用) · [源码构建](#源码构建) · [使用注意](#使用注意) · [文档](#文档) · [作者与贡献者](#作者与贡献者)

## 下载安装

| 文件 | 用途 |
| --- | --- |
| `video-downloader-android-1.1.0-arm64-v8a.apk` | ARM64 正式安装包 |
| `video-downloader-android-1.1.0-arm64-v8a-corresponding-source.zip` | 正式 APK 对应源码 |
| `SHA256SUMS.txt` | 发布附件校验值 |

1. 从发布页下载 APK，用系统安装器安装。
2. 首次打开时，把「使用与免责协议」滑到底，点「我已阅读并确认」。
3. 在首页粘贴视频链接，按需展开「下载选项」，再点「开始下载」。

首次确认协议后，可按「允许后台下载」提示打开系统电池设置，也可选「暂不设置」。使用小米设备时，可在应用电池设置中选择「无限制」。

### 老用户升级

在「设置 → 关于软件」点「检查更新」。下载新版正式 APK 后，使用系统安装器覆盖安装，以保留历史和设置。试用版与正式版可以同时安装，各自保存 Cookie、历史和预设。

## 支持平台

| 平台 | 已接入能力 | 使用要点 |
| --- | --- | --- |
| 哔哩哔哩 | 点播、多 P | 支持 `b23.tv`、`bili2233.cn` 分享短链；带明确 P 号的视频直链可直接下载对应分集 |
| YouTube | 点播、播放列表、可播放的直播回放 | 已结束且可播放的回放可用 `/live/` 链接 |
| FANBOX | 公开单帖预览与 ZIP 归档 | 位于「设置 → 专项归档」，可保存正文、图片和附件 |

频道批量下载、正在直播的录制、FANBOX 创作者批量扫描和 Withny 暂未接入安卓端。

## 功能与使用

### 下载与批量任务

- 每行一个链接，一次最多 20 条，哔哩哔哩和 YouTube 可混合提交。也可用「导入 TXT」填入链接，支持 UTF-8 和带 BOM 的 UTF-16。
- 单独提交多 P 视频或 YouTube 播放列表，可浏览前 100 项，每批最多勾选 20 项。B 站分 P 列表会显示可取得的分集标题。
- 队列按顺序下载，支持跳过当前条或停止队列。单条失败后继续下一条。展开「队列详情」可看各条链接状态。

### 音画输出、字幕与封面

| 音画输出 | 保存结果 |
| --- | --- |
| 带声音的视频（默认） | 有声 MP4 |
| 只输出音频 | 一个独立音频文件 |
| 带声音的视频 + 独立音频 | 有声 MP4 和独立音频 |
| 无声视频 + 独立音频 | 无声 MP4 和独立音频 |

- 在「下载选项」选择画质。「更多选项」提供编码偏好、音频格式、字幕和封面。独立音频可选 M4A（默认）、FLAC、Opus 或 WAV。
- 开启「同时下载字幕」后，单个视频可搜索语言，勾选人工、自动生成或自动翻译字幕，也可跳过。批量任务保存可用的人工字幕。字幕以独立 SRT 文件保存，封面以图片保存。
- 进度卡显示当前传输速度和可用的预计剩余时间。单条任务同时输出视频、独立音频和字幕时，按「1/3 · 视频」「2/3 · 独立音频」「3/3 · 字幕」提示。封面另计一项。

### 历史与文件位置

- 默认保存到「下载 / 多平台下载」，按平台和作者分文件夹。可在「设置 → 下载目录」自选位置和分类方式。
- 首页「历史」保留最近 200 条记录，可按平台、作者和标题筛选。完成卡及历史记录可播放文件、打开文件位置。
- 支持单条和批量删除。开启「删除记录时同时删除本地文件」后，确认框会列出关联的视频、音频、封面和字幕。旧记录未关联的封面和字幕可在原目录手动清理。

### 设置与使用帮助

在「设置」按分类打开配置。标题右侧的「配置预设」可保存、加载和恢复下载参数。工具箱提供下载目录入口和版本信息，使用帮助可查看手机端操作说明。

### FANBOX 内容归档

进入「设置 → 专项归档」，粘贴公开单帖链接，点「预览帖子」再点「保存 ZIP」。默认存到「下载 / 多平台下载 / FANBOX」。每篇最多收录 60 个文件，单文件上限 128 MiB，每帖合计上限 256 MiB。

<a name="构建"></a>

## 源码构建

构建环境为 Node.js 24、Python 3、JDK 17、Gradle 9.3、Android SDK Platform 35 和 Build Tools 36.0.0。设置 `JAVA_HOME` 和 `ANDROID_HOME`，在安卓源码目录执行。

1. 运行 `node prepare-core.cjs`，准备锁定版本的 yt-dlp。
2. 按 [ARM64 运行库构建说明](native-runtime/README.md) 准备 `.build/native-runtime/` 下的两个 AAR 和校验清单。
3. 运行 `gradle :app:assembleDebug`。试用包位于 `app/build/outputs/apk/debug/app-debug.apk`。

依赖已缓存时，可配置 `GRADLE_USER_HOME` 并加上 `--offline`。下载引擎锁定为 yt-dlp 2026.11.23，安卓封装采用 youtubedl-android 0.18.1 的 Java 接口。[第三方组件与源码](THIRD_PARTY_NOTICES.md)

也可以在浏览器打开 [本地预览页面](app/src/main/assets/index.html)，用示例链接体验模拟下载。

### 构建与签名正式包

运行 `gradle :app:assembleRelease`，未签名包位于 `app/build/outputs/apk/release/app-release-unsigned.apk`。正式应用 ID 为 `io.github.maomaoyexi.videodownloader`，本版为 `1.1.0`（`versionCode 7`）。试用版使用 ID `io.github.maomaoyexi.videodownloader.prototype`，显示版本为 `0.1.3`。

正式升级包沿用正式版签名证书，并递增 `versionCode`。使用 Build Tools 的 `apksigner` 签名和校验，在本机交互式输入口令。

```powershell
apksigner sign --ks '签名库路径' --ks-key-alias '签名别名' --out '签名后.apk' '未签名.apk'
apksigner verify --verbose --print-certs '签名后.apk'
Get-FileHash -Algorithm SHA256 -LiteralPath '签名后.apk'
```

检查更新按 `android-vX.Y.Z` 标签识别正式发布，APK 附件名为 `video-downloader-android-X.Y.Z-arm64-v8a.apk`。

### 验证

先运行 `npm --prefix tests ci`，再运行 `npm --prefix tests test`。正式包的 16 KiB 静态对齐和 ARM64 实体设备验收范围见对应版本的发布说明。

## 使用注意

- 两个点播平台可在「设置 → 平台 Cookie」分别导入 Netscape 格式的 `cookies.txt`。请妥善保管 Cookie。账号权限和可用画质由平台决定。
- 手动 HTTP 或 SOCKS5 代理默认关闭。使用手机 VPN 时通常保持关闭。电脑上的代理应填写手机能访问的电脑地址和端口。
- 「设置 → 网络与代理」可独立配置限速和分片并发。限速单位为 KiB/s，`0` 表示不限速。分片并发范围为 1–16，只在支持分片的流上生效。
- 若息屏后下载暂停，可在手机的应用电池设置中检查省电策略。
- 仅下载或归档拥有权利或已获授权的内容，并遵守平台规则及适用法律。

## 文档

| 文档 | 内容 |
| --- | --- |
| [安卓 1.1.0 发布页](https://github.com/maomaoyexi/video-downloader/releases/tag/android-v1.1.0) | APK、对应源码、校验文件与版本说明 |
| [ARM64 运行库构建](native-runtime/README.md) | 构建环境、输入和校验流程 |
| [第三方组件声明](THIRD_PARTY_NOTICES.md) | 组件版本、对应源码与许可证 |

## 作者与贡献者

| 贡献者 | 主要贡献 |
| --- | --- |
| [猫猫葉汐A_spy（@maomaoyexi）](https://github.com/maomaoyexi) | 安卓端移植、开发与维护 |

## 许可证

项目源码采用 MIT 许可证。第三方组件遵循各自的许可证。[MIT License](LICENSE) · [第三方组件声明](THIRD_PARTY_NOTICES.md)
