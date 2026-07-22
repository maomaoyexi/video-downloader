# 多平台视频下载工具 v2.1.0 WebUI
支持 YouTube / Bilibili / Twitch / Niconico / Fantia 五个平台的视频/直播下载工具，采用浏览器界面。Release 的 EXE 绿色版无需安装 Python；源码运行版使用 Python 3 启动。

![Version](https://img.shields.io/badge/version-v2.1.0%20WebUI-purple)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> v2.1.0 WebUI 由 [DarkKandaoMaster（强壮的砍刀）](https://github.com/DarkKandaoMaster) 重构；MP3 音频单独下载由 [ErgouTree (@ergou10086)](https://github.com/ergou10086) 贡献。

## ✨ 功能特性

- 🌐 **全新WebUI界面** - 内置HTTP服务器，自动打开浏览器，深色主题，响应式设计
- 🎬 **五平台支持** - YouTube、Bilibili、Twitch、Niconico、Fantia，自动识别平台
- 📺 **Bilibili 支持** - 支持普通视频、直播和多 P 分集选择
- 🎮 **直播录制** - 支持 YouTube、Twitch、Niconico 直播识别、从头录制和实时状态
- 💾 **配置预设** - 保存常用设置组合，一键切换
- 📜 **下载历史** - 自动记录每次下载，最多500条
- 🔄 **断点续传** - 默认启用，网络中断后自动续传
- 📊 **批量下载** - 支持从TXT文件批量导入链接
- ⌨️ **命令行模式** - 支持直接传入 URL 或通过 `--batch` 批量下载
- 🧾 **多行链接** - 下载页可直接粘贴多行 URL，按顺序加入批量队列
- 🖼️ **封面处理** - 下载独立 JPG 封面，并在兼容格式中自动嵌入
- 🎵 **MP3 音频下载** - 支持在下载视频时单独保存 MP3 音频
- 🍪 **Cookie支持** - 支持cookies.txt文件模式
- ⚡ **硬件加速** - 支持NVIDIA NVENC、Intel QSV、AMD AMF
- 🔄 **自动更新** - 启动后通过 GitHub Releases 检查新版本，校验通过后自动更新替换
- 🧰 **工具箱** - 内置WAV转MP3、yt-dlp更新、临时文件清理等8个工具
- 🛡️ **进程管理** - 关闭网页30秒后自动退出，无残留进程

## 🚀 快速开始

1. 从 [Releases](https://github.com/maomaoyexi/video-downloader/releases) 下载最新版本（两个文件都要下载）：
   - `视频下载工具v2.1.0-GUI.exe` - 主程序
   - `视频下载工具v2.1.0-依赖包.zip` - 完整依赖包（包含所有依赖exe和帮助文档）
2. 新建一个文件夹（如「视频下载工具」），将 `视频下载工具v2.1.0-GUI.exe` 放入其中
3. 解压依赖包，将里面的**全部内容**（所有exe文件、docs文件夹、changelog.html等）解压到主程序同一目录
4. 双击 `视频下载工具v2.1.0-GUI.exe` 运行，自动打开浏览器界面

> 💡 **提示**：依赖包已包含所有必需文件（yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe），解压后无需再下载任何东西。首次运行会自动生成配置文件、下载目录等。所有文件都保存在exe同目录下，绿色软件无需安装。

### 源码运行版

保持 `视频下载工具v2.1.0-GUI.py`、`video_downloader/` 与各依赖 EXE 位于同一目录，安装 Python 3 后运行：

```powershell
python ".\视频下载工具v2.1.0-GUI.py"
```

源码运行版不会用下载到的 EXE 自动覆盖 Python 源码；升级源码时请手动替换主脚本与 `video_downloader/` 目录。

## 📖 使用说明

### 单视频下载
1. 在「下载」页面粘贴视频链接
2. 点击「开始下载」
3. 实时查看进度、速度、剩余时间

### 批量下载
1. 进入「工具箱」页面
2. 点击「生成链接模板」创建 `urls.txt`
3. 编辑 `urls.txt`，每行一个链接（支持混合平台）
4. 点击「TXT批量下载」开始批量下载

### Twitch直播录制
直接粘贴主播频道URL（如 `https://www.twitch.tv/xqc`）即可从直播开头录制，停止则结束录制。文件自动保存到 `Twitch/主播名/直播/` 目录。

### YouTube / Niconico 直播录制
YouTube 使用明确的 `/live` 直播链接，Niconico 使用 `live.nicovideo.jp` 或 `live2.nicovideo.jp` 链接。程序会自动进入直播模式，并实时显示录制时长、大小、速度和分片状态。

### Bilibili 下载
粘贴 Bilibili 视频或直播链接后程序会自动识别。多 P 视频可按设置下载全部分集或弹出分集选择器；1080P 及以上画质通常需要在程序目录配置 `cookies.txt`。

### 配置预设
1. 在「设置」页面调整好各项参数
2. 在「配置预设」区域输入预设名称
3. 点击「保存」按钮
4. 之后可随时从下拉框选择预设一键加载

### 自动更新
程序启动后3秒自动通过 GitHub Releases 静默检查更新。检测到新版本时右上角显示「⬆ 有更新」徽标，点击后可一键下载；程序会校验可信下载来源、文件大小、Windows EXE 格式及 SHA-256，校验通过后自动替换重启，所有配置和下载记录保留。

## ⚙️ 配置选项

| 设置项 | 说明 | 默认值 |
|--------|------|--------|
| 分辨率 | best/2160/1440/1080/720/480/360 | best |
| 编码 | best/h264/av1/vp9 | best |
| 音频质量 | best/192/128 | best |
| 输出格式 | mp4/mkv/webm | mp4 |
| 合并模式 | 合并/分离 | 合并 |
| 线程数 | 下载线程数 | 4 |
| 代理 | HTTP/SOCKS5代理支持 | 关闭 |
| Cookie | cookies.txt文件模式 | 文件模式 |
| 硬件加速 | CPU/NVENC/QSV/AMF | CPU |

## 🍪 Cookie配置

对于需要登录才能观看的视频（如年龄限制、会员内容、Niconico高画质），需要配置Cookie：

1. 安装浏览器扩展「Get cookies.txt LOCALLY」（Chrome/Edge/Firefox均支持，纯本地运行）
2. 登录对应平台（YouTube/Twitch/Niconico/Fantia）
3. 在目标平台页面点击扩展图标，导出 **Netscape格式** Cookie
4. 将导出的文件重命名为 `cookies.txt`，放到exe同目录
5. 重启程序即可生效

> ⚠️ **注意**：Fantia仅支持cookies.txt文件模式，不支持浏览器提取。Cookie仅传递登录态，不能绕过付费墙。

## 📂 目录结构

```
工具目录/
├── 视频下载工具v2.1.0-GUI.exe # 主程序
├── yt-dlp.exe               # 下载核心
├── ffmpeg.exe               # 音视频处理
├── ffprobe.exe              # 媒体信息探测
├── deno.exe                 # JavaScript运行时
├── fantiadl.exe             # Fantia下载器（可选）
├── settings.ini             # 配置文件（自动生成）
├── presets.json             # 预设配置（自动生成）
├── cookies.txt              # Cookie文件（自行放置）
├── urls.txt                 # 批量下载链接（自行编辑）
├── download_history.json    # 下载历史（自动生成）
├── changelog.html           # 更新日志
├── CREDITS.txt              # 作者与贡献者
├── docs/                    # 帮助文档
│   ├── 使用教程.txt
│   ├── 常见问题答疑.txt
│   ├── 错误码.txt
│   └── cookies问题答疑.txt
├── logs/                    # 日志目录
├── YouTube/                 # YouTube下载目录
│   └── 上传者名/
│       └── 视频标题 [id].mp4
├── Twitch/                  # Twitch下载目录
│   ├── 主播名/
│   │   └── 视频标题 [id].mp4
│   └── 主播名/直播/
│       └── 直播标题 - 日期 id.mp4
├── Niconico/                # Niconico下载目录
├── Bilibili/                # Bilibili视频、直播及多P目录
└── Fantia/                  # Fantia下载目录
```

## 🔧 工具箱功能

- 📋 **TXT批量下载** - 从urls.txt读取链接批量下载
- 📝 **生成链接模板** - 生成带注释的urls.txt模板
- 🍪 **生成Cookie模板** - 生成Netscape格式cookies.txt模板
- 🔄 **更新yt-dlp** - 一键更新下载核心到最新版本
- 🗑️ **清理临时文件** - 清理下载产生的.part/.ytdl等临时文件
- 🎵 **WAV转MP3** - 批量音频转换，支持比特率选择
- 📂 **打开下载目录** - 在资源管理器中打开下载文件夹
- 📋 **打开日志目录** - 在资源管理器中打开日志文件夹

## ❓ 常见问题

**Q: 下载速度慢怎么办？**
> A: 1. 配置代理；2. 适当增加线程数；3. 在工具箱更新yt-dlp到最新版本。

**Q: 提示需要登录？**
> A: 配置Cookie，参考Cookie配置说明。

**Q: Niconico只能下载低画质？**
> A: 需要配置登录Cookie，游客身份仅能获取低清晰度。登录后导出cookies.txt即可。

**Q: 下载的文件在哪里？**
> A: 默认保存在exe同目录下对应平台名称的文件夹中，如YouTube/、Twitch/等。

**Q: 可以同时下载多个视频吗？**
> A: 同一时间只能运行一个下载任务，但批量下载会按顺序自动下载所有链接。

**Q: 关闭浏览器会中断下载吗？**
> A: 不会。下载在后台继续进行，下载完成后30秒自动退出。如需停止请点击「停止」按钮或右上角「✕ 退出」按钮。

**Q: 双击exe后浏览器没自动打开？**
> A: 查看控制台窗口显示的端口号（如 http://127.0.0.1:8765），手动在浏览器中输入该地址访问。

**Q: 老用户如何升级？**
> A: 只需下载新版 `视频下载工具v2.1.0-GUI.exe` 替换旧版exe即可，原有配置、下载记录、依赖文件全部无需改动。

## 📚 详细文档

更多详细说明请查看 `docs/` 目录下的文档：

- [📖 完整使用教程](docs/使用教程.txt) - 从安装到高级功能的完整指南
- [🍪 Cookie配置指南](docs/cookies问题答疑.txt) - Cookie配置详细说明和常见问题
- [❓ 常见问题答疑](docs/常见问题答疑.txt) - 常见问题的解决方案
- [⚠️ 错误码说明手册](docs/错误码.txt) - 下载错误码详解和排查流程
- [📋 更新日志](resource/templates/changelog.html) - 版本更新历史

## 📋 版本更新

v2.1.0 的完整更新内容、贡献者和升级说明请查看：

- [发布说明](RELEASE_NOTES.md)
- [内置更新日志](resource/templates/changelog.html)

## ⚠️ 免责声明

- 本工具仅供学习和个人使用，请遵守当地法律法规
- 请勿用于下载受版权保护的内容，除非您拥有相关权利
- 使用者需自行承担使用本工具产生的一切责任
- 各平台商标归其各自所有者所有

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 作者与贡献者

- 项目原版作者：[猫猫葉汐A_spy（GitHub：@maomaoyexi）](https://github.com/maomaoyexi)
- v2.1.0 WebUI 重构：[DarkKandaoMaster（强壮的砍刀）](https://github.com/DarkKandaoMaster)
- MP3 音频单独下载：[ErgouTree（GitHub：@ergou10086）](https://github.com/ergou10086)

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 强大的视频下载引擎
- [FFmpeg](https://ffmpeg.org/) - 音视频处理工具

---

**如果这个工具对您有帮助，欢迎给个Star ⭐**
