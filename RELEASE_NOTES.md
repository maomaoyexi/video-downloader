# v2.8.3 WebUI

发布日期：2026-11-25 · [下载本版](https://github.com/maomaoyexi/video-downloader/releases/tag/v2.8.3) · [使用说明](https://github.com/maomaoyexi/video-downloader/blob/v2.8.3/README.md)

本次修复单条 YouTube 直播回放链接被当成直播录制的问题，并补充直播预检和网络代理设置的提示。

## 新增功能

本版以问题修复和文档维护为主，沿用现有支持平台和功能。

## 问题修复

- **YouTube 直播回放**。WebUI 确认单条 `/live/` 链接已有可用回放时，按普通视频下载。保留原视频 ID 的大小写及本次 yt-dlp 参数。
- **YouTube 直播预检**。遇到格式错误会补查直播状态。确认直播尚未开播时可继续蹲开播。直播缺少可录制格式或回放未就绪时，会显示对应的中文提示。

## 界面与交互

- 「下载设置 → 网络与代理」补充代理类型、地址和端口的填写说明。实际值以代理客户端为准，`7890` 是默认值。使用 Windows 手动代理时可在系统设置中查看当前地址和端口。

## 依赖说明

- 沿用 v2.8.2 的下载核心和锁定运行库。本版依赖清单与 v2.8.3 完整依赖包配套。
- 同步使用教程、常见问题、错误手册与专项指南中的版本、回放用法和排查说明。

## 下载与升级

Windows 绿色版由以下两份文件配套交付，无需安装 Python。

| 文件 | 用途 |
| --- | --- |
| `video-downloader-v2.8.3-GUI.exe` | 主程序 |
| `video-downloader-v2.8.3-dependencies.zip` | 下载工具、插件及运行依赖 |

1. 先完成或取消现有任务，通过左侧底部「退出工具」关闭旧程序。
2. 替换 EXE，并完整解压同版本依赖包，使 `dependency/` 与 EXE 位于同一目录。
3. 保留 `settings.ini`、`presets.json`、`cookies.txt`、密码表和 `download/`，升级前备份重要数据。
4. 启动 v2.8.3 后，可在「关于软件 → 依赖状态 → 更新依赖」检查配套依赖。
5. 升级源码时，同步 `视频下载工具v2.8.3-GUI.py`、`video_downloader/`、`resource/` 与配套依赖，并重启后端。

完整安装步骤见 [README](README.md#下载安装)。上版附件及校验值可查阅 [v2.8.2 发布说明](https://github.com/maomaoyexi/video-downloader/blob/v2.8.2/RELEASE_NOTES.md)。

### SHA-256

```text
985c1fac1c0ca55751134fbccd6f4b0e37b76ddcd1548859b0570a687cd29287  video-downloader-v2.8.3-GUI.exe
3a9ea65feef4e6634c880465a3052962f4c05fd11599c35b420cbf4538e7300a  video-downloader-v2.8.3-dependencies.zip
```

## 已知限制

- 回放分流适用于 WebUI 单条 YouTube 直播链接。普通观看链接可直接按点播下载。
- YouTube 仍由平台决定回放处理进度、访问权限和可用格式。若浏览器可播放回放，也可使用同一视频的普通观看链接重试。
- 普通任务队列只在本次运行中保留。FANBOX 和 Withny 等平台功能的具体适用范围见使用教程。

## 使用注意

- 通过「退出工具」关闭应用。依赖正在安装或回滚时，请按界面提示等待完成。
- HAR、Cookie、凭据配置、密码表及原始评论可能包含隐私，反馈前请脱敏。
- 使用帮助提供常见报错速查，其他报错可查 [完整手册](docs/错误码.txt)。

## 本次贡献者

| 贡献者 | 本版贡献 |
| --- | --- |
| [maomaoyexi（@maomaoyexi）](https://github.com/maomaoyexi) | YouTube 回放和预检修复、代理提示、回归测试、文档及版本维护 |

历史作者与上游贡献见 [CREDITS.txt](CREDITS.txt) 和 [版本更新记录](CHANGELOG.md)。
