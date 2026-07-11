# v1.9.3 WebUI (p4)

## 🎉 发布说明

四平台极致音画下载工具 v1.9.3 WebUI 版正式发布！全面升级为浏览器界面，彻底解决tkinter缺失问题，双击即用。

## ✨ 主要更新

- 🌐 **全新WebUI界面** - 内置HTTP服务器，自动打开浏览器，深色主题
- 🎬 **四大平台支持** - YouTube / Twitch / Niconico / Fantia
- 🎮 **直播录制** - Twitch/Niconico直播自动从开头录制
- 💾 **配置预设** - 保存常用设置，一键切换
- 📜 **下载历史** - 自动记录每次下载
- 🔄 **断点续传** - 默认启用，网络中断自动续传
- 🧰 **8个工具箱工具** - 批量下载、WAV转MP3、更新yt-dlp等
- 🛡️ **进程管理** - 关闭网页30秒自动退出，无残留进程

## 🔧 p4补丁修复（累计14个问题）

- ✅ 修复日文/中文标题显示乱码问题
- ✅ 修复Niconico直播下载无进度显示
- ✅ 修复下载进度卡在0%不动的问题
- ✅ 修复停止按钮点击无效问题（三级终止策略）
- ✅ 修复启动下载后弹出CMD黑窗口问题
- ✅ 修复孤儿进程残留问题
- ✅ 修复VOD视频被误判为直播问题
- ✅ 修复录制时长重复显示问题
- ✅ 修复Niconico下载超时问题
- ✅ 添加关闭网页自动退出机制
- ✅ 添加退出按钮，支持彻底关闭工具
- ✅ 下载中关闭页面弹出确认提示

## 📦 下载说明

### 文件清单

| 文件 | 说明 | 必须 |
|------|------|------|
| `视频下载工具v1.9.3-GUI.exe` | 主程序 | ✅ |
| `yt-dlp.exe` | 下载核心 | ✅ |
| `ffmpeg.exe` | 音视频处理 | ✅ |
| `ffprobe.exe` | 媒体信息探测 | ✅ |
| `fantiadl.exe` | Fantia下载器 | ⭕ 可选 |

### 依赖下载地址

- **yt-dlp.exe**: https://github.com/yt-dlp/yt-dlp/releases
- **ffmpeg.exe + ffprobe.exe**: https://www.gyan.dev/ffmpeg/builds/ （下载 `ffmpeg-release-full.7z`，解压后从bin目录取出）

## 🚀 快速开始

1. 下载所有必需文件放到同一文件夹
2. 双击 `视频下载工具v1.9.3-GUI.exe`
3. 程序自动启动并打开浏览器界面
4. （可选）配置Cookie以支持会员/高画质内容

## 📖 文档

- [使用教程](https://github.com/3121673169/video-downloader/blob/main/docs/%E4%BD%BF%E7%94%A8%E6%95%99%E7%A8%8B.txt)
- [Cookie配置指南](https://github.com/3121673169/video-downloader/blob/main/docs/cookies%E9%97%AE%E9%A2%98%E7%AD%94%E7%96%91.txt)
- [常见问题](https://github.com/3121673169/video-downloader/blob/main/docs/%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98%E7%AD%94%E7%96%91.txt)
- [错误码说明](https://github.com/3121673169/video-downloader/blob/main/docs/%E9%94%99%E8%AF%AF%E7%A0%81.txt)
- [更新日志](https://github.com/3121673169/video-downloader/blob/main/changelog.html)

## ⚠️ 注意事项

- 使用过程中不要关闭控制台窗口（它是后端服务器）
- 关闭浏览器标签页不会停止下载，下载完成后30秒自动退出
- 需要彻底关闭时，点击界面右上角红色「✕ 退出」按钮
- Niconico 720P及以上画质需要配置登录Cookie
- Fantia仅支持cookies.txt文件模式

## 💡 推荐配置

- Cookie模式：cookies.txt文件模式（全平台通用最稳定）
- 输出格式：MP4
- 编码：兼容优先（H.264，所有设备可直接播放）
- 音视频模式：合并输出
- 关闭方式：使用右上角「✕ 退出」按钮

---

**如果这个工具对您有帮助，欢迎给个Star ⭐**
