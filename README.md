# 多平台视频下载工具 v2.7.0 WebUI

支持 YouTube / Bilibili / Twitch / Niconico / NicoChannel / Fantia / TwitCasting / Twitter / Rplay 的视频或直播下载，并提供 FANBOX 内容扫描与归档、Withny 已授权历史存档 HAR 保存及直播监控录制功能。具体能力与限制按平台区分。Release 的 EXE 绿色版无需安装 Python；源码运行版使用 Python 3 启动。

![Version](https://img.shields.io/badge/version-v2.7.0%20WebUI-purple)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> v2.7.0 整合 PR #18；其中 Rplay 与 FANBOX 等该 PR 的全部新增功能由 [ErgouTree (@ergou10086)](https://github.com/ergou10086) 贡献。当前已知问题及下载文件 SHA-256 见 [发布说明](RELEASE_NOTES.md)。

> v2.5.0 由 [DarkKandaoMaster](https://github.com/DarkKandaoMaster) 重构 WebUI 视觉与交互体系；[ErgouTree (@ergou10086)](https://github.com/ergou10086) 完善设置控件、TwitCasting 下载与进度、YouTube PO Token Provider 集成及运行目录收拢。本版同时支持自定义 yt-dlp 参数，并修复关闭代理后仍可能继承系统代理的问题。

## ✨ 功能特性

- 🌐 **全新WebUI界面** - 内置HTTP服务器，自动打开浏览器，深色主题，响应式设计
- 🎬 **多平台支持** - YouTube、Bilibili、Twitch、Niconico、NicoChannel、Fantia、TwitCasting、Twitter、Rplay，自动识别支持的链接
- 📡 **Rplay 支持** - 单个 HLS 点播、已接入的直播源与 Twitch 转播，支持独立 Firefox 登录设置
- 🗃️ **FANBOX 内容归档** - 扫描、帖子预览、筛选所选下载、正文与附件归档、文件校验、粉丝卡及流量记录
- 📦 **Withny 支持** - 从 HAR 保存已授权历史存档，也可通过 withny-dl 配置监控和录制直播
- 📺 **Bilibili 支持** - 支持普通视频、直播和多 P 分集选择
- 🎮 **直播录制** - 支持直播模式选择（自动/追开播/从当前时刻/蹲开播）；开始前按平台检查直播状态并提示开播时间/已开播时长，蹲开播会在开播后自动开始录制
- 🗂️ **任务模式** - 一次点击创建一个任务；支持 1–5 个任务并行（默认 2），任务内直播与视频使用独立并发额度，并支持网络检测后应用高性能/高可靠配置
- 💾 **配置预设** - 保存常用设置组合，一键切换
- 📜 **下载历史** - 自动记录每次下载，最多500条
- 🔄 **断点续传** - 默认启用，网络中断后自动续传
- 📊 **批量下载** - 支持从TXT文件批量导入链接
- ⌨️ **命令行模式** - 支持直接传入 URL 或通过 `--batch` 批量下载
- 🧾 **多行链接** - 下载页可直接粘贴多行 URL，按顺序加入批量队列
- 🖼️ **封面处理** - 下载独立 JPG 封面，并在兼容格式中自动嵌入
- **字幕下载** - 支持普通下载附带字幕及独立多链接字幕下载，默认关闭，开启后默认中文
- 🎵 **MP3 音频下载** - 支持在下载视频时单独保存 MP3 音频
- 🍪 **Cookie支持** - 支持cookies.txt文件模式
- 🛡️ **YouTube PO Token** - 可选自动启动本地 BgUtils Provider，缓解部分 GVS/PO Token 相关 403
- 🧩 **自定义 yt-dlp 参数** - 支持仅本次任务参数与每次下载默认参数
- ⚡ **硬件加速** - 支持NVIDIA NVENC、Intel QSV、AMD AMF
- 🔄 **自动更新** - 启动后通过 GitHub Releases 检查新版本，校验通过后自动更新替换
- 🧰 **工具箱** - 内置WAV转MP3、yt-dlp更新、临时文件清理等多项工具
- 🛡️ **进程管理** - 关闭网页30秒后自动退出，无残留进程

## 🚀 快速开始

### Windows EXE 绿色版（推荐）

1. 下载正式版 `video-downloader-v2.7.0-GUI.exe` 和 `video-downloader-v2.7.0-dependencies.zip`。
2. 将 EXE 放入单独文件夹，并将依赖包中的 `dependency/` 完整解压到 EXE 同一目录。
3. 双击 EXE，程序会自动打开浏览器 WebUI；无需安装 Python。
4. 老用户先退出旧程序，再替换 EXE 并完整更新依赖包，保留原有配置、Cookie、密码表和 `download/`。

> 💡 **提示**：正式 Release 仅提供 EXE 和依赖包，不提供单独源码附件；实际附件以 Release 页面为准。依赖包包含 yt-dlp、FFmpeg、ffprobe、Deno、Fantia/Withny 工具、NicoChannel 插件、Rplay 插件、Provider 及本版运行依赖。首次运行会生成下载、归档和日志目录。

### 源码运行版

保持 `视频下载工具v2.7.0-GUI.py`、`video_downloader/`、`resource/` 与 `dependency/` 位于同一目录，安装 Python 3 后运行：

```powershell
python ".\视频下载工具v2.7.0-GUI.py"
```

源码运行版不会用下载到的 EXE 自动覆盖 Python 源码；升级源码时请手动替换主脚本、`video_downloader/` 与 `resource/` 目录。

## 📖 使用说明

### 单视频下载

1. 在「下载」页面粘贴视频链接
2. 点击「开始下载」
3. 实时查看进度、速度、剩余时间

### 任务模式

在「设置 → 任务与并发」启用任务模式后，每次点击「开始」会创建一个任务，显示在链接输入框下方的任务列表。多行链接和 TXT 批量分别归入一次点击对应的任务，Withny 专用下载/监控也进入队列。任务行按进度填充颜色，点击展开可查看每条链接的状态、历史和日志，并单独取消父任务；密码与归档确认直接在对应详情内处理，刷新页面也能恢复待确认内容。

任务间默认并行 2 个，最多 5 个。任务内默认开启直播与视频并行：每个任务默认录制 2 路直播（可设 2–5 路），同时下载 1 条视频（可设 1–5 条），两类额度互不占用，避免直播和普通下载相互阻塞。关闭任务内并行开关后，全部链接按输入顺序串行。排序只影响排队任务，不中断运行中的任务；任务内设置在提交时固定，任务间并行数与排序对队列实时生效。

「设置 → 网络与代理 → 快速检测网络」会按当前代理设置测量单/多连接吞吐、HTTP 首字节延迟、抖动、失败率和负载延迟，约 20 秒，最多 32 MiB 测试数据（不含协议开销）。检测完成后可预览并应用「高性能」或「高可靠」方案；高可靠保持每任务视频串行，并通过仅限普通 yt-dlp 视频的独立限速为直播留出带宽。开始检测及应用方案前需先完成或取消活跃任务。操作步骤见 [使用教程](docs/使用教程.txt)。

任务列表保留本次运行中最近 100 个已结束任务，程序重启后不恢复普通队列；全局下载历史照常保存。相同的活跃链接会拒绝重复提交。关闭任务模式后，需先完成或取消现有队列，才能启动旧单任务流程；“停止”会处理实际活跃任务。蹲开播仍通过等待开播面板管理。当前边界和已知问题见 [发布说明](RELEASE_NOTES.md)。

### 批量下载

1. 进入「工具箱」页面
2. 点击「生成链接模板」创建 `urls.txt`
3. 编辑 `urls.txt`，每行一个链接（支持混合平台）
4. 点击「TXT批量下载」开始批量下载

### 直播录制（Twitch / YouTube）

在「设置 → 直播设置」选择全局模式，并可分别为 YouTube/Twitch 设置默认录制方式。任务前检查和实际执行都会核验条件：YouTube 需要可追播 DASH；Twitch 需要可访问的本场 VOD。未满足条件时会说明原因并从当前时刻录制。Twitch 会先录实时尾部、独立回填历史；只有轨道兼容且音视频包指纹确认重叠后才生成合并文件，无法验证时保留原件并报告缺口。未开播时可选择蹲开播，并在下载页「等待开播」面板取消。

直播媒体、会话记录和完整性报告保存在 `download/.live-jobs/<job-id>/`。报告验证容器、轨道、全文件时间戳和首尾解码，不承诺平台已删除的历史分片仍能取得。请结合完整性报告检查实际输出，不把实现范围视作所有平台均已实测通过。

### YouTube / Niconico 直播录制

YouTube 使用 `/live` 直播链接，Niconico 使用 `live.nicovideo.jp`、`live2.nicovideo.jp` 或 `www.nicovideo.jp/watch/lv...` 链接。YouTube 在 DVR/归档可用时可追开播；Niconico 当前只从当前时刻录制（上游 chasePlay 固定关闭）。程序实时显示录制时长、大小、速度和分片状态。

### TwitCasting 直播录制 / 录播下载

粘贴主播页 URL（如 `https://twitcasting.tv/主播名`）后默认从当前时刻录制（平台不支持 yt-dlp 从头），文件保存到 `download/TwitCasting/主播名/直播/` 目录。单条录播使用 `/movie/数字ID` 链接，历史直播列表使用 `/show` 或 `/archive` 链接。密码保护或会员限定内容会在对应任务中询问密码；可在「设置 → 平台专项 → TwitCasting」选择记住密码或保存到 XLSX，两个开关默认关闭。

### Bilibili 下载

粘贴 Bilibili 视频或直播链接后程序会自动识别。直播默认从当前时刻录制（普通观看侧无 DVR，不支持追开播）；多 P 视频可按设置下载全部分集或弹出分集选择器；1080P 及以上画质通常需要在程序目录配置 `cookies.txt`。

如需直播弹幕，在「设置 → 直播设置」开启「录制直播弹幕」，可选择 SRT、ASS 或两者。现有实现接入 Bilibili 录播姬 XML、YouTube `live_chat`、Withny 原生聊天，以及 Twitch、TwitCasting、NicoChannel、Niconico、Rplay 的评论采集路径；平台权限、源时间精度与实测范围不同，请查看 `comments-report.json`，不保证所有平台都能取得评论或精确同步。源码版可运行 `python scripts/install_live_dependencies.py` 准备受管依赖。匿名化只作用于派生事件库和字幕，原始采集文件仍可能包含账号信息。

### Withny 历史存档

在下载页面选择 Withny，点击「选择 HAR 并下载」，依次选择浏览器导出的包含内容 HAR 和输出文件。程序只处理已授权的普通未加密 HLS，检测到 DRM、加密 HLS、缺失媒体清单正文或签名 Cookie 时会拒绝下载。HAR 可能包含登录信息，使用后应立即删除。

### Rplay 点播、直播与 Twitch 转播

点播使用单个 `https://rplay.live/play/<内容ID>` 链接；直播使用 `/live/<创作者ID>` 或 `/creatorhome/<创作者ID>`。需要登录时，先在 Firefox 登录 Rplay，再在「设置」中选择「Rplay 登录来源 → Firefox」并指定所需配置。Rplay 授权不以普通 `cookies.txt` 代替。

点播仅处理当前支持的普通 HLS；直播按可用源从当前时刻录制，也可等待开播。平台返回 Twitch 转播时会解析源 Twitch 频道，需源频道仍在直播且具有观看权限。DRM、未知加密、未接入的授权协议和无权限内容会拒绝处理。Rplay HLS 暂不支持分离音画，请选择合并或受支持的音频输出组合。

### FANBOX 扫描、预览与内容归档

在「设置 → 平台专项 → FANBOX」检查启用状态、凭据文件和匿名访问选项。输入创作者主页或单帖链接后，可先「预览」检查帖子列表，再筛选并下载所选内容；开始前可调整本次任务选项。登录账号还可按赞助或关注范围扫描，结果始终受当前账号权限限制。

可归档正文（HTML/TXT/Markdown）、原始 JSON、图片、附件、封面、外链清单和可选评论，并提供命名模板、资源筛选、同名处理、已验证文件复用、归档文件校验、每日流量额度与下载记录。粉丝卡可按当前作者或赞助作者处理。外链只收集，不代表已下载外部平台内容；受限帖的公开封面也不代表正文可访问。默认目录为 `download/Fanbox/`。

独立扫描命令仅生成清单，不下载附件；匿名扫描必须显式使用 `--anonymous`：

```powershell
python ".\视频下载工具v2.7.0-GUI.py" --fanbox-scan "https://www.fanbox.cc/@creator" --output ".\fanbox-manifest.json" --anonymous
python ".\视频下载工具v2.7.0-GUI.py" --fanbox-download "https://www.fanbox.cc/@creator" --preview --anonymous
```

本版已修复跨 FANBOX 后的单任务停止路由，仍保留六项已知问题，包括队列 `queued` 卡住、混合批量重新下载确认、缩略图格式校验、预览后受限帖封面遗漏、请求间隔达到 120 秒的租约状态，以及独立扫描 CLI 的 `FANBOX_ANONYMOUS` 配置读取。完整条件和规避建议见 [发布说明](RELEASE_NOTES.md#已知问题待后续修复)。建议先以少量帖子确认权限和输出，FANBOX 与其他平台分开提交任务，请求间隔避免达到或超过 120 秒。

### 配置预设

1. 在「设置」页面调整好各项参数
2. 在「配置预设」区域输入预设名称
3. 点击「保存」按钮
4. 之后可随时从下拉框选择预设一键加载

### 自动更新

程序启动后3秒自动通过 GitHub Releases 静默检查更新。检测到新版本时右上角显示「⬆ 有更新」徽标，点击后可一键下载；程序会校验可信下载来源、文件大小、Windows EXE 格式及 SHA-256，校验通过后自动替换重启，所有配置和下载记录保留。

## ⚙️ 配置选项


| 设置项   | 说明                            | 默认值                 |
| -------- | ------------------------------- | ---------------------- |
| 分辨率   | best/2160/1440/1080/720/480/360 | best                   |
| 编码     | best/h264/av1/vp9               | best                   |
| 音频质量 | best/192/128                    | best                   |
| 输出格式 | mp4/mkv/webm                    | mp4                    |
| 合并模式 | 合并/分离                       | 合并                   |
| 线程数   | 下载线程数                      | 4                      |
| 代理     | HTTP/SOCKS5代理支持             | 关闭                   |
| Cookie   | cookies.txt文件模式             | 文件模式               |
| 硬件加速 | CPU/NVENC/QSV/AMF               | CPU                    |
| 字幕下载 | 人工/自动字幕，支持语言预设     | 关闭（开启后默认中文） |

## 🍪 Cookie配置

对于需要登录才能观看的视频（如年龄限制、会员内容、Niconico高画质），需要配置Cookie：

1. 安装浏览器扩展「Get cookies.txt LOCALLY」（Chrome/Edge/Firefox均支持，纯本地运行）
2. 登录对应平台（YouTube/Twitch/Niconico/Fantia/TwitCasting）
3. 在目标平台页面点击扩展图标，导出 **Netscape格式** Cookie
4. 将导出的文件重命名为 `cookies.txt`，放到exe同目录
5. 重启程序即可生效

> ⚠️ **注意**：Fantia 仅支持 `cookies.txt` 文件模式。FANBOX 使用对应账号 Cookie，也可匿名访问公开内容；Rplay 登录需独立配置 Firefox。Cookie 和登录态不能绕过付费、地区或 DRM 限制。

## 📂 目录结构

```
工具目录/
├── video-downloader-v2.7.0-GUI.exe # 正式版主程序
├── dependency/              # 所有第三方依赖，可整体替换
│   ├── yt-dlp.exe           # 下载核心
│   ├── ffmpeg.exe           # 音视频处理
│   ├── ffprobe.exe          # 媒体信息探测
│   ├── deno.exe             # JavaScript运行时
│   ├── fantiadl.exe         # Fantia下载器（可选）
│   ├── nicochannel.zip      # NicoChannel插件（依赖包已含）
│   ├── yt-dlp-plugins/
│   │   └── bgutil-ytdlp-pot-provider.zip
│   └── bgutil-ytdlp-pot-provider/
│       └── server/          # BgUtils Provider 与 node_modules（可选）
├── settings.ini             # 配置文件（自动生成）
├── presets.json             # 预设配置（自动生成）
├── cookies.txt              # Cookie文件（自行放置）
├── urls.txt                 # 批量下载链接（自行编辑）
├── RELEASE_NOTES.md         # 发布说明与更新日志
├── CREDITS.txt              # 作者与贡献者
├── docs/                    # 帮助文档
│   ├── 使用教程.txt
│   ├── 常见问题答疑.txt
│   ├── 错误码.txt
│   └── cookies问题答疑.txt
└── download/                # 所有运行产物，可整体迁移或备份
    ├── archive/             # 各平台 *_archive.txt
    ├── download_history.json # 下载历史（自动生成）
    ├── logs/                # 日志目录
    ├── YouTube/             # YouTube下载目录
    │   └── 上传者名/
    │       └── 视频标题 [id].mp4
    ├── Twitch/              # Twitch下载目录
    ├── Niconico/            # Niconico下载目录
    ├── NicoChannel/         # NicoChannel下载目录
    ├── Bilibili/            # Bilibili视频、直播及多P目录
    ├── Fantia/              # Fantia下载目录
    ├── Twitter/             # Twitter/X下载目录
    ├── Rplay/               # Rplay点播与直播目录
    ├── Fanbox/              # FANBOX内容归档、记录与校验数据
    ├── Withny/              # Withny历史存档目录
    └── TwitCasting/         # TwitCasting下载目录
```

旧版本散落在根目录的依赖、平台下载目录和 `*_archive.txt` 会在首次启动时自动迁移到上述结构。迁移不会覆盖同名文件；发生冲突时，旧文件会以 `.legacy-N` 后缀保留。

## 🔧 工具箱功能

- 📋 **TXT批量下载** - 从urls.txt读取链接批量下载
- 📝 **生成链接模板** - 生成带注释的urls.txt模板
- 🍪 **生成Cookie模板** - 生成Netscape格式cookies.txt模板
- 🔄 **更新yt-dlp** - 一键更新下载核心到最新版本
- 🗑️ **清理临时文件** - 清理下载产生的.part/.ytdl等临时文件
- 🎵 **WAV转MP3** - 批量音频转换，支持比特率选择
- 📂 **打开下载目录** - 在资源管理器中打开下载文件夹
- 📋 **打开日志目录** - 在资源管理器中打开日志文件夹
- **单独下载字幕** - 输入一个或多个链接，仅下载指定类型和语言的字幕
- 🖼️ **下载视频封面** - 输入一个或多个链接，只抓封面图片；自动识别平台，保存
  到该视频所在的平台目录，文件名与视频完全一致（如 `[20260907] 标题 [ID].jpg`），
  不写入下载归档，因此不影响之后的正式下载。Fantia 与 Withny 不走 yt-dlp，暂不支持。

## ❓ 常见问题

**Q: 下载速度慢怎么办？**

> A: 1. 配置代理；2. 适当增加线程数；3. 在工具箱更新yt-dlp到最新版本。

**Q: 提示需要登录？**

> A: 配置Cookie，参考Cookie配置说明。

**Q: Niconico只能下载低画质？**

> A: 需要配置登录Cookie，游客身份仅能获取低清晰度。登录后导出cookies.txt即可。

**Q: 下载的文件在哪里？**

> A: 默认保存在exe同目录的 `download/` 下，如 `download/YouTube/`、`download/Twitch/` 等。

**Q: 可以同时下载多个视频吗？**

> A: 任务模式支持 1–5 个任务并行（默认 2），每任务的直播与视频使用独立并发额度；关闭任务内并行后按链接顺序执行。请结合带宽设置限速。

**Q: 关闭浏览器会中断下载吗？**

> A: 不会。下载在后台继续进行，下载完成后30秒自动退出。如需停止请点击「停止」按钮或右上角「✕ 退出」按钮。

**Q: 双击exe后浏览器没自动打开？**

> A: 查看控制台窗口显示的端口号（如 http://127.0.0.1:8765），手动在浏览器中输入该地址访问。

**Q: 老用户如何升级？**

> A: 退出旧程序，下载 `video-downloader-v2.7.0-GUI.exe` 替换旧版 exe，并完整解压 `video-downloader-v2.7.0-dependencies.zip`；原有配置、Cookie、密码表和下载记录无需删除。

## 📚 详细文档

更多详细说明请查看 `docs/` 目录下的文档：

- [📖 完整使用教程](docs/使用教程.txt) - 从安装到高级功能的完整指南
- [📦 Withny HAR 指南](docs/withny_har_guide.txt) - 获取包含内容 HAR、下载和隐私安全说明
- [🍪 Cookie配置指南](docs/cookies问题答疑.txt) - Cookie配置详细说明和常见问题
- [❓ 常见问题答疑](docs/常见问题答疑.txt) - 常见问题的解决方案
- [⚠️ 错误码说明手册](docs/错误码.txt) - 下载错误码详解和排查流程
- [📋 更新日志](RELEASE_NOTES.md) - 版本更新历史

## 📋 版本更新

v2.7.0 的完整更新内容和升级说明请查看：

- [发布说明](RELEASE_NOTES.md)
- [版本更新日志](RELEASE_NOTES.md)

## ⚠️ 使用注意

- 推荐将下载限速设置为 **5–10 MB/s**。高速或大批量下载可能导致 IP 或账号被限制或封禁，相关后果由使用者自行承担。
- 使用过程中不要关闭后端控制台；彻底退出请使用右上角「✕ 退出」。
- HAR、Cookie、密码表、原始评论及归档文件可能包含账号信息，请勿作为公开反馈附件。
- 新增平台的实现范围不等于所有账号、内容和网络环境均已实测；本版其余六项已知问题待后续修复，详见 [发布说明](RELEASE_NOTES.md)。

## ⚠️ 免责声明

- 本工具仅供学习和个人使用，请遵守当地法律法规
- 请勿用于下载受版权保护的内容，除非您拥有相关权利
- 使用者需自行承担使用本工具产生的一切责任
- 各平台商标归其各自所有者所有

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 作者与贡献者

- 项目原版作者：[猫猫葉汐A_spy（GitHub：@maomaoyexi）](https://github.com/maomaoyexi)
- v2.1.0 WebUI 重构：[DarkKandaoMaster（强壮的砍刀）](https://github.com/DarkKandaoMaster)
- v2.3.0 NicoChannel、Twitter/X、TwitCasting、UI 与音频工具：[ErgouTree（GitHub：@ergou10086）](https://github.com/ergou10086)
- v2.3.0 Withny 历史存档、直播录制与 UI 调整：[猫猫葉汐A_spy（GitHub：@maomaoyexi）](https://github.com/maomaoyexi)
- v2.4.0 UI 重构：[DarkKandaoMaster（强壮的砍刀）](https://github.com/DarkKandaoMaster)
- v2.4.0 字幕下载：[ZheYi101](https://github.com/ZheYi101)
- v2.4.0 其他更新与修复：[ErgouTree（GitHub：@ergou10086）](https://github.com/ergou10086)
- v2.4.0 字幕功能修复与合并适配：[猫猫葉汐A_spy（GitHub：@maomaoyexi）](https://github.com/maomaoyexi)
- v2.5.0 WebUI 视觉与交互体系重构：[DarkKandaoMaster](https://github.com/DarkKandaoMaster)
- v2.5.0 设置控件、TwitCasting 下载与进度、BgUtils Provider 及目录收拢：[ErgouTree（GitHub：@ergou10086）](https://github.com/ergou10086)
- v2.7.0 PR #18 全部新增功能（Rplay、FANBOX 及相关界面与命令行）：[ErgouTree（GitHub：@ergou10086）](https://github.com/ergou10086)
- v2.6.0 上游修复：[@maomaoyexi](https://github.com/maomaoyexi) 的 Cookie 模板、TwitCasting 密码表、HLS 路径和恢复、文件对话框回退与相关测试，按本分支直播架构整合。

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 强大的视频下载引擎
- [FFmpeg](https://ffmpeg.org/) - 音视频处理工具

---

**如果这个工具对您有帮助，欢迎给个Star ⭐**
