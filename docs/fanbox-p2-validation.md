# FANBOX P2：可靠落盘与执行器验收

日期：2026-10-31（Asia/Shanghai）。承接 [P1](fanbox-p1-integration.md)，在当前 main 开发；未修改 README 和生产 UI。P3 继续接入预览、交互与发行包。

## 已交付

- 独立的 archive / binary / downloader / exporters / naming / repository / scheduling / executor 模块，视频执行器通过路由门面接入，解析器继续保持无 IO。
- 强 ETag 条件续传，检查 Content-Range、响应长度及最终文件大小；200 全量响应安全重建，416 仅在总长和强 ETag 一致时完成。无可靠验证器时重新下载，不盲目拼接。
- 原子落盘、SHA-256 成功索引、磁盘缺失及内容变更修复、资源修订独立分配路径。失败/受限/降级不记入原图成功索引。
- URL 失效后重新获取详情；缩略图仅按明确策略降级，并保持独立 variant。冲突支持添加序号、覆盖、询问及跳过；不覆盖其他已登记资源。
- Windows 保留名、路径穿越、超长名称、大小写冲突和重解析点保护；冻结命名路径，HTML 引用实际落盘路径。
- TXT/HTML/Markdown/JSON、评论和外链导出；HTML 转义正文，保留 UTF-16 超链接/加粗跨度，不执行来源 HTML、不自动加载远程媒体。
- SQLite schema 1、事务、WAL/FULL 同步；工作、资源和调度租约持久化，崩溃租约过期后可恢复。成功索引仅在文件校验和原子提升后写入。
- 同归档工作区保守共享 API/文件调度、文件并发及 429 冷却；Cookie 更换不重置额度。当前只有一个凭据槽，不猜测账号身份。
- 日额度事务预留、按接收块计量、当前时区跨午夜核算、取消释放预留、过期租约回收。实际接收的失败重试正文也计量；不含 HTTP/TLS 开销。未知长度先保守预留可用额度，收到长度后调整，可能降低未知文件间的并发。
- TaskManager 新增内容统计及归档结果，不将一个作者等同多个视频；partial/paused 能释放队列槽。旧 TwitCasting 密码状态赋值兼容已回归。

## 使用

```powershell
python -m video_downloader.platforms.fanbox.download_cli https://www.fanbox.cc/@creator --cookies "C:/path/to/cookies.txt" --max-posts 2 --directory "download/Fanbox"
python -m video_downloader.platforms.fanbox.download_cli --resume JOB_ID --cookies "C:/path/to/cookies.txt" --directory "download/Fanbox"
```

现有总 CLI 支持 `--fanbox-download`；直接输入 FANBOX URL 和 CLI 混合批量也在视频依赖检查前路由。`--preview` 只抓取，不请求附件。恢复使用该工作区内已冻结的任务快照。

## 真实样本与边界

用户提供的三个作者合计选取 5 帖，全部完成所选范围，归档 7 个文件，共 59,451,082 字节；均复跑确认复用。只取各作者首列表页，不是全作者归档。

- kanibiimu：2 帖、4 文件；shirohanemu：1 帖、1 文件；mimoriaino：2 帖、2 文件。
- 3 张正文原图用 Pillow 完整解析，并与 API 宽高一致；MP3 完整落盘 46,532,160 字节，ffprobe 确认格式及非零时长。Pillow/ffprobe 仅用于验收，不是此平台归档运行依赖。
- MP3 首次因旧请求总时限中断，留下约 25 MB 部分文件。改为连接及空闲超时后，恢复任务成功；本次恢复接收的是完整文件，不宣称它证明了真实 CDN 的 206 续传。200/206/416、ETag 变化、错误范围与零字节附件均由真实本机 HTTP 服务覆盖。
- 不以作者 isSupported 推断权限；未复制付费正文到离线夹具。当前原生 file/WAV 的完整落盘未实测，P1 的 WAV 前缀验证仍有效。

## 自动验证

最终全仓 **962 项通过、1 项跳过、另有 51 项子测试通过**。唯一跳过项为原直播默认关闭的 145 秒中断验收。实际 Windows Junction 检查通过。FANBOX 模块语句与分支综合覆盖率 **91.99%**，包括原生下载 CLI、下载器、SQLite 及执行器；不把真实联网结果混入覆盖率夹具。

发现并修复：curl_cffi 0.13.0 会把普通短写返回值转换为全部接收，必须返回 CURL_WRITEFUNC_ERROR；常规 stream 使用无界队列，不适合大文件背压；非 stream 的 tuple timeout 是总请求时限，不能作为大附件读超时。另修复了路由门面的旧对象状态写入委托。没有修改旧测试断言规避兼容问题。

已清理本阶段的真实正文/附件/检查点和无用测试目录、覆盖率文件；验收工具因 P3 仍需使用暂留 temp，P3 结束后删除。隔离运行依赖保留，不提交 Git。正式 UI、任务模式关闭时的混合批量协调、次日自动恢复调度和完整主程序冻结验收在 P3 收尾，不能由本阶段结果推断完成。

## 核对来源

- [参考插件固定提交](https://github.com/xuejianxianzun/PixivFanboxDownloader/tree/c978562e8e5d75fe102cc97277fbc3d4d9a40ac2)：本日复核仍为上游最新提交；核对 FileName、SaveData、download/Download、DownloadRecord、TotalDownload、CrawlResult。
- [gallery-dl FANBOX](https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/fanbox.py)：交叉核对媒体、封面、嵌入和评论处理。实现独立编写，没有复制 GPL 代码。
- [RFC 9110 条件范围请求](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.5)、[206](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.3.7)、[416](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.17)。
- [libcurl 写回调](https://curl.se/libcurl/c/CURLOPT_WRITEFUNCTION.html)、[文件大小上限](https://curl.se/libcurl/c/CURLOPT_MAXFILESIZE_LARGE.html)；固定 wheel 的 curl.py、requests/session.py、requests/utils.py 已实际审阅并以本机 HTTP 测试验证。
- [SQLite 事务](https://www.sqlite.org/lang_transaction.html)、[原子提交](https://www.sqlite.org/atomiccommit.html)：写入顺序、回滚和并发预留依据。
