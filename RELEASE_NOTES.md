# v1.9.5 WebUI

## 🎉 发布说明

四平台极致音画下载工具 v1.9.5 WebUI 版于 2026-07-17 发布！本次更新完成了核心代码模块化，并集中增强直播识别、封面处理、批量下载、停止可靠性、配置存储、SSE 状态恢复和自动更新安全。主程序文件名统一为 `视频下载工具v1.9.5-GUI.exe`，原有设置、预设、下载记录及下载目录全部兼容，直接替换 exe 即可升级。

## ✨ 主要更新

- 🎮 **直播识别增强** - 新增 YouTube `/live` 直播识别，Twitch、Niconico 与批量任务统一使用准确的直播判定
- 🖼️ **封面功能完善** - 下载并转换独立 JPG 封面，在 MP4/MKV 等兼容输出中自动嵌入
- 🛑 **停止逻辑重构** - 统一管理任务代际、取消状态和子进程树，停止完成前禁止新任务启动
- 📊 **批量下载修复** - 清洗无效链接，按有效 URL 统计进度，并正确处理直播参数和停止状态
- 💾 **配置存储增强** - 配置、预设和历史增加并发保护与原子写入，损坏配置可安全回退
- 🌐 **WebUI 状态增强** - SSE 重连恢复下载、批量和更新状态，慢连接使用有界队列避免内存持续增长
- 🔄 **GitHub 版本检查** - 统一通过 GitHub Releases 检查和分发新版本
- 🛡️ **可信下载限制** - 仅允许配置的可信更新来源，并将更新文件限制在 512 MB 以内
- 🔐 **SHA-256 校验** - 从发布资产或发布说明读取摘要，缺少有效 SHA-256 时禁止自动更新
- ✅ **更新文件验证** - 下载完成后校验文件大小、SHA-256 与 Windows EXE 格式，再执行替换重启
- 🧩 **核心代码模块化** - 下载、HTTP/SSE、存储、工具箱、更新、命令构建和页面已拆分为独立模块

## 📦 下载说明

### 文件清单

| 文件 | 说明 | 必须 |
|------|------|------|
| `视频下载工具v1.9.5-GUI.exe` | 主程序，单文件绿色版 | ✅ |
| `视频下载工具v1.9.5-依赖包.zip` | 完整依赖包（包含所有依赖 exe + 帮助文档） | ✅ |

> 💡 **依赖包已包含**：yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe（可选）+ docs 帮助文档 + changelog.html，解压后无需再下载任何文件。

### SHA-256

```text
33e08fcf893608dfede4ec6550bb7f5e6aa296ba6f6b8e7b861942ea20650c8c  视频下载工具v1.9.5-GUI.exe
392cf0af1fab3dd52df1b92490a8030060f809fbe8285e431b50927b5d7eefa9  视频下载工具v1.9.5-依赖包.zip
```

## 🚀 快速开始

### 新用户安装
1. 下载 `视频下载工具v1.9.5-GUI.exe` 和 `视频下载工具v1.9.5-依赖包.zip`
2. 新建一个文件夹（如「视频下载工具」），将 `视频下载工具v1.9.5-GUI.exe` 放入其中
3. 解压依赖包，将里面的**全部内容**解压到 exe 同一目录
4. 双击 `视频下载工具v1.9.5-GUI.exe` 运行，自动打开浏览器界面
5. （可选）配置 Cookie 以支持会员/高画质内容

### 老用户升级
1. 关闭正在运行的旧版本程序（点击右上角「✕ 退出」按钮）
2. 只需下载新版 `视频下载工具v1.9.5-GUI.exe`，替换旧版 exe 即可
3. 原有 `settings.ini`、`presets.json`、`cookies.txt`、`download_history.json` 全部兼容
4. 原有依赖文件（yt-dlp.exe、ffmpeg.exe 等）无需重新下载，继续使用即可
5. 双击运行新版 exe 即可

## 📖 文档

- [使用教程](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E4%BD%BF%E7%94%A8%E6%95%99%E7%A8%8B.txt)
- [Cookie配置指南](https://github.com/maomaoyexi/video-downloader/blob/main/docs/cookies%E9%97%AE%E9%A2%98%E7%AD%94%E7%96%91.txt)
- [常见问题](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98%E7%AD%94%E7%96%91.txt)
- [错误码说明](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E9%94%99%E8%AF%AF%E7%A0%81.txt)
- [更新日志](https://github.com/maomaoyexi/video-downloader/blob/main/changelog.html)

## ⚠️ 注意事项

- 使用过程中不要关闭控制台窗口（它是后端服务器）
- 关闭浏览器标签页不会停止下载，下载完成后30秒自动退出
- 需要彻底关闭时，点击界面右上角红色「✕ 退出」按钮
- Niconico 720P及以上画质需要配置登录Cookie
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
