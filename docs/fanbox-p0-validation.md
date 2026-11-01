# FANBOX P0 技术验证记录

日期：2026-10-30（Asia/Shanghai）；范围：用户明确授权的只读测试。不修改 README、平台赞助或账号设置。

## 实现边界

本阶段增加独立的 URL、Cookie、错误、请求节流和传输模块；使用协议事实自主编写，不复制/翻译参考项目实现或品牌素材。现有 MIT 许可保持不变。Chrome 扩展不是运行前提，尚未开放下载 UI；P1 接抓取清单，批量资源下载属于 P2。

参考插件版本 5.1.1，提交 `c978562e8e5d75fe102cc97277fbc3d4d9a40ac2`。参考 [API.ts](https://github.com/xuejianxianzun/PixivFanboxDownloader/blob/c978562e8e5d75fe102cc97277fbc3d4d9a40ac2/src/ts/API.ts)、[抓取源码](https://github.com/xuejianxianzun/PixivFanboxDownloader/blob/c978562e8e5d75fe102cc97277fbc3d4d9a40ac2/src/ts/InitPageBase.ts)、[gallery-dl FANBOX 源码](https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/fanbox.py)。

## 真实数据结论

同一授权 Cookie，HTTPX 的 creator.get、分页与列表返回 200；post.info 返回 Cloudflare HTML 403。固定 curl_cffi 0.13.0 的浏览器兼容传输成功获取详情。未使用验证码求解、第三方代理服务、账号轮换或关闭证书校验。[gallery-dl 的类似案例](https://github.com/mikf/gallery-dl/issues/7490)、[curl_cffi 官方文档](https://curl-cffi.readthedocs.io/en/latest/)。

| 作者 | 已观测结果 |
| --- | --- |
| mimoriaino | 24 个分页地址；首列表页 10 条；公开 article 详情可访问，五种 block/map 字段存在 |
| shirohanemu | 19 个分页地址；首列表页 8 条可访问、2 条受限；付费 image 正文可访问；更高权限 file 详情 body=null |
| kanibiimu | 53 个分页地址；付费 article 正文可访问，含 2 张原图 |

这是小样本观测，不是全量作者归档。creator.get 的 isSupported 对部分作者返回 false，但实际付费正文仍可访问，因此**不能根据该标记推断当前月份的阅读权**，也不能据此判定用户是否已付款。实际以详情响应及 isRestricted 判断。

原图探测只在内存消费前 4096 字节：shirohanemu 返回 206、Content-Range 含 4,450,073 字节总长、JPEG 文件头；kanibiimu 返回 200 并忽略 Range，也读到 JPEG 文件头。后续续传必须检查 200/206，不可盲目追加。没有保存这些图片。

三个作者的评论接口均返回 body.viewMode 与 body.commentList。正文和评论可用性分别判断。未在此次小样本中取得可访问的原生 file 附件，因此不宣称已完成附件下载实测；受限 file 不视为可下载。

后续 [P1 验收](fanbox-p1-integration.md)扩展样本后，已取得可访问的 MP3/WAV 附件并完成内存前缀验证；完整附件落盘与完整性验收仍属于 P2。

### 与旧样本的重要差异

当前 post.listCreator 的 body.posts 中是**摘要**：包含 id、creatorId、费用、日期、标签、isRestricted、cover 和统计；没有 type/body。body 缺失不等于 body=null。必须抓取详情确定帖子类型，不可仿照 Python `get('body') is None` 跳过全部摘要。

post.info 的新包装是 body.post；保留有依据的旧 body 帖子兼容。缺少结构必须报 schema_changed，不能伪装成空作者。

## 运行与发行

源码安装命令：`python -m video_downloader.platforms.fanbox.runtime --install`。依赖安装到 dependency/fanbox-python，官方 PyPI 版本和 wheel SHA-256 固定在 resource/dependencies/fanbox-runtime.txt；不修改全局 Python。

运行环境 Python 3.12.7 / Windows x64。HTTPX 为诊断与可替换后端；主路径用 curl_cffi。所有请求禁用隐式环境代理，显式代理和 Cookie 域/path/过期策略单独控制。[HTTPX 代理环境变量](https://www.python-httpx.org/environment_variables/)、[Python CookieJar](https://docs.python.org/3/library/http.cookiejar.html)。

PyInstaller spec 增加 curl_cffi 数据/二进制、_cffi_backend、证书与许可证收集；完整主程序 EXE 构建尚未作为本阶段验收完成，不能由源码运行成功推断发布包已验证。

Chrome 原生自动核验被工具停止，原因是无法可靠识别当前浏览器 URL；后续没有继续发送浏览器输入。所有有效验证结论来自受控 HTTP 传输，不依赖浏览器自动化结果。

## 验证与后续约束

P0 单元测试覆盖 URL 边界、Cookie 域/过期、异常脱敏、响应大小、资源前缀、HTTP 错误和可取消节流；网络请求与解析通过依赖注入替换。测试临时目录放项目 temp，结束后清理；真实 Cookie、正文、分享口令不进入测试夹具和提交。

P0 结论：直接 HTTP 路线可行，但**必须具备合适的传输适配器**。P1 按实时摘要结构实现；公开/受限/未知明确区分。原生附件、完整 EXE、所有历史类型和所有评论页仍需在对应阶段继续验收。
