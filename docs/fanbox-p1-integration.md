# FANBOX P1 抓取集成与验收

日期：2026-10-30（Asia/Shanghai）。前置验证见 [P0 记录](fanbox-p0-validation.md)。本阶段提供可运行的帖子抓取清单；不进行批量附件下载，不新增 UI 说明，也不修改 README。

## 当前可以做什么

- 输入作者子域主页、`www.fanbox.cc/@creator`、帖子列表或单帖地址，规范化到稳定来源。
- 完整分页枚举，去重置顶帖，允许中间空页；分页中断后保留检查点并继续。
- 解析 article/image/file/text/video/entry 六种帖子，保留 blocks 顺序、资源引用、文本样式和超链接跨度；未知类型/缺失资源明确标记。
- 原图与缩略图地址独立，正文与直接附件分别筛选；video 嵌入仅提取外链。
- 保存同一行多个 URL、MEGA fragment、HTML 属性链接、嵌入链接、引用帖和评论链接，保留出处与上下文。
- 免费/付费、金额、严格 ID、日期、标题及原附件名筛选；支持最大帖子数的有界抓取。
- 可选评论分页、去重、回复保留、页数上限和不完整状态；评论失败不冒充完整成功，恢复时可重新抓取不完整评论。
- 原子写入 JSON 清单和检查点，恢复前校验来源、配置摘要、登录快照；不记录 Cookie 值。

摘要缺少 type/body 时仍抓详情；仅详情明确 body=null/isRestricted 时标记正文受限。creator.get 的 isSupported 不用于推断阅读权限。

## 使用入口

先安装项目隔离运行依赖（已固定官方 wheel 版本及 SHA-256）：

```powershell
python -m video_downloader.platforms.fanbox.runtime --install
```

安装命令应使用运行工具的同一个 Python。已验证系统 Python 3.12.7 和项目 dependency/.venv 的 Python 3.13.2；两者需要对应 ABI 的 CFFI wheel，不能将一个解释器的安装成功直接视作另一个可用。安装器从同一哈希锁选择匹配 wheel。

抓取小范围清单，默认使用项目配置和原图地址：

```powershell
python -m video_downloader.platforms.fanbox https://www.fanbox.cc/@creator --cookies "C:/path/to/cookies.txt" --max-posts 3 --comments --output "download/Fanbox/creator-scan.json"
```

也可通过现有 CLI 分发：`run_cli(["--fanbox-scan", URL, "--output", PATH, ...])`。模块入口可独立运行，不依赖 yt-dlp、ffmpeg 或 WebUI 启动。

- `--anonymous`：明确匿名；与显式 `--cookies` 互斥。
- `--options PATH`：读取版本化 FANBOX JSON 设置。
- `--import-plugin-settings PATH`：迁移插件导出的 JSON；清单附带逐键迁移报告。
- `--checkpoint PATH`：指定检查点；默认在输出文件名后追加 `.checkpoint.json`。
- `--resume`：继续同一来源/配置/登录快照，复用已经解析完整的帖子。
- `--max-posts N`：最多解析 N 篇通过帖子筛选的帖子，不宣称已经扫描作者全站。

不指定最大数时按返回的所有分页地址枚举；默认请求间隔 1 秒。返回码：完整完成或完成用户指定范围为 0，不完整/失败为 2，中断为 130。清单的 `coverage.list_complete` 和 `coverage.limit_reached` 分别表示列表完整性与用户上限，必须一起读取；`completed` 不等于“作者全站已抓完”。

文件可能包含可访问的正文、评论和分享口令，应作为本地归档保存。stdout 只输出计数、范围和脱敏错误，不输出帖子全文、分享密钥或认证信息。

## 设置对接

全局 `DEFAULT_CONFIG` 新增 `FANBOX_OPTIONS`，由专用 schema 校验，不受旧 200 字符通用字符串限制影响。全默认配置保留为 `{}`，避免改变旧配置回退判断；非默认设置规范化成完整版本化 JSON。现有 INI 保存、预设保存/加载、局部设置更新均保留该字段，已有 UI 不需要增加说明才能维持配置。

对提供的上游 Settings.ts 默认值实际提取并比对：**58/58 键覆盖，其中 52 项映射、5 项保留为未应用的界面兼容元信息、1 项字节额度作为派生值处理。** 不将保留配置误称为当前 P1 已执行的下载行为。

| 当前 P1 生效 | 为后续阶段保留，但 P1 不执行 |
| --- | --- |
| 帖子与资源筛选、图片质量地址选择、正文/链接/评论清单、评论页数、API 间隔、代理、传输引擎、原始快照 | 文件并发/启动间隔、文件命名与冲突处理、真正的磁盘增量下载、日下载额度、自动附件下载、浏览器通知、界面主题与外观 |

导入插件 `saveText=false` 时额外关闭新增的原始快照，避免通过 source 字段反而保存用户选择不保存的正文。直接配置的 body 和 raw_snapshot 是两个独立开关。导入报告列明未应用项，不静默假称生效。

FANBOX 下载平台尚未加入现有下载页选择器，也没有改变普通视频 URL 的执行器；该接入点按计划在 P2/P3 实现，避免提前出现不能下载的按钮。

## 模块与扩展接口

网络只通过 `JsonTransport` 协议进入 `FanboxClient`；`ScanService` 不接触 Cookie、HTTPX 或 curl_cffi 的具体对象。模型、筛选、外链与帖子解析无网络/磁盘副作用。`write_json` 只负责原子持久化，检查点保存通过回调注入。

