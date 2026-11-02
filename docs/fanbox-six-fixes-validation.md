# FANBOX 六项问题修复与验证

验证日期：2026-11-02。本文对应当前源码检出，未重新打包或替换已发布的 v2.7.0 附件。

## 范围与方法

- 以用户提供的六项审查记录为范围，先在当前源码建立失败用例，再修复并保留回归测试。
- 使用临时目录、合成 Cookie、模拟时钟和离线传输；真实任务队列、控制器、下载器、SQLite 归档及文件校验仍走实际实现。
- 长间隔测试推进模拟时钟验证 180 秒等待，不实际等待数分钟；浏览器测试使用本机合成接口和独立 Edge 配置。
- FANBOX 之后切换其他平台的停止路由作为既有功能回归，不计入六项新问题。

## 逐项结果

| 问题 | 复现与根因 | 修复与验证 |
| --- | --- | --- |
| 1. 暂停或启动失败后无法继续 | 6 个控制器用例修前全部失败：排队取消后仍为 `queued`，活动映射未清理，启动异常也未持久化暂停状态。 | 对照任务队列的权威活动状态与 job lease 恢复记录；排队暂停立即落库，执行器结束回调清理活动映射。另用真实 container/TaskManager/FanboxExecutor 验证两种任务模式、直接取消、失败后修配置续跑与有效租约互斥。 |
| 2. 旧模式混合批次确认路由错误 | 初始 7 个用例中 5 个失败：两个 URL 顺序均接受混合，任务入口接受混合，确认消息落到外层视频执行器，FANBOX 活动时仍接受旧视频确认。 | FANBOX 与其他平台在同一批次/父任务的输入于启动前拒绝，分别创建的任务可并行；确认交给当前子执行器或活动执行器，陈旧确认被拒绝。保留跨平台停止路由回归。 |
| 3. 缩略图内容与扩展名不符 | PNG/GIF 原图切换到 JPEG 缩略图 URL 后，资源仍保留原扩展名，真实 Downloader 报 `invalid_payload`。旧失败任务还可能冻结了错误路径。 | 按实际缩略图 URL 归一化资源类型，覆盖新扫描和旧快照恢复；仅在不能复用旧成功文件时修正冻结路径的扩展名，保留文件名主体、已有文件与冲突策略。错误内容仍须通过图片头校验。 |
| 4. 预览后漏掉受限帖公开封面 | `action(download)` 强制 `accessible_only=True`，同时帖子选择与页面控件将受限帖全部禁用，公开封面未进入实际下载。 | 移除隐式全帖过滤，允许选取含可下载公开封面的受限帖子与封面资源；列表计数和详情保持一致。正文附件仍受权限限制，用户显式指定 `accessible_only=True` 的语义保留。 |
| 5. 长间隔导致租约过期和残留 running | 4 个用例修前全部失败：API/文件启动间隔 180 秒时未续租，异常收尾又要求已失效租约，数据库状态未完成更新。另复现旧 worker 在被新 worker 接管后仍覆盖归档状态。 | 等待期间每 20 秒续租 job、API、file、asset 的活动租约，释放时移除续租登记；正常保存与所有权检查在同一事务内进行，失效后的暂停收尾采用版本与新 owner 校验，不覆盖接管者。覆盖等待取消、恢复及异常失效。 |
| 6. 扫描命令忽略保存的匿名和 Cookie 设置 | 初始凭据矩阵 5 失败、18 通过：扫描遗漏专项设置；归档命令已读取保存设置，但显式 `--cookies` 被保存的匿名开关压制。WebUI 原有三条设置链正常。 | 扫描与归档 CLI 共用凭据选择：显式参数优先于保存设置，其后才为默认 `cookies.txt`；相对路径按工具目录解析，显式匿名与 Cookie 仍互斥。新增 27 个配置、鉴权、路径和输出保护用例，WebUI 逻辑保持原样。 |

## 定向复跑

在本源码检出目录执行，先准备测试依赖，再使用对应 Python 运行：

```powershell
python -m pytest tests/platforms/fanbox/test_recovery_regressions.py tests/platforms/fanbox/test_task_recovery_integration.py -q
python -m pytest tests/services/test_fanbox_batch_boundaries.py tests/services/test_routed_batch.py tests/services/test_routed_executor_lifecycle.py tests/services/test_archive_choice.py tests/tasks/test_tasks.py -q
python -m pytest tests/platforms/fanbox/test_cover_regressions.py -q
python -m pytest tests/platforms/fanbox/test_lease_regressions.py tests/platforms/fanbox/test_lease_ownership_review.py -q
python -m pytest tests/platforms/fanbox/test_cli_credentials.py -q
```

## 回归范围

Python 回归覆盖 FANBOX 扫描、预览、鉴权、文件复用、图片降级、断点续传、流量计量、内容校验、任务并行、取消、重下载确认，以及 Rplay、普通视频、Withny 和直播的既有测试。

Web 回归覆盖 FANBOX 受限帖封面的可选择性、正文资源禁用、设置隔离、整页初始化、任务日志与浅/深主题下的响应式布局。

初轮全量运行暴露测试环境缺依赖、Windows DPAPI 沙箱限制、默认 GBK 解码及临时目录差异。E 盘文件系统不记录 Git 所需的归属信息，也不支持相应符号链接测试；最终测试改用正常 Windows 用户环境、UTF-8 和 C 盘 NTFS 下的独立临时目录。

Python 测试依赖放在根工作区 `.build-tools/test-python`，生产依赖清单及锁文件未修改。为覆盖真实媒体回归，仅向当前检出的缺失位置复用根工作区已有的 `ffmpeg.exe`、`ffprobe.exe`、`yt-dlp.exe`；源文件与目标文件 SHA-256 一致，原文件未改。测试环境为 Python 3.12.14、pytest 9.2.0、Node.js 24.16.0。

最终全量按互不重叠的三组运行：`tests/live`、`tests/platforms`，以及 `tests --ignore=tests/live --ignore=tests/platforms`，完整覆盖 1135 个收集项。

| 分组 | 通过 | 跳过 | 失败/错误 | 额外子测试通过 | 耗时 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `tests/live` | 229 | 1 | 0 | 18 | 58.37 秒 |
| `tests/platforms` | 474 | 0 | 0 | 7 | 60.62 秒 |
| 其余测试 | 431 | 0 | 0 | 26 | 106.86 秒 |
| 合计 | 1134 | 1 | 0 | 51 | 三组并行执行 |

唯一跳过为 `tests/live/test_live_network_recovery.py` 中需要显式设置 `LIVE_EXTENDED_TESTS=1` 的 145 秒断网可选验收，本次未运行该项。子测试另行计数，不重复加入 1135 个收集项。

最终 Web 回归为 5 项通过、0 失败、0 跳过，耗时 12.410 秒：包含 4 个 DOM 用例和 1 个真实 headless Edge 页面验收。跨 FANBOX 切换其他平台后的停止、启动失败时保留活动执行器、批量确认归属及独立任务并行回归均通过。`git diff --check` 通过。

完整日志保存在根工作区 `.build-tools/`：`pytest-v270-six-fixes-final.log` 明确标记为三个分组的汇总，并保留各组完整输出；Web 日志为 `node-web-six-fixes-final.log`。依赖来源与哈希记录见同目录 `reused-media-dependencies.json`。环境失败日志单独保留，不计入最终通过结果。

## 验证边界

本次不使用真实账号访问线上付费内容，也不声明平台实时接口或已发布 EXE 已完成在线实测。平台访问权限、服务端限流和账号会话有效性仍由平台决定。
