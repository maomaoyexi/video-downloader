# v2.3.0 WebUI

## 🎉 发布说明

多平台视频下载工具 v2.3.0 WebUI 版于 2026-08-16 发布。本次版本新增 Twitter/X、TwitCasting 与 NicoChannel 支持，以及 Withny 已授权历史存档 HAR 下载和直播监控录制，并扩展音频格式转换、EBU R128 响度统一和音量调整工具。WebUI 完成模块化改版，加入正常蓝灰中性配色、明暗主题组合和音频工具排版优化。主程序文件名升级为 `视频下载工具v2.3.0-GUI.exe`，原有设置、预设、Cookie、下载记录及下载目录全部兼容。

## 🤝 本次贡献者

- [ErgouTree (@ergou10086)](https://github.com/ergou10086) - 制作 NicoChannel、Twitter/X、TwitCasting 直播支持、v2.3.0 UI 改版及音频处理工具
- [猫猫葉汐A_spy (@maomaoyexi)](https://github.com/maomaoyexi) - 制作 Withny 已授权历史存档下载、直播监控录制、中性配色切换及本版 UI 调整
- [DarkKandaoMaster（强壮的砍刀）](https://github.com/DarkKandaoMaster) - v2.1.0 WebUI 重构基础

## ✨ 主要更新

- 🐦 **Twitter/X 支持** - 支持推文视频与 Space 音频，识别 Space 为直播任务
- 📡 **TwitCasting 支持** - 支持直播、录播、历史列表以及密码保护内容交互
- 📺 **NicoChannel 支持** - 支持频道视频与直播，并通过 Firefox localStorage JWT 完成登录鉴权
- 📦 **Withny 支持** - 从 HAR 安全保存已授权历史存档，也可通过 withny-dl 配置监控和录制直播
- 🎵 **音频工具扩展** - 新增批量格式转换、EBU R128 单次/双次响度统一和增益/限幅器音量调整
- 🎨 **UI 与配色** - 模块化样式、图标与响应式界面，新增正常蓝灰中性配色和暖色配色切换
- ✅ **回归保护** - 自动化测试扩展至 129 项
- 🔄 **兼容升级** - 原有配置、预设、Cookie、历史记录和下载目录继续兼容

## 📦 下载说明

### 文件清单

| 文件 | 说明 | 必须 |
|------|------|------|
| `视频下载工具v2.3.0-GUI.exe` | 主程序，单文件绿色版 | ✅ |
| `视频下载工具v2.3.0-依赖包.zip` | 通用依赖包（下载工具 + 帮助文档） | ✅ |
| `视频下载工具v2.3.0-源码版.zip` | Python 源码、测试、资源与文档 | 可选 |

> 💡 **依赖包已包含**：yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe、withny-dl-windows-amd64.exe、docs 帮助文档、changelog.html 和 CREDITS.txt。NicoChannel 还需要单独准备 `nicochannel.zip` 并放在主程序同一目录。

### SHA-256

```text
6393258D9D15B59521C5BDD847F9565B6AA2001D351AD3D7E6279B5B9E27F1C2  视频下载工具v2.3.0-GUI.exe
依赖包与源码 ZIP 的 SHA-256 请以 GitHub Release 页面为准。
```

## 🚀 快速开始

### 新用户安装
1. 下载 `视频下载工具v2.3.0-GUI.exe` 和 `视频下载工具v2.3.0-依赖包.zip`
2. 新建一个文件夹（如「视频下载工具」），将 `视频下载工具v2.3.0-GUI.exe` 放入其中
3. 解压依赖包，将里面的**全部内容**解压到 exe 同一目录
4. 双击 `视频下载工具v2.3.0-GUI.exe` 运行，自动打开浏览器界面
5. （可选）配置 Cookie 以支持会员/高画质内容

### 老用户升级
1. 关闭正在运行的旧版本程序（点击右上角「✕ 退出」按钮）
2. 只需下载新版 `视频下载工具v2.3.0-GUI.exe`，替换旧版 exe 即可
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
