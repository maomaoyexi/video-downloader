# FANBOX P3 收尾、P4 与精简 P5

日期：2026-11-01。按用户本次范围调整实施，不修改 README，不恢复插件设置导入入口，不在 UI 添加说明段落。

## 阶段核查与范围

P3 的主页/单帖归档、预览选择、全局与任务设置隔离、日志、按链接历史、恢复和完整发行包已有验收，可以认定核心流程基本完成。本轮补齐结果清单导出、外链复制、命名预览、仅失败文件重试，以及暂停后对额度、同名冲突、图片降级策略的显式调整。重试保留先前成功帖子的归档入口，任务覆盖值不修改全局默认。

下载设置中的筛选、日期、金额、资源类型、关键词、粉丝卡和少量单次行为集中到默认关闭的“单次下载选项”。任务弹窗默认展开这一组，固定偏好放入“其他下载设置”；继续任务只显示允许调整的运行策略。所有设置仍逐项单行排列。

P4 重点为标签、关注/赞助集合、下载记录管理、缓存清理、用量和完整功能对照。既有产品取舍继续生效：插件设置导入不恢复，主题和中文界面跟随主工具，不增加 FANBOX 独立皮肤/背景/语言系统。

P5 仅做手动、只读的本地归档文件校验。不加入外站文件下载、作者定时同步或自动更新复查，也不增加新的后台轮询。

## 源码与依据

