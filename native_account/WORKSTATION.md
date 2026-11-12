# 在插件页连接工作站账号

管理员先在工作站运行仓库的 `account_manager.py` 添加账号。安装根目录依赖和 `native_account/requirements-workstation.txt`，并准备上游 CLI 或浏览器等本产品需要的依赖。从仓库根目录运行：

```
python native_account/workstation_host.py private-service.json
```

从 `native_account/service.example.json` 复制私有配置。填写自己的域名，服务进程的工作目录用于解析示例的相对路径。给状态目录配置仅服务用户可读写的权限。仅把 18641 的 MCP、OAuth 和发现路由交给 HTTPS 入口。18642 专用于本机账号选择，始终绑定回环地址。私有服务由部署者的进程管理器启动。

在 Codex 中用 HTTPS 地址 `/codex-accounts/primary/mcp` 创建一次 OAuth 应用插件。账户随后通过插件管理页连接。授权时需在持有凭据的工作站浏览器选定账号，后续读取只需工作站在线。需要第二个账号时，在同一插件页选择「连接另一个账户」。每份授权绑定一个本机配置。断开一份授权会撤销对应的令牌。部署方负责保护本机账号资料及授权数据库。

本服务对远端开放选定账号的身份及固定的只读操作。原有完整运维、写入和传输工具通过明确选定账号的本地客户端使用。工作站窗口可添加配置，也可以调用相应服务的官方登录。
