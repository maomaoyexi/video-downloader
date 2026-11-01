# v2.7.0 WebUI

发布日期：2026-11-01 · [下载本版](https://github.com/maomaoyexi/video-downloader/releases/tag/v2.7.0) · [使用说明](https://github.com/maomaoyexi/video-downloader/blob/main/README.md)

本次更新新增 Rplay 与 FANBOX 支持、任务队列和直播弹幕，并修复跨平台切换后的单任务停止路由。

## 新增功能

### Rplay

- 支持单个 HLS 点播，以及已接入直播源的识别、状态检查、等待开播和录制。
- 支持 `/play/`、`/live/`、`/creatorhome/` 入口及平台返回的 Twitch 转播源。
- 新增独立 Firefox 登录来源和配置选择；普通 `cookies.txt` 不能替代 Rplay 授权，Rplay HLS 暂不支持分离音画。
- Twitch 转播需源频道仍在直播且具有观看权限，不向 Twitch 转交 Rplay 凭据。

### FANBOX

- 支持创作者主页、单帖、标签及账号可访问的赞助/关注集合扫描，提供帖子预览和所选内容下载。
- 可保存正文、原始 JSON、图片、附件、封面、可选评论和外链清单；外链仅记录，不自动下载外站内容。
- 新增内容筛选、命名模板、文件复用、归档记录与完整性校验，以及粉丝卡、文件并发、每日流量额度和用量统计。
- 新增 WebUI 专项设置、任务详情与独立 CLI：`--fanbox-scan` 生成清单，`--fanbox-download` 执行归档。

归档内容以当前账号已有权限为准；匿名访问仅适用于平台允许公开读取的内容。

### 任务与直播

- 新增任务队列：任务间默认并行 2 个，最多 5 个；任务内直播和视频使用独立并发额度。
- 任务可展开查看链接状态、独立日志、密码与归档确认，并可单独取消；普通队列仅保留在本次运行中。
- 新增网络检测及并发方案预览与应用，提供高性能、高可靠选项。
- 新增已接入平台的直播评论采集、SRT/ASS 导出和评论报告；实际可用性与时间精度因平台而异。

## 问题修复

- **修复停止目标残留**：关闭任务模式后，完成 FANBOX 再成功启动普通视频批量或 Withny 任务，停止和当前命令查询会跟随实际执行器。
- **修复启动结果处理**：只有新任务成功启动才切换路由；失败、异常、取消选择时保留原执行器。新单链接密码重试同样处理，唤醒原批量等待时不切换。

此项修复不调整线程池或任务并发规则。FANBOX 请独立建任务，不与其他平台的链接混在同一个任务内；不同任务仍可并行。

## 依赖更新

- 下载核心升级为 **yt-dlp 2026.10.26**。
- 配套依赖加入固定版本的 FANBOX 与直播运行库、**BililiveRecorder 2.20.0** 和 Withny 受管录制组件。
- 依赖包保留 `withny-dl-windows-amd64.exe`，并包含 NicoChannel、Rplay 插件及 Provider 等配套文件。

## 下载与升级

本次手动上传的附件仅有以下两份，Windows 绿色版无需安装 Python：

| 文件 | 用途 |
| --- | --- |
| `video-downloader-v2.7.0-GUI.exe` | 主程序 |
| `video-downloader-v2.7.0-dependencies.zip` | 下载工具、插件及运行依赖 |

1. 先通过程序右上角「✕ 退出」关闭旧程序。
2. 替换 EXE，并完整解压新版依赖包，使 `dependency/` 与 EXE 位于同一目录。
3. 保留 `settings.ini`、`presets.json`、`cookies.txt`、密码表和 `download/`。跨版本升级应同时更新依赖包。

不另附源码压缩包；源码可从仓库获取。详细安装步骤见 [README](https://github.com/maomaoyexi/video-downloader/blob/main/README.md#下载安装)。

### SHA-256

```text
3222C203364150043FD7DCD268A91363F63A8BB17A9EBE16A09AE78F3767D465  video-downloader-v2.7.0-GUI.exe
6D716FDB81DEDCA7713CABBA377C8AE007AE49F1953C3A52F81862DE05F2C75F  video-downloader-v2.7.0-dependencies.zip
```

## 已知问题

以下六项仍待修复：

| 场景 | 当前影响与临时办法 |
| --- | --- |
| FANBOX 排队任务暂停或启动失败 | 归档记录可能卡在 `queued`，无法继续；核对日志，必要时重启程序 |
| FANBOX 与其他平台混合批量 | 命中归档后的重新下载确认可能失败；请拆成独立任务 |
| FANBOX 缩略图质量 | 原图 PNG/GIF、缩略图 JPEG 时可能按错误格式校验；暂用原图质量 |
| FANBOX 先预览再下载 | 可能漏存受限帖公开可见的封面；人工核对归档结果 |
| FANBOX 请求间隔达到或超过 120 秒 | 工作租约可能过期，任务中断后仍显示 `running`；避免此设置，异常时核对日志并重启 |
| FANBOX 独立扫描 CLI 匿名访问 | 当前忽略保存的 `FANBOX_ANONYMOUS`，仍可能使用 Cookie；匿名扫描必须显式加 `--anonymous`。该问题不影响 WebUI 和归档下载 CLI |

## 使用注意

- **下载限速推荐 5–10 MB/s。** 高速或大批量下载可能导致 IP 或账号被限制或封禁，相关后果由使用者自行承担。
- 不要关闭后端控制台。有任务时关闭网页，确认后任务继续在后台运行；无任务时关闭网页，程序会在 30 秒后退出。彻底退出请使用「✕ 退出」。
- `twitcasting_passwords.xlsx` **以明文保存密码，除非获得明确授权，请勿发送给其他人**。
- HAR、Cookie、凭据配置、密码表和原始评论可能包含登录或账号信息，请勿公开上传。
- 登录态只提供已有权限，不能绕过付费、会员、地区或 DRM 限制。已接入功能不代表所有账号、内容和网络环境均已实测通过。

## 本次贡献者

| 贡献者 | 本版贡献 |
| --- | --- |
| [猫猫葉汐A_spy（@maomaoyexi）](https://github.com/maomaoyexi) | 单任务执行器停止路由修复、回归测试、版本整合、打包和文档整理 |
| [ErgouTree（@ergou10086）](https://github.com/ergou10086) | [PR #18](https://github.com/maomaoyexi/video-downloader/pull/18)：Rplay 平台接入、授权与直播处理，以及 FANBOX 扫描、预览、归档、筛选、粉丝卡和相关 WebUI/CLI |
