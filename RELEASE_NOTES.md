# v2.7.0 WebUI

## 🎉 发布说明

多平台视频下载工具 v2.7.0 WebUI。本次版本在 v2.6.0 WebUI 基础上整合 PR #18，新增 Rplay 点播、直播与 Twitch 转播源支持，以及 FANBOX 扫描、预览、内容归档和粉丝卡等功能。Windows 主程序为 `video-downloader-v2.7.0-GUI.exe`，原有设置、预设、Cookie 和下载记录继续兼容。当前已知问题列于下方，待后续版本修复。

## 🤝 本次贡献者

- [ErgouTree（@ergou10086）](https://github.com/ergou10086) - PR #18 的全部新增功能，包括 Rplay 平台接入、授权和直播处理，以及 FANBOX 扫描、预览、归档、筛选、粉丝卡和相关界面与命令行功能

历史版本贡献记录（保留原有署名）：

- [猫猫葉汐A_spy（@maomaoyexi）](https://github.com/maomaoyexi) - v2.6.0 YouTube、Bilibili、Twitch、Niconico、NicoChannel、TwitCasting、Twitter/X Spaces 各平台直播入口识别、直播录制策略、断流处理与实时状态展示；任务页「本次 yt-dlp 参数」和「直播录制设置」两个按钮及相关设置功能、Cookie 模板修复、TwitCasting 密码表及失效记录清理、HLS 回退、完成后 `.ytdl` 清理、回归测试与相关文档整理
- [ErgouTree（@ergou10086）](https://github.com/ergou10086) - PR #15 下载归档选择、独立批量封面及 PO Token Provider 启动改进

## ✨ 主要更新

- **单任务停止路由修复** - 仅在新任务成功启动后切换活动执行器；失败、取消和批量密码确认保留原路由，覆盖视频批量、Withny 和新单链接密码重试，不调整任务队列或线程池。
- **Rplay 点播下载** - 支持单个 `/play/` 链接，按可用授权解析普通 HLS 点播；转码中、已删除、无权限、DRM 或未知加密内容会报告对应限制
- **Rplay 直播录制** - 支持 `/live/` 和 `/creatorhome/` 入口，接入直播状态检查、从当前时刻录制与等待开播；支持当前已接入的 HLS 和授权签名 FLV 路径，不承诺所有直播源或所有账号均可用
- **Rplay Twitch 转播** - 识别平台返回的 Twitch 转播状态，交由 Twitch 提取器解析源频道；需源平台仍在直播且当前环境具有观看权限，不向 Twitch 转交 Rplay 凭据
- **Rplay 登录设置** - 新增独立 Firefox 登录来源与配置选择；Rplay 登录状态不以普通 `cookies.txt` 替代，不绕过订阅或付费权限
- **FANBOX 扫描与预览** - 支持创作者主页、单帖及已登录账号的赞助/关注范围；可先抓取并预览帖子，再筛选下载所选内容，扫描 CLI 仅输出清单而不下载附件
- **FANBOX 内容归档** - 可保存可访问的正文、原始 JSON、图片、附件、封面、外链清单及可选评论，支持本地归档记录、文件校验和已验证文件复用；外链只收集，不自动下载其他平台内容
- **FANBOX 筛选与命名** - 提供免费/付费、金额、日期、投稿 ID、标题、附件名、资源类型等筛选，支持目录与文件命名模板、同名策略和原图不可用时的处理选项
- **FANBOX 粉丝卡与运行策略** - 支持按当前作者或赞助作者生成/保存粉丝卡，提供文件并发、请求间隔、每日流量额度、下载记录和流量查看功能
- **FANBOX WebUI 与命令行** - 新增平台专项设置、预览/归档详情、任务选项及 `--fanbox-scan`、`--fanbox-download` 入口；匿名访问只适用于平台允许公开读取的内容
- **任务队列与并发** - 提供 1–5 个任务并行（默认 2）、任务内直播与视频独立额度、任务展开详情与独立日志，支持网络检测后预览并应用并发方案；普通队列仅保留在本次运行中
- **直播弹幕与报告** - 保留现有多平台评论采集和 SRT/ASS 导出，按源记录时间与完整性信息；权限、同步精度和真实环境验证范围因平台而异，应核对评论报告
- **兼容保留** - 继续保留原有任务队列、多平台直播录制、弹幕、TwitCasting 密码表、下载归档、独立批量封面、PO Token Provider、自定义 yt-dlp 参数和目录迁移能力

> 上述为当前版本的实现范围，不代表所有平台、账号、直播源及网络环境均已完成真实下载验证。FANBOX 受限帖子、评论及粉丝卡等结果取决于账号权限和平台实际返回内容，请结合任务状态、清单与文件校验结果检查归档完整性。

## 📦 下载说明

### 文件清单

| 文件 | 说明 | 必须 |
|------|------|------|
| `video-downloader-v2.7.0-GUI.exe` | 主程序，单文件绿色版 | ✅ |
| `video-downloader-v2.7.0-dependencies.zip` | 通用依赖包（下载工具、Provider 和平台插件） | ✅ |

> 本版正式发行仅提供 Windows EXE 和依赖包，不另附源码压缩包；可下载版本与附件以 Release 页面实际发布内容为准。

> **依赖包已包含**：`dependency/` 中的 yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe、withny-dl-windows-amd64.exe、平台插件及本版所需的运行依赖。NicoChannel 插件 `dependency/nicochannel.zip` 已包含在依赖包中，无需另外下载。

### SHA-256

```text
3222C203364150043FD7DCD268A91363F63A8BB17A9EBE16A09AE78F3767D465  video-downloader-v2.7.0-GUI.exe
6D716FDB81DEDCA7713CABBA377C8AE007AE49F1953C3A52F81862DE05F2C75F  video-downloader-v2.7.0-dependencies.zip
```

## 🚀 快速开始

### 新用户安装
1. 下载 `video-downloader-v2.7.0-GUI.exe` 和 `video-downloader-v2.7.0-dependencies.zip`
2. 新建一个文件夹（如「视频下载工具」），将 `video-downloader-v2.7.0-GUI.exe` 放入其中
3. 解压依赖包，将其中的 `dependency` 文件夹完整放到 exe 同一目录
4. 双击 `video-downloader-v2.7.0-GUI.exe` 运行，自动打开浏览器界面
5. （可选）配置 Cookie 以支持会员、直播或高画质内容；Rplay 登录请使用独立 Firefox 设置

### 老用户升级
1. 关闭正在运行的旧版本程序（点击右上角「✕ 退出」按钮）
2. 下载新版 `video-downloader-v2.7.0-GUI.exe` 替换旧版 exe，并完整解压 v2.7.0 依赖包
3. 原有 `settings.ini`、`presets.json`、`cookies.txt` 和下载记录继续兼容
4. 原有 `download/`、`dependency/`、Cookie 和密码表无需删除；密码表仅在启用记住密码和 XLSX 保存后读取或迁移
5. 双击运行新版 exe；先以少量链接检查新增平台的权限和保存结果

## 📖 文档

- [使用教程](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E4%BD%BF%E7%94%A8%E6%95%99%E7%A8%8B.txt)
- [Cookie配置指南](https://github.com/maomaoyexi/video-downloader/blob/main/docs/cookies%E9%97%AE%E9%A2%98%E7%AD%94%E7%96%91.txt)
- [常见问题](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98%E7%AD%94%E7%96%91.txt)
- [错误码说明](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E9%94%99%E8%AF%AF%E7%A0%81.txt)
- [更新日志](https://github.com/maomaoyexi/video-downloader/blob/main/RELEASE_NOTES.md)

## ⚠️ 注意事项

- Windows EXE 和依赖包以 GitHub Release 页面实际发布的版本为准
- 使用过程中不要关闭控制台窗口（它是后端服务器）
- 有下载任务时关闭浏览器页面会提示确认；确认关闭后任务继续在后台运行
- 无下载任务时关闭浏览器页面，程序会在 30 秒后自动退出
- 需要彻底关闭时，请点击界面右上角红色「✕ 退出」按钮
- 登录、会员可见、地区受限或高画质内容可能需要对应平台有效 Cookie；Cookie 只提供登录态，不能绕过付费、地区或 DRM 限制
- Niconico 720P 及以上画质需要配置登录 Cookie
- Bilibili 1080P 及以上画质通常需要配置登录 Cookie
- Fantia 仅支持 `cookies.txt` 文件模式，不支持浏览器提取
- FANBOX 凭据使用对应账号的 Cookie；匿名访问不能取得需要登录或赞助权限的正文与附件，公开封面也不代表正文可访问
- Rplay 登录内容需在 Firefox 中具有有效登录态和相应观看权限；Twitch 转播还受源频道的权限与直播状态限制
- 自动更新要求 Release 提供有效 SHA-256，并会校验文件大小和 Windows EXE 格式；缺少有效摘要时请从 Release 页面手动下载更新
- NicoChannel 直播需在 Firefox 登录以提取令牌
- `twitcasting_passwords.xlsx` 以明文保存密码，除非获得明确授权，请勿发送给其他人
- Withny 直播监控由 `withny-dl` 配置驱动；HAR、配置文件和凭据可能包含登录信息，请妥善保管
- 使用本工具下载内容时请遵守平台规则和当地法律法规

### 已知问题（待后续修复）

1. **队列状态卡住**：FANBOX 排队任务暂停或启动失败后，对应队列任务可能已经取消或失败，而 FANBOX 归档记录仍显示 `queued` 并无法继续。请核对归档记录与日志，必要时重启程序。
2. **混合批量重新下载确认**：FANBOX 与其他平台混合批量下载时，命中归档后的重新下载确认可能失败。建议将 FANBOX 与其他平台拆成独立任务提交。
3. **缩略图格式校验**：原图为 PNG/GIF、缩略图为 JPEG 时，选择缩略图质量可能按原图格式校验而失败。建议暂用原图质量。
4. **预览后受限帖封面遗漏**：FANBOX 先预览再下载时，可能漏掉受限帖可公开获取的封面。请人工检查结果；公开封面不授予正文或附件访问权限。
5. **长间隔工作租约失效**：FANBOX 请求间隔达到或超过 120 秒时，工作租约可能失效，而任务仍显示 `running`。本版请避免此设置；出现时核对日志并重启相关任务。
6. **独立扫描 CLI 匿名设置**：`--fanbox-scan` 当前忽略配置中的 `FANBOX_ANONYMOUS`。如需匿名扫描，必须显式传入 `--anonymous`；WebUI 和 `--fanbox-download` 不受此匿名设置问题影响。

以上六项为 v2.7.0 仍保留的已知问题，待后续版本修复；本次仅修复单任务执行器停止路由。

## 💡 推荐配置

- Cookie 模式：`cookies.txt` 文件模式；Rplay 登录使用独立 Firefox 设置
- 输出格式：MP4
- 音视频模式：合并输出
- 下载限速：推荐设置为 5–10 MB/s。高速或大批量下载可能导致 IP 或账号被限制或封禁，相关后果由使用者自行承担
- FANBOX：先用少量帖子预览，检查筛选、权限和输出内容；请求间隔请避免达到或超过 120 秒
- 直播录制：根据场景选择「蹲开播」「追开播」或「加入时开录」；是否可追开播由平台能力决定
- 关闭方式：使用 WebUI 右上角「✕ 退出」按钮

