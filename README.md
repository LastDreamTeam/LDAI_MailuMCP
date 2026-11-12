# Mailu Mail MCP

> **自用项目** · 本仓库主要供维护者自用。

使用所配置 Mailu 站点的原生 REST API 管理邮箱和别名，可通过单独授权的 IMAP 账号读取邮件。

## 安装和认证

Python 3.11+。运行 `python -m venv .venv` 后，在该环境中运行 `python -m pip install -r requirements.txt`。设置 `MAILU_API_URL` 为实际原生 API 地址（含 `/api/v1`），`MAILU_API_TOKEN_FILE` 为自己的令牌文件。读取邮件还需配置 `MAILU_IMAP_HOST`、`MAILU_IMAP_USER`、`MAILU_IMAP_PASSWORD_FILE`；默认使用 TLS 的 993 端口。支持邮箱与别名查询、创建、消息头和正文读取。创建邮箱时，在仅管理员可读的 `MAILU_NEW_PASSWORD_DIR` 内预置以小写邮箱地址的 SHA-256 加 `.txt` 命名的初始密码文件。别名目标限已存在的本地邮箱。[Mailu REST API](https://mailu.io/2024.06/api.html)

使用 `python client_config.py cursor`、`python client_config.py dsh` 或 `python client_config.py codex` 输出对应客户端的配置。将其合并到已有 MCP 或 DSH 插件列表。配置生成器接受重复的 `--env NAME=VALUE` 以传递路径和站点设置。

## 账号管理窗口

账号版从本插件详情页点「管理」→「已连接的账户」→「连接另一个账户」。已连接账号右侧菜单提供重命名、重新连接和断开连接。

使用独立 stdio 客户端时可运行 `python account_manager.py` 设置本机账号。站点与凭据保存在部署端；图形窗口需要 Python 的 Tk 组件。

管理 API 注册邮箱、设置密码、管理别名。改密使用 MAILU_NEW_PASSWORD_DIR 下以小写邮箱地址 SHA-256 命名的 .txt 私有文件。IMAP 读信，SMTP 支持发送、抄送和带 In-Reply-To 的回复。发送使用所选邮箱的独立 SMTP 凭据（可与此账号的 IMAP 登录一致）。SMTP 接受表示提交到邮件服务器，收件端投递另行确认。

## 多账号和终端更新

MCP 入口为 `router.py`，需要 Python 3.11+。主机在本地保存账号配置，默认位置为 `~/.config/ldai-mcp/mailu/accounts.json`，也可用 `LDAI_ACCOUNTS_FILE` 指定。复制 [两账号示例](examples/accounts.example.json)，将地址与路径换成自己的值。每个账号可以对应不同的 Mailu 站点、管理令牌或 IMAP 邮箱。只读个人收件箱时仅需该账号的 IMAP 配置。

`ldai_accounts` 仅列出别名和连接状态。配置两个账号后，工具以 `work__` 和 `personal__` 前缀区分，所选工具始终进入该账号的独立子进程。已有单账号配置继续使用原工具名。运行 `python profile_exec.py work -- <程序> <参数…>` 可在同一账号环境完成登录或初始化。完成配置后重新连接 MCP。需要自有适配器时，管理员可为某个账号填写可信 stdio 程序的 `command`、`args` 和 `env`；连接器仅发布当前产品前缀下的业务工具。

安装本仓库后，其他终端可运行 `git pull --ff-only`；Python 服务在其虚拟环境执行 `python -m pip install -r requirements.txt`，随后重新加载客户端。需要固定版本时可检出发布标签。

维护者在 main 提交改进、运行测试，并同步更新 connector.json、两个插件清单的版本，再执行 `python build_plugin.py --push`。此命令将 main 与版本标签一起推送到本仓库，再从已提交文件生成 ZIP。更新既有账号插件时传 `--account-name <既有包名>`，把生成的 ZIP 发布到同一插件。包内 release-source.json 记录精确提交，可与各终端核对。Git 推送与账号插件发布是两个独立步骤。

许可为 **AGPL-3.0-only**。[许可全文](LICENSE)

## 实现参考

按 Mailu 原生资源实现邮箱和别名操作，并对照社区连接器的认证与资源映射。GitHub 统计核对日期为 2026-11-11。

- [Mailu/Mailu](https://github.com/Mailu/Mailu) · 7614 stars，默认分支 5425 次提交
- [manganate006/mailu-mcp](https://github.com/manganate006/mailu-mcp) · 0 stars，默认分支 19 次提交

[原生插件页多账号接入候选版：部署、覆盖范围与验收](native_account/README.md)

使用 Codex 插件页连接、重连和管理多个工作站账号，见[工作站接入](native_account/WORKSTATION.md)。
