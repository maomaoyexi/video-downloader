# v1.9.4 WebUI

## 🎉 发布说明

四平台极致音画下载工具 v1.9.4 WebUI 版发布！本次更新对自动更新功能进行了优化，统一使用 GitHub Releases 作为唯一更新源，版本检测更加稳定可靠。此版本为维护更新，无功能性新增，原有设置、预设、下载记录全部兼容，直接替换 exe 即可升级。

## ✨ 主要更新

- 🔧 **自动更新功能优化** - 统一使用 GitHub Releases 作为唯一更新源，精简更新检查逻辑，减少不必要的网络请求
- 🔗 **更新源地址统一** - 自动更新 API 地址为 `https://api.github.com/repos/maomaoyexi/video-downloader/releases/latest`
- ⬇️ **直连下载** - 下载链接统一使用 `browser_download_url` 直连地址，一键下载替换更新
- 📝 **文件名适配** - 自动检测新版本 exe 文件名，适配新的命名规范（去掉 -GUI 后缀）

## 📦 下载说明

### 文件清单

| 文件 | 说明 | 必须 |
|------|------|------|
| `视频下载工具v1.9.4.exe` | 主程序，单文件绿色版 | ✅ |
| `视频下载工具v1.9.4-依赖包.zip` | 完整依赖包（包含所有依赖 exe + 帮助文档） | ✅ |

> 💡 **依赖包已包含**：yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe（可选）+ docs 帮助文档 + changelog.html，解压后无需再下载任何文件。

## 🚀 快速开始

### 新用户安装
1. 下载 `视频下载工具v1.9.4.exe` 和 `视频下载工具v1.9.4-依赖包.zip`
2. 新建一个文件夹（如「视频下载工具」），将 `视频下载工具v1.9.4.exe` 放入其中
3. 解压依赖包，将里面的**全部内容**解压到 exe 同一目录
4. 双击 `视频下载工具v1.9.4.exe` 运行，自动打开浏览器界面
5. （可选）配置 Cookie 以支持会员/高画质内容

### 老用户升级
1. 关闭正在运行的旧版本程序（点击右上角「✕ 退出」按钮）
2. 只需下载新版 `视频下载工具v1.9.4.exe`，替换旧版 exe 即可
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

## 💡 推荐配置

- Cookie模式：cookies.txt文件模式（全平台通用最稳定）
- 输出格式：MP4
- 编码：兼容优先（H.264，所有设备可直接播放）
- 音视频模式：合并输出
- 关闭方式：使用右上角「✕ 退出」按钮

---

**如果这个工具对您有帮助，欢迎给个Star ⭐**
