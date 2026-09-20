# v2.5.0 WebUI

## 🎉 发布说明

多平台视频下载工具 v2.5.0 WebUI 版于 2026-09-18 发布。本次版本重构 WebUI 视觉与交互体系，重点改进 TwitCasting 多初始化段归档下载、代理直连行为和 YouTube PO Token 获取，并增加自定义 yt-dlp 参数及运行目录迁移。主程序文件名升级为 `视频下载工具v2.5.0-GUI.exe`，原有设置、预设、Cookie 和下载记录继续兼容。

## 🤝 本次贡献者

- [DarkKandaoMaster](https://github.com/DarkKandaoMaster) - WebUI 视觉与交互体系重构（`dcdf010`，合并为 `1db8864`）
- [ErgouTree (@ergou10086)](https://github.com/ergou10086) - 设置控件补充（`c865dc1`）、TwitCasting 下载与进度增强（`3ca46de`、`3dab5ec`）、BgUtils Provider 集成（`f3547b4`）及依赖和下载目录收拢（`a24b57f`）

合并提交和本地保存提交不重复计入功能贡献。

## ✨ 主要更新

- **WebUI 视觉与交互重构** - 统一页面布局、视觉层级、控件样式和交互反馈，并补齐设置页所需控件
- **TwitCasting 并发预取** - 多初始化段归档按下载线程数并发获取分片，生成本地播放列表后交由 FFmpeg 封装
- **安全回退与续传** - 并发预取失败时恢复远程播放列表并回退 FFmpeg 串行下载，保留已完成分片供下次复用
- **代理直连修复** - 关闭代理时显式要求 yt-dlp 直连，并清理子进程继承的 HTTP、HTTPS 和 SOCKS 代理环境变量
- **YouTube PO Token** - 可选托管本地 BgUtils Provider，按需启动、复用健康实例并在程序退出时清理自有进程
- **自定义 yt-dlp 参数** - 支持持久化默认参数和仅用于当前单条或批量任务的临时参数
- **进度反馈增强** - 接入 TwitCasting 分片百分比、速度、ETA 和媒体阶段，并扩展 FFmpeg 进度识别
- **目录结构升级** - 依赖统一放入 `dependency/`，下载、日志和归档统一放入 `download/`，首次启动安全迁移旧版文件
- **兼容改进** - Firefox 默认配置改为自动探测，旧版根目录依赖和未迁移数据仍可继续使用
- **回归保护** - 自动化测试覆盖命令构建、代理直连、Provider 生命周期、目录迁移和 TwitCasting 回退链路

## 📦 下载说明

### 文件清单

| 文件 | 说明 | 必须 |
|------|------|------|
| `video-downloader-v2.5.0-GUI.exe` | 主程序，单文件绿色版 | ✅ |
| `video-downloader-v2.5.0-dependencies.zip` | 通用依赖包（下载工具 + 帮助文档） | ✅ |
| `video-downloader-v2.5.0-source.zip` | Python 源码、测试、资源与文档 | 可选 |

> 💡 **依赖包已包含**：`dependency/` 中的 yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe、withny-dl-windows-amd64.exe 和插件。NicoChannel 还需要单独准备 `nicochannel.zip` 并放入 `dependency/`。

### SHA-256

```text
FA828DB2260B4E4E44D9A873759FA47EC8BE1CA745F8DECC01FA79F9B4DBA606  video-downloader-v2.5.0-GUI.exe
D607CAF3B8B0B5D72FE6B3A2BE92EBA831821C535CD5EDBAC04C891D47EDBA49  video-downloader-v2.5.0-dependencies.zip
9B59768C8163B4FCC35E4192C3F9E4747D32180699A90A7233889D7F9902F914  video-downloader-v2.5.0-source.zip
```

## 🚀 快速开始

### 新用户安装
1. 下载 `video-downloader-v2.5.0-GUI.exe` 和 `video-downloader-v2.5.0-dependencies.zip`
2. 新建一个文件夹（如「视频下载工具」），将 `video-downloader-v2.5.0-GUI.exe` 放入其中
3. 解压依赖包，将其中的 `dependency` 文件夹完整放到 exe 同一目录
4. 双击 `video-downloader-v2.5.0-GUI.exe` 运行，自动打开浏览器界面
5. （可选）配置 Cookie 以支持会员/高画质内容

### 老用户升级
1. 关闭正在运行的旧版本程序（点击右上角「✕ 退出」按钮）
2. 下载新版 `video-downloader-v2.5.0-GUI.exe` 替换旧版 exe，并解压 v2.5.0 依赖包补齐 Provider 与 TwitCasting 插件
3. 原有 `settings.ini`、`presets.json`、`cookies.txt` 全部兼容，`download_history.json` 会迁入 `download/`
4. 原有依赖、平台下载目录和归档文件无需手动整理，首次启动会安全迁移到 `dependency/` 与 `download/`；程序仍兼容无法迁移的旧版根目录依赖
5. 双击运行新版 exe 即可

## 📖 文档

- [使用教程](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E4%BD%BF%E7%94%A8%E6%95%99%E7%A8%8B.txt)
- [Cookie配置指南](https://github.com/maomaoyexi/video-downloader/blob/main/docs/cookies%E9%97%AE%E9%A2%98%E7%AD%94%E7%96%91.txt)
- [常见问题](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98%E7%AD%94%E7%96%91.txt)
- [错误码说明](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E9%94%99%E8%AF%AF%E7%A0%81.txt)
- [更新日志](https://github.com/maomaoyexi/video-downloader/blob/main/resource/templates/changelog.html)

## ⚠️ 注意事项

- 使用过程中不要关闭控制台窗口（它是后端服务器）
- 关闭浏览器标签页不会停止下载，下载完成后30秒自动退出
- 需要彻底关闭时，点击界面右上角红色「✕ 退出」按钮
- Niconico 720P及以上画质需要配置登录Cookie
- Bilibili 1080P及以上画质通常需要配置登录Cookie
- Fantia仅支持cookies.txt文件模式
- 自动更新要求 Release 提供有效 SHA-256；缺少摘要时请手动下载并核验

## 💡 推荐配置

- Cookie模式：cookies.txt文件模式（全平台通用最稳定）
- 输出格式：MP4
- 编码：兼容优先（H.264，所有设备可直接播放）
- 音视频模式：合并输出
- 关闭方式：使用右上角「✕ 退出」按钮

---

**如果这个工具对您有帮助，欢迎给个Star ⭐**
