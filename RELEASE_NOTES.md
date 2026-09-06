# v2.4.0 WebUI

## 🎉 发布说明

多平台视频下载工具 v2.4.0 WebUI 版于 2026-09-05 发布。本次版本以重构后的 WebUI 为基础，新增普通下载附带字幕和独立字幕下载工具，并完善下载进度、停止流程、命令诊断、音频提取与 TwitCasting 兼容性。主程序文件名升级为 `视频下载工具v2.4.0-GUI.exe`，原有设置、预设、Cookie、下载记录及下载目录全部兼容。

## 🤝 本次贡献者

- [ZheYi101](https://github.com/ZheYi101) - 提供字幕下载功能
- [猫猫葉汐A_spy (@maomaoyexi)](https://github.com/maomaoyexi) - 修复字幕任务生命周期、停止流程、界面适配与合并问题
- [DarkKandaoMaster（强壮的砍刀）](https://github.com/DarkKandaoMaster) - 提供本版 UI 重构
- [ErgouTree (@ergou10086)](https://github.com/ergou10086) - 提供本版其他更新与修复

## ✨ 主要更新

- **字幕下载** - 普通视频完成后可继续下载独立字幕，字幕失败不影响视频成功状态
- **独立字幕工具** - 支持多链接、人工字幕、自动字幕、全部字幕和自定义语言
- **默认行为** - 字幕默认关闭；开启后默认下载中文，全部字幕请求遇到 HTTP 429 时自动缩小范围重试
- **任务生命周期** - 字幕任务接入统一任务管理，支持停止、退出清理、任务互斥和超时终止
- **WebUI 重构** - 更新设置、工具箱、日志、历史记录和响应式布局，字幕控件与新版设计保持一致
- **下载稳定性** - 改进媒体阶段进度、即时停止、可取消音频提取、敏感命令脱敏和 TwitCasting FFmpeg 回退
- **回归保护** - 自动化测试扩展至 162 项，并覆盖字幕与 TwitCasting 重试组合场景
- 🔄 **兼容升级** - 原有配置、预设、Cookie、历史记录和下载目录继续兼容

## 📦 下载说明

### 文件清单

| 文件 | 说明 | 必须 |
|------|------|------|
| `视频下载工具v2.4.0-GUI.exe` | 主程序，单文件绿色版 | ✅ |
| `视频下载工具v2.4.0-依赖包.zip` | 通用依赖包（下载工具 + 帮助文档） | ✅ |
| `视频下载工具v2.4.0-源码版.zip` | Python 源码、测试、资源与文档 | 可选 |

> 💡 **依赖包已包含**：yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe、withny-dl-windows-amd64.exe、docs 帮助文档、changelog.html 和 CREDITS.txt。NicoChannel 还需要单独准备 `nicochannel.zip` 并放在主程序同一目录。

### SHA-256

```text
79823330ACC99931643E8FBBA5EE0F6DAFC9724B0F91F67FCF04FE2502F1B575  视频下载工具v2.4.0-GUI.exe
68A598F9642E3215DBDF5963209D6FEA7ADCDD45539B9113370FCB41C2442E43  视频下载工具v2.4.0-依赖包.zip
源码 ZIP 的 SHA-256 请以 GitHub Release 页面为准。
```

## 🚀 快速开始

### 新用户安装
1. 下载 `视频下载工具v2.4.0-GUI.exe` 和 `视频下载工具v2.4.0-依赖包.zip`
2. 新建一个文件夹（如「视频下载工具」），将 `视频下载工具v2.4.0-GUI.exe` 放入其中
3. 解压依赖包，将里面的**全部内容**解压到 exe 同一目录
4. 双击 `视频下载工具v2.4.0-GUI.exe` 运行，自动打开浏览器界面
5. （可选）配置 Cookie 以支持会员/高画质内容

### 老用户升级
1. 关闭正在运行的旧版本程序（点击右上角「✕ 退出」按钮）
2. 只需下载新版 `视频下载工具v2.4.0-GUI.exe`，替换旧版 exe 即可
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