`CurlTransport` 是实测默认，`HttpTransport` 为可替换诊断后端。请求固定到允许的 API endpoint；分页与详情同时校验作者/帖子身份，拒绝任意主机及重定向。单路节流实例可注入共享；P2 将在应用组合根绑定同账号的共享调度和持久冷却，当前 CLI 不宣称已具备跨进程账号限流。

审阅安装的 curl_cffi 0.13.0 `requests/session.py`、`utils.py`、`cookies.py` 后，发现其 trust_env 字段并未控制全部 libcurl 环境代理行为。本实现显式设置空代理/NO_PROXY 和 CA 路径，而非仅依赖 trust_env。实际测试向测试进程注入失效 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/CA 路径，两个后端仍能访问公开 API。未修改系统代理或降低 TLS 验证。

项目 Python 3.13 的真实 CLI 验证还发现 Windows 缺少 IANA 数据库，导致默认 quota.timezone 校验失败。按 [Python 官方建议](https://docs.python.org/3/library/zoneinfo.html)加入 [tzdata 2026.6](https://pypi.org/project/tzdata/2026.6/) 的官方 wheel 哈希和许可证；系统数据库缺失时加载隔离依赖后重试，未知时区仍拒绝。冻结配置收集时区数据及子包，已用合成故障和实际 CLI 验证修复。

## 已完成验证

| 验证 | 结果 |
| --- | --- |
| 新 FANBOX 离线测试 | 93 项通过，包含 305 帖分页、空页、置顶去重、失败恢复、六种类型、恶意 URL、设置往返、无系统时区数据和 CLI；Python 3.13 专项亦通过 |
| 全仓回归 | 913 项通过，1 项跳过，另有 51 项子测试通过；包含现有配置、存储、队列、直播、Rplay、HTTP 和 CLI |
| FANBOX 覆盖率 | 语句 95.94%、分支 89.24%、综合 94.05%；没有把临时真实内容计入离线夹具 |
| 三作者真实抓取 | 每人 3 帖，均完成所选范围；列表每人只取首 10 条，不是全量抓取 |
| 原图地址核验 | kanibiimu 4 个、shirohanemu 3 个，均与真实响应 originalUrl 完全一致 |
| 外链 | 该样本分别提取 3 个和 1 个；其余多链接/口令场景用合成数据覆盖 |
| 评论 | 三组清单中所取评论均完成分页，无不完整标记 |
| 匿名对照 | 公开帖可见；同一付费帖匿名正文受限，登录正文可见 |
| 原生附件前缀 | mimoriaino 的 MP3、shirohanemu 的 WAV 各读取 4096 字节；均返回 206、正确音频类型、文件头和总长；未保存完整附件 |
| 恢复与多解释器 | 完整检查点恢复成功；Python 3.13 另做授权单帖及评论抓取，完成所选范围 |
| 冻结运行 | 最小 PyInstaller 程序加载 curl_cffi 原生库、证书及 IANA 时区数据，并成功请求公开 FANBOX API |

覆盖率依据 coverage.py 的 statement+branch 报告，包含 runtime/CLI，不以源文件数量或断言数代替。完整应用 EXE、完整原生附件下载、UI 浏览器操作、六种格式全部来自真实作者等均**未**在本阶段完成；legacy entry 等使用与参考协议匹配的合成数据。

全仓回归使用 Windows 当前用户身份，复用项目已有的 yt-dlp 测试依赖；受限执行身份出现的旧模块加载/DPAPI 失败没有计入通过结果。最终在实际身份下重新全仓通过。唯一跳过项是现有直播模块默认关闭的 145 秒长中断验收（LIVE_EXTENDED_TESTS），与本次 FANBOX 路径无关。

测试期间发现并修正了全默认 JSON 的旧配置回退兼容问题、冻结测试的相对依赖路径问题、curl_cffi 环境代理继承细节及 Windows 时区依赖缺失。没有通过删除旧断言或降低阈值掩盖失败。

## 来源与剩余工作

- [参考插件 5.1.1](https://github.com/xuejianxianzun/PixivFanboxDownloader/tree/c978562e8e5d75fe102cc97277fbc3d4d9a40ac2)：API、Settings、SaveData、CrawlResult、InitPageBase 的协议和行为核对。
- [gallery-dl FANBOX 实现](https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/fanbox.py)、[403 实践记录](https://github.com/mikf/gallery-dl/issues/7490)：独立交叉验证，未复制其 GPL 代码。
- [FANBOX 官方内容类型](https://fanbox.pixiv.help/hc/en-us/articles/360011655774-How-do-I-insert-images-or-files-into-the-post)：混合正文、附件和嵌入区分。
- [curl_cffi 官方文档](https://curl-cffi.readthedocs.io/en/latest/)、固定 wheel 内源码：传输、代理、Cookie 与冻结路径核对。
- [Python CookieJar](https://docs.python.org/3/library/http.cookiejar.html)、[HTTPX 环境变量](https://www.python-httpx.org/environment_variables/)：认证隔离和显式网络设置。

P2 接文件下载/Range/完整性、资源数据库、配额与任务执行器；P3 接正式 WebUI、SSE 和交互。当前清单和 DTO 可直接作为后续输入，不需让 UI 或执行器重写解析逻辑。

本阶段只保留可维护代码、合成测试、依赖锁与验收文档。真实正文/检查点、覆盖率数据库、临时安装工具、冻结样例和一次性脚本在验收后删除；必需的 dependency/fanbox-python 作为隔离运行依赖保留，不提交到 Git。