- [参考插件固定提交](https://github.com/xuejianxianzun/PixivFanboxDownloader/tree/c978562e8e5d75fe102cc97277fbc3d4d9a40ac2)：复核 API、InitHomePage、InitTagPage、DownloadRecord、Resume、Settings；只据协议事实独立实现。
- [gallery-dl 的 FANBOX 实现](https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/fanbox.py)：交叉核对标签和集合分页行为，不复制 GPL 实现。
- [SQLite JSON 接口](https://www.sqlite.org/json1.html)：大任务明细和轻量摘要投影依据。

测试与功能对照将在各阶段完成后补记；没有以本文件的计划文字代替已实现状态。

## P3 收尾验收

FANBOX、路由及 WebUI 相关 180 项测试通过；DOM/独立无头 Edge 的 3 项集成测试通过，覆盖折叠默认状态、任务覆盖隔离、命名/清单安全投影、失败重试保留归档，以及两种主题和三种窗口宽度。P3 可按上述边界收尾，后续缺口归 P4，不称“插件功能全部覆盖”。

## P4 已实现与范围对照

| 功能 | 结果 |
| --- | --- |
| F01—F02 作者主页、单帖 | 沿用核心归档与 Enter/预览入口 |
| F03 标签 | 两种主页形式、中文/特殊字符编码、数字 userId、nextUrl 校验与恢复 |
| F04 所有赞助 | post.listSupporting 完整游标分页、跨作者去重、全局筛选上限 |
| F05 所有关注 | 关注成员快照、作者逐页抓取、跨作者恢复，不重新抓已完成详情 |
| F06—F08 六种正文、资源、封面和格式 | 延续已有解析/原生传输和质量策略 |
| F09 外链提取 | 保存链接及上下文、复制/导出，不下载外站文件 |
| F10 评论 | 分页/回复状态；JSON、TXT、HTML 输出，转义来源文本 |
| F11 筛选 | 既有全部筛选；明确统计日期、金额、ID、关键词等排除数量 |
| F12 命名 | 图片/附件模板、别名、补零、收藏、路径预览与冲突处理 |
| F13 控制/重试 | 暂停、冻结策略调整后继续、仅失败文件重试，保留成功归档 |
| F14 调度/额度 | 共享持久限制；按接收块计量，不混用任务并发与文件并发 |
| F15 URL 记录 | 预览/导入/导出/清空；只作提示，不作为文件存在或完整的证据 |
| F16 恢复/清缓存 | 版本保护、工作/资源租约；只删已知 part/元数据，保留文件/索引 |
| F17 设置迁移 | 保留兼容 API/CLI 与工具预设；按用户要求不恢复插件设置导入 UI |
| F18 粉丝卡 | 当前/所有赞助、用户名开关、无背景替代、独立 PNG 排版，未复制品牌资产 |
| F19 用量 | 今日/近 30 日接收量及已记录完成体积，图/表与时区 |
| F20 日志/通知/标题 | 专属日志与 SSE、完成通知、活动任务标题状态 |
| F21 外观/语言 | 随主工具明暗/中文/折叠布局；不增加独立皮肤/多语言或说明段落 |
| F22 结果交互 | 分页预览、资源路径、命名预览、复制外链、导出安全清单 |

URL 记录兼容插件的 `[{"url":"..."}]` 格式。导入前预览有效/重复/拒绝计数；文件上限 16 MiB/100000 项，按 UTF-8 大小分批，每批保留现有 64 KiB HTTP 限制。记录移除签名查询；非 FANBOX 资源 URL、非法路径不会导入。清空 URL 记录不会删除文件或成功校验索引。成功传输会记录 URL 路径；升级前没有 URL 元数据的旧索引不会凭空补造记录。

SQLite schema 2→3 先备份，增加 URL 记录、成功体积账本、起始时间与来源索引。完成体积定义为通过验证的资源文件全长；接收量包含失败和重试正文。旧日期缺少完成记录时显示未知，既有接收量照常保留。首次 SSE/列表/来源历史只投影轻量摘要，不把大任务的正文/资源清单反复读入 Python 集合。

真实只读观察：现有会话关注列表 16 位作者、赞助列表为空；关注集合限两帖预览完成，赞助空集合正确结束。对 gallery-dl 公开参考标签页匿名读取 31 篇元信息，不请求第三方付费正文/附件。合成协议覆盖两作者、305 篇、空页、置顶重复、游标循环、错误标签身份、跨页失败恢复；真实非空赞助集合与可用粉丝卡仍无成功样本，不把空集合校验当成非空成功。

P4 相关回归 193 项及前端 3 项集成测试通过；新增记录/用量界面也覆盖明暗主题和 320/768/1440 像素窗口。此处“完成”按本次产品范围判断，保留上表的用户取舍及真实验证限制，不宣称原插件所有界面/语言等价。

### 58 项设置处理记录

| 原键 | 当前对接/处理 |
| --- | --- |
| `autoStartDownload` | `workflow.auto_download` |
| `bgDisplay` | compat.original_ui；preserved_not_applied |
| `bgOpacity` | compat.original_ui；preserved_not_applied |
| `bgPositionY` | compat.original_ui；preserved_not_applied |
| `boldKeywords` | `ui.bold_keywords` |
| `compressed` | `filters.resource_types.archive` |
| `conflictAction` | `naming.conflict` |
| `crawlInterval` | `network.api_interval_seconds` |
| `dateFormat` | `naming.date_format` |
| `deduplication` | `archive.incremental` |
| `downloadInterval` | `network.file_start_interval_seconds` |
| `downloadThread` | `network.file_concurrency` |
| `fee` | `filters.fee.value` |
| `feeRange` | `filters.fee.op` |
| `feeSwitch` | `filters.fee.enabled` |
| `fileNameExclude` | `filters.attachment_name.exclude` |
| `fileNameExcludeSwitch` | `filters.attachment_name.exclude_enabled` |
| `fileNameInclude` | `filters.attachment_name.include` |
| `fileNameIncludeSwitch` | `filters.attachment_name.include_enabled` |
| `free` | `filters.include_free` |
| `idRange` | `filters.post_id.op` |
| `idRangeInput` | `filters.post_id.value` |
| `idRangeSwitch` | `filters.post_id.enabled` |
| `image` | `filters.resource_types.image` |
| `imageSize` | `content.image_quality` |
| `music` | `filters.resource_types.audio` |
| `nameruleForNonImages` | `naming.attachments` |
| `namingRuleList` | `naming.favorites` |
| `other` | `filters.resource_types.other` |
| `pay` | `filters.include_paid` |
| `postDate` | `filters.published.enabled` |
| `postDateEnd` | `filters.published.end` |
| `postDateStart` | `filters.published.start` |
| `ps` | `filters.resource_types.source` |
| `saveComment` | `content.comments` |
| `saveLink` | `content.links` |
| `savePostCover` | `content.cover` |
| `saveText` | `content.body` |
| `showAdvancedSettings` | 随主工具；兼容报告 follows_application |
| `showHowToUse` | 保留但不呈现独立说明；preserved_not_applied |
| `showNotificationAfterDownloadComplete` | `notifications.on_complete` |
| `textFormat` | `content.body_formats` |
| `theme` | 随主工具；兼容报告 follows_application |
| `tipCreateFolder` | 保留但不呈现独立说明；preserved_not_applied |
| `titleCannotText` | `filters.title.exclude` |
| `titleCannotTextSwitch` | `filters.title.exclude_enabled` |
| `titleMustText` | `filters.title.include` |
| `titleMustTextSwitch` | `filters.title.include_enabled` |
| `totalDownloadLimit` | `quota.limit_gib` |
| `totalDownloadLimitByte` | 由额度推导；derived |
| `totalDownloadLimitSwitch` | `quota.enabled` |
| `unifiedURL` | compat.original_ui；preserved_not_applied |
| `userSetLang` | 随主工具；兼容报告 follows_application |
| `userSetName` | `naming.images` |
| `video` | `filters.resource_types.video` |
| `whatIsNewFlag` | compat.original_ui；preserved_not_applied |
| `zeroPadding` | `naming.zero_pad` |
| `zeroPaddingLength` | `naming.pad_width` |

## P5 最小增强：手动资源校验

任务和历史详情增加“校验资源文件”。校验读取已下载图片/附件的大小与 SHA-256，报告缺失、变化、无法读取、使用中及缺少校验数据；不以大小一致代替哈希一致。未知校验数据不会记为通过。每个工作区同时最多一个校验，可停止；同一任务的继续/缓存清理与校验互斥，资源租约保护其他任务正在使用的文件。

结果独立保存在 schema 4 的报告表，升级 schema 3 前保留备份。大文件分块读取，进度经既有 SSE 发布；不会为进度重写整份正文/附件任务快照。报告有独立递增版本，迟到的首次快照不能把完成状态回退成运行中。下载任务版本改变后，旧报告标为需重新校验；进程中断后只记录中断，不自动重新运行。问题路径最多保留 500 条，并标记截断，完整计数继续保留。报告随清单导出。

资源文件和成功索引保持只读，网络额度不增加。正文导出、生成的粉丝卡及缺少可靠哈希的旧文件不宣称得到完整性认证。没有加入外站直链/网盘下载、作者级同步、更新复查或新的周期任务。

收尾同时核对受限帖的封面分支：仅按当前接口公开提供的封面地址保存可见封面，受限正文和附件仍不会下载，整体仍记为部分完成/受限，不假报完整访问。

真实验证：对用户提供作者的公开封面完成落盘、完整图片解码、接收量/完成体积计量，以及本地 SHA-256 校验；保留了受限帖的部分完成状态。现有 cookies.txt 的有界图片样本没有发现可访问原图；项目现有 Chrome Cookie 读取器返回 DownloadError，未获得新会话。当前非空赞助集合、可用粉丝卡和新付费原图下载仍缺少真实成功样本，不将历史验收结果等同于当前会话验证。

## 最终验收

- 全仓 1005 项通过、1 项跳过，另有 51 项子测试通过；跳过项仍为原有可选的长时间直播测试。FANBOX 语句与分支综合覆盖率 91.18%。
- DOM 与独立无头 Edge 共 4 项集成测试通过，覆盖设置隔离、折叠分组、记录导入预览/确认、用量图表、资源校验、迟到快照、明暗主题及 320/768/1440 像素布局。
- 完整主程序用临时隔离 Python 3.12 环境构建成功；8 项原有依赖自检通过，冻结程序实际完成公开标签元信息抓取、公开封面归档和 schema 4 写入，受限状态仍为部分完成。新 listing/records/verification 模块已进入程序，包内脚本、样式及模板字节与最终源码一致。
- 校验测试覆盖真实文件哈希、同尺寸内容变化、缺失、未知元数据、越界路径、使用中资源、取消、版本变化、中断恢复与备份升级；schema 1/2/3 的升级均覆盖旧版本备份检查。
- 已清理验收数据、公开封面/元信息、数据库、覆盖率、浏览器测试工具、npm 缓存、构建环境和 EXE；保留必要运行依赖、维护测试、用户原计划和参考插件。
