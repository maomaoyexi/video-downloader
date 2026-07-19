# GitHub Release v2.0.0 发布清单

## 基本信息

- 仓库：https://github.com/maomaoyexi/video-downloader
- Tag：`v2.0.0`
- Release 标题：`v2.0.0 WebUI - Bilibili 支持与模块化重构`
- Target：包含本次 v2.0.0 源码的默认分支
- 发布类型：正式 Release
- Draft：不勾选
- Pre-release：不勾选
- Set as latest release：勾选

## Release 正文

将 `RELEASE_NOTES.md` 中除第一行标题外的内容复制到 GitHub Release 正文。

必须保留以下主程序校验行，自动更新器会从 Release 正文读取：

```text
b40087a8da19e59294732b39ecb8d3e5aedffd11b1f3f4aa59768fd59f33948f  视频下载工具v2.0.0-GUI.exe
a749df83aff8cfaca00f274ffb08d9f9e455500bf52b80aed683567359df1fad  视频下载工具v2.0.0-依赖包.zip
```

文件名不要加反引号，不要改空格、连字符或版本号。

## 上传附件

只上传以下两个文件：

- `release-output/视频下载工具v2.0.0-GUI.exe`
- `release-output/视频下载工具v2.0.0-依赖包.zip`

不要上传：

- `smoke.stdout.log`
- `smoke.stderr.log`
- `build/`
- `dist/`
- 用户配置、Cookie、日志或下载历史

`SHA256SUMS.txt` 可选上传，但自动更新器不会读取该附件，因此 Release 正文中的主程序校验行不能省略。

## 发布前检查

- Tag 必须精确为 `v2.0.0`，不能使用大写 `V` 或额外前缀
- 主程序附件名必须精确为 `视频下载工具v2.0.0-GUI.exe`
- 同一个 Release 不要上传其他名称含 `GUI` 的 EXE
- 确认贡献者 `ErgouTree (@ergou10086)` 在 Release 正文中可见
- 确认依赖 ZIP 包含 `CREDITS.txt`、`changelog.html`、`docs/` 和五个依赖 EXE
- 确认 GitHub 页面显示两个附件上传完成后再点击发布

## 发布后检查

- 打开 `https://api.github.com/repos/maomaoyexi/video-downloader/releases/latest`
- 确认 `tag_name` 为 `v2.0.0`
- 确认 `draft` 和 `prerelease` 均为 `false`
- 确认 assets 中存在精确命名的 GUI EXE 和依赖 ZIP
- 下载 GitHub 上的两个附件并重新计算 SHA-256
- 使用旧版程序检查更新，确认能够识别 v2.0.0
- 点击自动更新，确认下载、SHA-256 校验、替换和重启成功
