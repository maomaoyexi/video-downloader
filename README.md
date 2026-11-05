# 多平台视频下载工具 v2.8.1 WebUI

![Version](https://img.shields.io/badge/source-v2.8.1%20WebUI-purple) ![Platform](https://img.shields.io/badge/platform-Windows-blue) ![License](https://img.shields.io/badge/license-MIT-green)

面向 Windows 的多平台视频下载与直播录制工具，使用浏览器 WebUI 操作，提供任务队列、批量下载、字幕与音频工具，并支持 FANBOX 内容归档及 Withny 授权存档。

**[下载 Windows 版](https://github.com/maomaoyexi/video-downloader/releases)** · **[完整使用教程](docs/使用教程.txt)** · **[更新日志](RELEASE_NOTES.md)**

> 本页对应 v2.8.1 正式版源码。安装包版本、文件和 SHA-256 请以 Releases 页面实际发布的内容为准。

[下载安装](#下载安装) · [支持平台](#支持平台) · [功能与使用](#功能与使用) · [已知问题](#已知问题) · [源码运行](#源码运行) · [使用注意](#使用注意) · [文档](#文档) · [作者与贡献者](#作者与贡献者)

## 下载安装

### Windows 绿色版

从 [Releases](https://github.com/maomaoyexi/video-downloader/releases) 下载**同一版本的两份文件**：

| 文件 | 用途 |
| --- | --- |
| `video-downloader-v2.8.1-GUI.exe` | 主程序，无需安装 Python |
| `video-downloader-v2.8.1-dependencies.zip` | 下载工具、平台插件及配套运行依赖 |

1. 新建一个工具文件夹，将 EXE 放入其中。
2. 解压依赖包，将完整的 `dependency/` 文件夹放在 EXE 旁边，不要拆散或额外套一层目录。
3. 双击 EXE，程序会自动打开浏览器界面。
4. 在「设置」中按需要配置画质、音频、Cookie、代理和下载限速。

```text
工具文件夹/
├── video-downloader-v2.8.1-GUI.exe
└── dependency/
```

依赖包包含 yt-dlp、FFmpeg、ffprobe、Deno、Fantia/Withny 工具、NicoChannel/Rplay 插件、Provider 及配套运行库。Withny 的 `withny-dl-windows-amd64.exe` 和受管录制组件随依赖包提供。

正式发行手动上传的附件仅为 EXE 和依赖包，不另附源码压缩包；源码可从本仓库获取。文件 SHA-256 见对应版本的 Release 说明。

v2.8.0 新增「关于软件 → 依赖状态 → 更新依赖」。启动或打开时只检测依赖文件是否缺失，不自动下载；需要补齐或更新时，点击「更新依赖」并确认，程序会下载与当前程序匹配的官方完整配套包，校验后先备份再替换外置组件。

- 已自行升级的 yt-dlp 默认保留，其兼容性仍需实际任务验证；其他外置组件随本次依赖更新备份并替换。
- EXE 内置库和源码 Python 运行库只读；源码运行库仍按[源码运行](#源码运行)中的命令维护。
- 依赖更新与下载、音频工具、监控任务互斥；取消或失败会尝试恢复已备份文件，未完成的恢复须按界面提示处理。
- 失败时可使用界面的项目 GitHub 手动更新入口，完整步骤与状态说明见[使用教程](docs/使用教程.txt)。

v2.8.1 继续提供这项功能；更新主程序后，请重新检查对应版本的依赖。

### 老用户升级

先通过程序左侧底部「退出工具」关闭旧程序，再替换 EXE，并完整更新同版本依赖包。

保留原有 `settings.ini`、`presets.json`、`cookies.txt`、密码表和 `download/`。不要为了升级删除这些文件；跨版本升级时也应检查配套依赖，不能只替换 EXE。

## 支持平台

各平台能力不同，登录、会员、地区及直播回放权限仍由平台决定。

| 平台 | 已接入能力 | 使用要点 |
| --- | --- | --- |
| YouTube | 视频、直播录制 | 追开播取决于可用的 DVR/DASH；受限内容可能需要 Cookie |
| Bilibili | 视频、多 P、直播录制 | 高画质通常需要 Cookie；直播从当前时刻录制 |
| Twitch | 回放、剪辑、直播录制 | 追开播依赖可访问的本场 VOD |
| Niconico | 视频、直播录制 | 高清视频需要登录 Cookie；当前直播从当前时刻录制 |
| NicoChannel | 视频、直播录制 | 依赖包已含 `nicochannel.zip`；直播需要 Firefox 登录态 |
| Fantia | 帖子及媒体下载 | 使用 `cookies.txt` 文件模式；未接入直播录制 |
| TwitCasting | 录播、历史列表、直播录制 | 密码或会员内容需要对应授权；可选记住密码及保存 XLSX |
| Twitter/X | 视频、Spaces 录制 | Spaces 通常需要 Cookie，且取决于平台是否仍提供相应流或回放 |
| Rplay | HLS 点播、已接入的直播源、Twitch 转播 | 登录来源独立配置为 Firefox；Rplay HLS 不支持分离音画 |
| FANBOX | 扫描、预览、正文/图片/附件归档、粉丝卡 | 支持创作者、单帖及账号可访问的集合；权限以实际响应为准 |
| Withny | HAR 授权历史存档、直播监控录制 | HAR 存档仅处理已授权的普通未加密 HLS；直播由 `withny-dl` 配置驱动 |

## 功能与使用

### 下载与批量任务

- 粘贴链接后点击「开始下载」，程序自动识别支持的链接。
- 多行链接可一次提交；TXT 批量可在工具箱生成 `urls.txt` 模板后编辑导入。
- 命中下载归档时，可选择重新下载或跳过；20 秒未选择默认跳过，跳过单独计数。
- 支持断点续传、下载历史、配置预设、默认参数与「本次 yt-dlp 参数」。
- 同一文件、同一音视频阶段内，预计总大小重新估算时保留最高已显示进度，速度和剩余时间继续刷新；切换文件、阶段或任务时正常重新计算。

启用「设置 → 任务与并发」中的任务模式后，每次提交形成一个任务。任务间默认并行 2 个，最多 5 个；任务内直播与视频使用独立并发额度。展开任务可查看链接状态、日志、密码或归档确认，并单独取消任务。

**FANBOX 请独立创建任务，不与其他平台的下载或录制链接混在同一任务中；不同任务可以并行。** 普通任务队列仅保留在本次程序运行中，重启后不会自动恢复。

### 直播录制与弹幕

通过「直播录制设置」选择自动、追开播、从当前时刻录制或蹲开播。程序会检查平台状态；能否追播取决于平台与当前流，无法取得的历史分片不保证能够补齐。

支持已接入评论源的采集、SRT/ASS 导出和录制报告。不同平台的权限、时间精度与实测范围不同，请结合 `comments-report.json` 及完整性报告检查结果。

直播会话和报告保存在 `download/.live-jobs/`。平台入口、追播条件、停止与输出规则见 [使用教程](docs/使用教程.txt)。

### FANBOX 内容归档

在「设置 → 平台专项 → FANBOX」选择凭据和访问方式，再输入创作者或单帖链接。可先预览帖子列表，设置筛选和命名规则，再下载所选内容。

支持正文、原始 JSON、图片、附件、封面、外链清单、可选评论和粉丝卡，并提供文件复用、归档校验、流量额度与记录。外链只收集，不自动下载其他网站的内容；公开封面不代表正文或附件也有访问权限。

独立扫描 CLI 仅生成清单。当前源码中的扫描与归档 CLI 均读取已保存的匿名及 Cookie 设置；`--anonymous` 或 `--cookies PATH` 可覆盖本次访问方式，两者不能同时指定。修复与发布状态见[已知问题](#已知问题)。

### 设置与使用帮助

- 设置页采用紧凑单列，下拉框按最长选项文字测宽、同组等宽，长路径和参数保持可编辑宽度。
- 设置目录首次点击其他章节时定位并展开，再次点击当前目录项可展开、收起；章节标题支持整行切换。下载页“本次 yt-dlp 参数”默认收起，收起不会清空输入。
- 帮助页按三类、17 个主题组织，提供 21 条常见报错速查、完整手册、本地报错整理与反馈模板。
- 报错整理不自动读取日志、上传内容或提交反馈；生成后可检查、编辑再复制，敏感信息仍需人工核对。

### 字幕、音频与辅助工具

- 普通视频可附带字幕，也可独立下载字幕或批量封面。
- 提供音视频合并/分离、MP3 保存、WAV 转 MP3、响度与音量处理，以及受支持的硬件编码选项。
- 可更新 yt-dlp、清理临时文件、生成链接/Cookie 模板、打开下载和日志目录。
- YouTube 可选使用本地 BgUtils PO Token Provider；它可能缓解部分请求失败，但不保证绕过风控。
- 支持自动更新 EXE，并校验下载来源、文件大小、Windows EXE 格式和 SHA-256；配套依赖按对应版本说明更新，可按上文点击「更新依赖」。

## 已知问题

v2.7.0 中记录的以下六项 FANBOX 问题已在 v2.7.1 修复，本版继续保留这些行为。v2.8.1 的修复见 [本版发布说明](RELEASE_NOTES.md)，历史更新见 [版本更新记录](CHANGELOG.md)，各平台的访问权限与续传差异仍以使用说明及实际结果为准。

| 场景 | 当前源码行为 |
| --- | --- |
| FANBOX 排队任务暂停或启动失败 | 清理失效活动记录并恢复为可继续状态，修正配置后无需重启即可继续 |
| FANBOX 与其他平台混合批量 | 入口拒绝混合输入；请分别创建独立任务，不同任务可以并行，归档确认发给所属执行器 |
| FANBOX 缩略图与封面格式 | 按实际资源 URL 确定扩展名，旧失败资源续跑时可修复路径与格式不一致 |
| FANBOX 预览后下载 | 可选择受限帖的公开封面；正文和附件仍按权限处理，显式 `accessible_only` 筛选继续生效 |
| FANBOX 较长请求间隔 | 等待期间每 20 秒续租，异常结束原子保存终态，不再因 180 秒间隔本身残留 `running` |
| FANBOX 独立扫描 CLI 设置 | 扫描与归档 CLI 均沿用保存的匿名及 Cookie 设置，并支持显式参数覆盖；WebUI 原有行为保持一致 |
| 代理开关范围 | 常规 yt-dlp 下载和 FANBOX 关闭后默认直连；更新及部分辅助请求仍可能沿用系统／环境代理，自定义 `--proxy` 可覆盖，TUN／VPN 由系统网络层控制 |
| 依赖缺失检测 | 仅检查托管外置文件是否存在，不代表文件内容或平台兼容性已经验证；完整更新前会核验配套包 |
| 同一文件、同一阶段的下载百分比小幅回退 | v2.8.1 保留最高已显示进度，速度和剩余时间继续更新；切换文件、音视频阶段、链接或重新启动下载进程时正常重置 |
| v2.8.0 EXE 直播预检查报 `网络错误: [Errno 2] No such file or directory` | 原正式 EXE 漏包构建运行库依赖的 SSL 证书策略文件；v2.8.1 主程序已补齐原策略资源并加强默认 TLS 初始化自检。请升级主程序，重新登录或更新外置依赖不能补齐旧 EXE 内嵌资源 |
| 启动器报 `Could not create temporary directory` 或退出值 `4294967295` | 需按完整错误区分产生进程和失败阶段；退出值不是 HTTP 429，重试恢复也不能确认具体原因。本版补充排查说明，未将未定原因的偶发启动失败列为已修复 |

## 源码运行

保留 `视频下载工具v2.8.1-GUI.py`、`video_downloader/`、`resource/` 和 `dependency/` 的目录结构，使用 64 位 Python 3.12 运行。若相应 Python 运行库尚未准备，可在项目根目录执行：

```powershell
python scripts/install_live_dependencies.py
python -m video_downloader.platforms.fanbox.runtime --install
python ".\视频下载工具v2.8.1-GUI.py"
```

前两条命令按锁定版本准备直播和 FANBOX 的 Python 运行库；yt-dlp、FFmpeg 及平台录制组件仍需在 `dependency/` 中准备。完整安装与依赖说明见[使用教程](docs/使用教程.txt)。

维护直播依赖时，以 `resource/dependencies/live-python.lock.json` 为准；修改锁文件后运行 `python scripts/sync_live_requirements.py` 同步手动安装清单。可使用 `python scripts/sync_live_requirements.py --check` 只检查一致性，不改动文件。

命令行选项可通过以下方式查看：

```powershell
python ".\视频下载工具v2.8.1-GUI.py" --help
python ".\视频下载工具v2.8.1-GUI.py" --fanbox-scan --help
python ".\视频下载工具v2.8.1-GUI.py" --fanbox-download --help
```

源码版不会被自动更新下载的 EXE 覆盖。升级源码时请更新主脚本、`video_downloader/`、`resource/` 和对应依赖，保留自己的配置与下载数据。

## 使用注意

- **下载限速推荐 5–10 MB/s。** 高速或大批量下载可能导致 IP 或账号被限制或封禁，相关后果由使用者自行承担。
- 不要关闭后端控制台。有任务时关闭网页，确认提示后任务继续在后台运行；无任务时关闭网页，程序会在 30 秒后退出。彻底退出请使用左侧底部「退出工具」。
- Cookie 应使用 Netscape 格式的 `cookies.txt`。Fantia 仅支持文件模式；Rplay 使用独立 Firefox 授权，NicoChannel 直播也需要 Firefox 登录态。
- TwitCasting「记住密码」和「保存到 XLSX」默认关闭。`twitcasting_passwords.xlsx` **以明文保存密码，除非获得明确授权，请勿发送给其他人**。
- HAR、Cookie、凭据配置、密码表及原始评论文件可能包含登录或账号信息，请勿作为公开反馈附件。
- Cookie 和登录态只提供已有权限，不能绕过付费、会员、地区或 DRM 限制；实现某项功能也不代表所有账号、内容和网络环境均已实测通过。
- 下载文件、归档和日志默认位于 `download/`；设置与预设等配置保留在程序根目录。请在升级和排查前备份重要数据。
- 仅在拥有相应权利或授权时下载内容，并遵守平台规则与当地法律法规。各平台商标归其各自所有者所有。

## 文档

| 文档 | 内容 |
| --- | --- |
| [完整使用教程](docs/使用教程.txt) | 安装、任务、直播及平台专项设置 |
| [常见问题](docs/常见问题答疑.txt) | 常见故障与排查方法 |
| [Cookie 配置指南](docs/cookies问题答疑.txt) | 登录状态与 Cookie 导出 |
| [Bilibili Cookie 指南](docs/bilibili_cookies_guide.txt) | Bilibili 登录配置 |
| [Withny HAR 指南](docs/withny_har_guide.txt) | 已授权历史存档保存 |
| [错误码说明](docs/错误码.txt) | 错误含义与处理建议 |
| [版本更新记录](CHANGELOG.md) | 按版本整理的功能变化、修复和交互改进 |
| [本版发布说明](RELEASE_NOTES.md) | 本版更新、问题修复、依赖与升级说明 |

## 作者与贡献者

| 贡献者 | 主要贡献 |
| --- | --- |
| [猫猫葉汐A_spy（@maomaoyexi）](https://github.com/maomaoyexi) | v2.8.1 下载进度稳定、SSL 打包与自检修复、错误说明和版本维护；v2.8.0 依赖检测与更新、可靠性修复及版本维护；v2.7.1 全部更新；项目原版与维护；Withny 历史存档和直播监控；多平台直播入口、策略、断流与状态展示；任务页「本次 yt-dlp 参数」「直播录制设置」按钮及后续交互整合；Cookie 模板、TwitCasting 密码表、HLS 回退与恢复、`.ytdl` 清理、合并适配、测试和文档 |
| [DarkKandaoMaster（强壮的砍刀）](https://github.com/DarkKandaoMaster) | WebUI 重构，以及 v2.4.0 / v2.5.0 的视觉与交互体系重构 |
| [ErgouTree（@ergou10086）](https://github.com/ergou10086) | Bilibili 视频与多 P、NicoChannel、Twitter/X、TwitCasting；单条/批量 CLI、音频输出与工具；下载进度、命令查看、yt-dlp 自定义参数、代理、Provider 和目录整理；归档选择与独立封面；PR #17 的直播框架重构、追播校验、弹幕及多任务；PR #18 的 Rplay、FANBOX 及相关界面与 CLI |
| [ZheYi101](https://github.com/ZheYi101) | PR #12 的随视频下载字幕设置与独立字幕下载工具（v2.4.0） |

完整版本、已合并 PR 与上游贡献来源见 [CREDITS.txt](CREDITS.txt)。感谢 [yt-dlp](https://github.com/yt-dlp/yt-dlp)、[FFmpeg](https://ffmpeg.org/) 及其他上游项目。

## 许可证

项目源码采用 [MIT License](LICENSE)。第三方工具和组件遵循各自许可证，相关声明见 [NOTICE](NOTICE) 及依赖包内的许可证文件。
