# mailu：原生账号连接候选版本

现行插件保持 stdio；本目录新增可独立运行的只读 HTTP MCP。它提供 `connected_profile` 和 `mailu_list_messages`（读取所连接邮箱最近十封邮件的列表。）。本版本尚未注册到 OpenAI，也没有修改已安装插件页。现行版其余工具继续在原安装中工作。

1. 在独立 Python 3.11+ 环境执行 `python -m pip install -r native_account/requirements.txt`。按仓库主 README 另行安装原有后端和依赖，确认每个后端账号单独可用。
2. 使用你控制的 OAuth 授权服务器，开启授权码、S256、账号选择，签发 RS256 JWT：issuer 为配置的精确值，audience 为 HTTPS MCP URL（含 `/mcp`），scope 含 `connector.read`，含稳定的 `sub` 和过期时间。授权服务器必须支持客户端发现，并允许在 OpenAI 配置客户端或动态注册。给各个可连接的业务身份绑定各自的 subject；同一 subject 不可指向两个上游账号。
3. 复制 `bindings.example.json` 到发布目录以外，填入真实 issuer、JWKS、服务域名、后端解释器、独立 home 和上游配置。为每个新增业务账号生成永久的随机 UUID，断开或重新授权同一个账号时保持不变。配置与密钥应由服务用户独占，禁止将其上传到 Git；不要将新身份自动绑定管理员。若改变绑定，重启这个独立接入服务。管理页的「连接另一个账号」不会自动创建上游邮箱、网站用户、浏览器登录或授权服务器账号。
4. 设置 `CONNECTOR_BINDINGS_FILE` 和 `CONNECTOR_LISTEN_PORT`，运行 `python native_account/account_http.py`。在部署方选用的独立 HTTPS origin 暴露 `/mcp` 与原生 OAuth protected-resource 发现路由；不转发业务后台或本机文件目录。不同插件使用不同的 MCP audience。
5. 在 OpenAI 自定义 MCP 设置中注册该 HTTPS 地址，绑定到对应账号插件；实际完成两个账号授权，在原生页面测试重命名、重连、断开，再启用替换版。不要把后端业务 ID 当作 OpenAI App ID，不要把旧共享账号作为 HTTP 请求的兜底。
6. 运行 `python native_account/native_subject_test.py` 测试：两个签名身份分别读取各自的测试后端，错误 audience 或过期令牌被拒绝，未知身份不能访问数据。测试不使用真实账号，也不证明平台页面已开通。

回退：停用这个独立 HTTP 服务并解绑其 App；原有 stdio 工具、业务数据和上游账号不受该候选版影响。

平台成功登记后，从 OpenAI 实际发现结果复制本服务的 App ID，再运行 `python native_account/prepare_app_binding.py <解包的当前私有插件> <已核实的AppID> <全新的私有目录>`，生成三份待审核的清单。此工具不上传、不替换现行插件，不会将旧 stdio 工具自动转成按账号路由。保留原 ZIP 作为回退；旧工具与原生工具容易混淆时，不应同时展示同名工具。先用平台测试连接完成双账号验收，并确定每个操作走选中账号，再对原插件 ID 发布。不要将生成的 App ID 或依赖清单提交到公共仓库。
