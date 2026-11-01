# 本地数据 Git 防护

## 保护范围

项目根目录的以下路径只保留在本地，文件名按大小写不敏感匹配：

- `cookies.txt`、`settings.ini`、`urls.txt`
- `download/`、`.ai/`、`.claude/`、`temp/` 及其全部内容

规则针对根目录；例如 `docs/cookies.txt` 不属于这组钩子禁入路径。原有
`dependency`、`scripts` 和测试目录布局校验继续保留。

## 生效方式

当前工作副本已配置 `core.hooksPath=.githooks`。新克隆或其他工作副本需要执行：

```shell
git config --local core.hooksPath .githooks
python scripts/check_repository_layout.py --staged
```

钩子使用项目 Python 环境或系统 Python，缺少解释器时中止操作。
两个钩子以 LF 换行及可执行模式入库，支持路径包含空格的 Windows 工作区。

| 层次 | 检查内容 |
| --- | --- |
| `.gitignore` | 默认忽略本地路径，阻止普通 `git add` 加入 |
| `pre-commit` | 检查整个暂存区；强制添加或此前已跟踪但本次未修改的本地文件也拒绝提交 |
| `pre-push` | 检查全部待推送提交的根目录树及目标提交树；后续删除文件不能掩盖前面的误提交 |

推送检查同时覆盖合并父提交、多个引用、附注标签和强推。新引用通过目的远程的
实时引用确认已有历史，避免错误信任过时的本地远程跟踪引用；推向全新远程时
重新检查完整历史。无法读取远程或对象、校验超时、浅克隆、无效输入和非提交标签均拒绝推送。
校验禁用本地替换对象和 graft 对遍历的影响，不读取或打印受保护文件的内容。

仅取消当前暂存区跟踪时，使用 `git rm --cached -- <路径>`，目录增加 `-r`；
本地文件保留。若文件已进入尚未推送的提交，必须清理那些提交本身，再重试推送。

这些语义参考 Git 官方的 [githooks](https://git-scm.com/docs/githooks)、
[gitignore](https://git-scm.com/docs/gitignore) 与
[rev-list](https://git-scm.com/docs/git-rev-list) 文档。

## 已有历史与边界

2026-11-01 检查当前索引：上述全部路径均未被跟踪。检查本地已获取的
`origin` 历史：`temp/plan` 下 5 份旧计划文档曾进入提交，其余指定路径没有记录。
这些旧计划文档已在后续提交中取消跟踪；本次不改写既有远程历史。
因此向现有 `origin` 推送安全的新提交可以通过，向空远程复制这段旧历史会被拦截。

本地钩子依赖工作副本配置，不能约束显式禁用钩子、删除校验程序、其他未安装钩子的
工作副本或直接通过 API 上传。Git 的
[`push --no-verify`](https://git-scm.com/docs/git-push#Documentation/git-push.txt---no-verify)
明确允许跳过推送钩子。要获得不受客户端控制的强制限制，需要远程服务端的拒绝规则；
仅修改本地 hooks 无法作出“任何情况下绝不上传”的保证。

## 验证

`tests/maintenance/test_repository_layout.py` 检查保护规则、忽略规则和当前跟踪列表。
`tests/maintenance/test_repository_hooks.py` 在临时工作副本和本地 bare 远程中，
实际执行提交与推送，确认被拒绝时远程引用未变、错误提交对象未传入远程，
并验证取消跟踪后本地文件仍保留。所有测试数据均为合成内容。

```shell
python -m pytest tests/maintenance/test_repository_layout.py tests/maintenance/test_repository_hooks.py -q
```

测试结束后删除本次临时仓库和前端测试依赖、缓存；保留维护中的测试代码。
