# v2.1.0 WebUI

## 🎉 发布说明

多平台视频下载工具 v2.1.0 WebUI 版于 2026-07-22 发布。本次版本完成 WebUI 与交互重构，新增多行 URL 批量下载、命令行模式、下载历史中的已下载封面预览和 MP3 音频单独下载。原有封面下载与嵌入功能保持不变。主程序文件名升级为 `视频下载工具v2.1.0-GUI.exe`，原有设置、预设、下载记录及下载目录全部兼容。

## 🤝 本次贡献者

- [DarkKandaoMaster（强壮的砍刀）](https://github.com/DarkKandaoMaster) - 重构 v2.1.0 WebUI 界面与交互
- [ErgouTree (@ergou10086)](https://github.com/ergou10086) - 贡献 MP3 音频单独下载

## ✨ 主要更新

- 🎨 **WebUI 重构** - 采用侧栏工作区、独立日志页、统一图标与响应式导航
- 🧾 **多行链接下载** - 下载页可直接粘贴多行 URL 并进入批量队列
- 🖼️ **历史封面预览** - 下载历史展示已下载封面的缩略图并支持点击大图预览，原有封面下载和嵌入功能保持不变
- ⌨️ **命令行模式** - 支持直接传入 URL、`--batch` 和 `--help`
- 🎵 **MP3 音频下载** - 支持下载视频时单独保存 MP3 音频
- ✅ **回归保护** - 自动化测试扩展至 98 项
- 🔄 **兼容升级** - 原有配置、预设、Cookie、历史记录和下载目录继续兼容

## 📦 下载说明

### 文件清单

| 文件 | 说明 | 必须 |
|------|------|------|
| `视频下载工具v2.1.0-GUI.exe` | 主程序，单文件绿色版 | ✅ |
| `视频下载工具v2.1.0-依赖包.zip` | 完整依赖包（包含所有依赖 exe + 帮助文档） | ✅ |

> 💡 **依赖包已包含**：yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe（可选）+ docs 帮助文档 + changelog.html + CREDITS.txt，解压后无需再下载任何文件。

### SHA-256

```text
dddafd70ad7ad9e73388e93d51abc6e862d8d5fefe4ac23633d317895ab1fb80  视频下载工具v2.1.0-GUI.exe
ecb7bec645725bf666ab1de6c9abc9a5f7492e1ccaddd48e06efd26b3932cbeb  视频下载工具v2.1.0-依赖包.zip
```

## 🚀 快速开始

### 新用户安装
1. 下载 `视频下载工具v2.1.0-GUI.exe` 和 `视频下载工具v2.1.0-依赖包.zip`
2. 新建一个文件夹（如「视频下载工具」），将 `视频下载工具v2.1.0-GUI.exe` 放入其中
3. 解压依赖包，将里面的**全部内容**解压到 exe 同一目录
4. 双击 `视频下载工具v2.1.0-GUI.exe` 运行，自动打开浏览器界面
5. （可选）配置 Cookie 以支持会员/高画质内容

### 老用户升级
1. 关闭正在运行的旧版本程序（点击右上角「✕ 退出」按钮）
2. 只需下载新版 `视频下载工具v2.1.0-GUI.exe`，替换旧版 exe 即可
3. 原有 `settings.ini`、`presets.json`、`cookies.txt`、`download_history.json` 全部兼容
4. 原有依赖文件（yt-dlp.exe、ffmpeg.exe 等）无需重新下载，继续使用即可
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
