# KingdeeMCP - 金蝶云星空轻量 MCP 网关

KingdeeMCP 当前生产实现是一个轻量 MCP Gateway，用于让 MCP 客户端安全地调用金蝶云星空 K/3 Cloud WebAPI。它不再依赖 FastMCP/Starlette/uvicorn/SSE，而是使用 Python 标准库实现普通 JSON-RPC HTTP/stdio 协议层，并保留金蝶官方 `LoginByAppSecret` 认证链路。

## 当前结论

- 生产服务只监听本机：`MCP_HOST=127.0.0.1`。
- 推荐本地端口：`MCP_PORT=8199`。
- 远程访问通过 Cloudflare Tunnel/Access，不直接暴露 MCP origin 端口。
- HTTP 响应是 `application/json` + `Content-Length`，不返回 `text/event-stream`，不使用 `mcp-session-id`。
- Bearer Token 映射到 `operator`、`kingdee_username`、`allowed_tools`。
- 金蝶 WebAPI 仍使用共享 `AppID/AppSecret` + 指定金蝶用户 `LoginByAppSecret` 登录。
- 当前生产只注册 14 个核心只读工具；写入、审核、删除、反审核、下推、SQL 探查不进入第一版 lightweight 工具面。

## 架构

```text
MCP Client
  -> Cloudflare Access/Tunnel, optional but recommended for remote access
  -> local origin http://127.0.0.1:8199/mcp
  -> lightweight JSON-RPC dispatcher
  -> Bearer token hash mapping
  -> per-Kingdee-user session cache
  -> Kingdee WebAPI over httpx HTTP/1.1
```

生产入口：

```text
kingdee-mcp -> kingdee_mcp.main:main -> kingdee_mcp.mcp_lite
```

主要模块：

| 文件 | 作用 |
| --- | --- |
| `src/kingdee_mcp/mcp_lite.py` | 轻量 MCP HTTP/stdio 协议层。 |
| `src/kingdee_mcp/light_tools.py` | 14 个生产只读工具、手写 JSON Schema 和参数校验。 |
| `src/kingdee_mcp/kingdee_client.py` | 金蝶 WebAPI 调用封装。 |
| `src/kingdee_mcp/kingdee_session.py` | 每个金蝶用户的 session cache 和刷新。 |
| `src/kingdee_mcp/auth.py` | Bearer token hash 校验和 OperatorContext。 |
| `src/kingdee_mcp/config.py` | 环境变量读取。 |
| `src/kingdee_mcp/server.py` | 旧 FastMCP 实现，仅作为 legacy 参考。 |

## 安装

在服务器仓库目录：

```bash
cd /public/KingdeeMCP
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

生产依赖保持轻量，必需运行依赖是 `httpx`。旧 FastMCP/Pydantic/pyodbc 能力不属于当前生产入口。

## 配置文件

复制模板：

```bash
cd /public/KingdeeMCP
cp .env.example .env
chmod 600 .env
```

完整环境变量说明见 [docs/configuration.md](docs/configuration.md)。当前 `.env.example` 中每个变量上方都有注释。

### 推荐生产配置

```env
KINGDEE_SERVER_URL=https://your-kingdee-host/k3cloud/
KINGDEE_ACCT_ID=your_acct_id
KINGDEE_APP_ID=your_app_id
KINGDEE_APP_SEC=your_app_secret
KINGDEE_LCID=2052
KINGDEE_USERNAME=

MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=8199
MCP_PATH=/mcp
MCP_TOKEN_CONFIG=/public/KingdeeMCP/secrets/tokens.json
MCP_AUTH_DISABLED=false

MCP_MAX_CONCURRENT_TOOLS=8
MCP_MAX_CONCURRENT_KINGDEE_REQUESTS=4
MCP_TOOL_QUEUE_TIMEOUT_SECONDS=3
MCP_TOOL_CALL_TIMEOUT_SECONDS=120
MCP_HTTP_REQUEST_QUEUE_SIZE=128
```

`KINGDEE_USERNAME` 在 HTTP 生产模式下应留空。共享远程部署不使用一个全局金蝶用户，而是从 Bearer Token 映射出 `kingdee_username`。

## 环境变量说明

| 变量 | 推荐值 | 是否生产需要 | 说明 |
| --- | --- | --- | --- |
| `KINGDEE_SERVER_URL` | `https://your-kingdee-host/k3cloud/` | 是 | 金蝶 WebAPI 根地址，必须包含 `/k3cloud/` 后缀。 |
| `KINGDEE_ACCT_ID` | 账套 ID | 是 | 传给 `LoginByAppSecret` 的账套 ID。 |
| `KINGDEE_APP_ID` | 应用 ID | 是 | 金蝶后台第三方系统登录授权中的应用 ID。 |
| `KINGDEE_APP_SEC` | 应用密钥 | 是 | 金蝶后台第三方系统登录授权中的应用密钥，只能保存在服务器。 |
| `KINGDEE_LCID` | `2052` | 否 | 金蝶语言标识，`2052` 为简体中文。 |
| `KINGDEE_USERNAME` | 空 | 仅本地测试 | stdio、`--check`、`MCP_AUTH_DISABLED=true` 时的本地 fallback 用户。HTTP 生产不用它。 |
| `MCP_TRANSPORT` | `streamable-http` | 是 | 启动 lightweight HTTP 网关。`stdio` 仅用于本地测试。 |
| `MCP_HOST` | `127.0.0.1` | 是 | MCP origin 监听地址。出于安全考虑必须只监听本机。 |
| `MCP_PORT` | `8199` | 是 | MCP origin 本地端口。Cloudflared 连接这个端口。 |
| `MCP_PATH` | `/mcp` | 是 | MCP JSON-RPC HTTP 路径。 |
| `MCP_TOKEN_CONFIG` | `/public/KingdeeMCP/secrets/tokens.json` | 是 | Bearer token hash 映射文件路径。 |
| `MCP_AUTH_DISABLED` | `false` | 是 | 只允许本地测试设为 `true`，生产必须为 `false`。 |
| `MCP_MAX_CONCURRENT_TOOLS` | `8` | 否 | MCP 工具处理器最大并发数。 |
| `MCP_MAX_CONCURRENT_KINGDEE_REQUESTS` | `4` | 否 | 对金蝶 WebAPI 的最大并发请求数。 |
| `MCP_TOOL_QUEUE_TIMEOUT_SECONDS` | `3` | 否 | 等待工具并发槽位的时间，超时返回 `server_busy`。 |
| `MCP_TOOL_CALL_TIMEOUT_SECONDS` | `120` | 否 | 单次工具调用最大执行时间。 |
| `MCP_HTTP_REQUEST_QUEUE_SIZE` | `128` | 否 | 本地 HTTP server TCP backlog。 |

以下旧变量不被 lightweight 生产入口读取，不应放入当前生产 `.env`：

```text
MCP_JSON_RESPONSE
MCP_STATELESS_HTTP
MCP_AUTH_ISSUER_URL
MCP_RESOURCE_SERVER_URL
MCP_USAGE_LOG
MCP_USAGE_LOG_DIR
MCP_MAX_CONCURRENT_WRITE_TOOLS
MCP_MAX_CONCURRENT_DESTRUCTIVE_TOOLS
MCP_MAX_CONCURRENT_TOOLS_PER_OPERATOR
MCP_KINGDEE_QUEUE_TIMEOUT_SECONDS
MCP_RATE_LIMIT_GLOBAL_PER_MINUTE
MCP_RATE_LIMIT_PER_OPERATOR_PER_MINUTE
MCP_SQLSERVER_HOST
MCP_SQLSERVER_PORT
MCP_SQLSERVER_USER
MCP_SQLSERVER_PASSWORD
MCP_SQLSERVER_DATABASE
MCP_SQLSERVER_SCHEMA
MCP_SQLSERVER_DRIVER
```

## Bearer Token 配置

生成一个只读 token，并写入 hash mapping：

```bash
cd /public/KingdeeMCP
/public/KingdeeMCP/scripts/generate_token.sh \
  --operator zhangsan \
  --kingdee-username zhangsan
```

脚本不要求安装 `kingdee-mcp` 包或激活 venv，只需要系统有 Python 3。脚本会优先使用 `--config`、环境变量 `MCP_TOKEN_CONFIG`、`.env` 中的 `MCP_TOKEN_CONFIG`，否则默认写入 `/public/KingdeeMCP/secrets/tokens.json`。

脚本会打印一次明文 Bearer token。配置文件只保存 hash，不保存明文 token。明文 token 需要交给 MCP 客户端配置保存。运行中的 MCP 服务会自动热加载 `tokens.json`，新增、禁用或删除 token 后不需要重启 systemd 服务。

`tokens.json` 结构：

```json
{
  "tokens": {
    "sha256:<token_hash>": {
      "operator": "zhangsan",
      "kingdee_username": "zhangsan",
      "enabled": true,
      "allowed_tools": ["read"]
    }
  }
}
```

当前生产建议只使用 `allowed_tools=["read"]`。legacy profile 名称不会在 lightweight 入口中开放写工具。

兼容旧自动化的 `kingdee-mcp-token` console script 仍保留，但新部署和运维文档推荐使用 `scripts/generate_token.sh`。

## systemd 部署

安装 systemd unit：

```bash
sudo /public/KingdeeMCP/scripts/install_systemd_service.sh
sudo systemctl enable kingdee-mcp.service
sudo systemctl restart kingdee-mcp.service
```

检查状态：

```bash
systemctl is-active kingdee-mcp.service
systemctl show kingdee-mcp.service -p MainPID -p MemoryCurrent -p MemoryPeak --no-pager
ss -ltnp | grep ':8199'
curl -sS http://127.0.0.1:8199/healthz
```

预期：

- 服务为 `active`。
- 只监听 `127.0.0.1:8199`。
- `/healthz` 返回 `kingdee-mcp-lite`。
- 不出现 `0.0.0.0:8199` 或公网监听。

## Cloudflare Tunnel 部署

Cloudflared 只负责把外部域名安全转发到本地 origin：

```text
http://127.0.0.1:8199/mcp
```

Docker Compose 说明见 [deploy/cloudflared/README.md](deploy/cloudflared/README.md)。Cloudflare Access 推荐保持一个 Service Auth 策略，客户端必需传：

```text
CF-Access-Client-Id: <cloudflare access client id>
CF-Access-Client-Secret: <cloudflare access client secret>
Authorization: Bearer <kingdee mcp bearer token>
```

`User-Agent: KingdeeMCP-Client/1.0` 只作为可选兼容项，用于 Cloudflare 区域存在浏览器类检查且影响 API 客户端时。

浏览器或 WebView 客户端如果报 `failed fetch`，通常是 CORS 预检失败。推荐在 Cloudflare Access 应用中启用 `options_preflight_bypass`，不要再配置 Access 自身的 CORS allowlist；`OPTIONS` 会直接到达本地轻量 MCP 服务，由 `MCP_CORS_ALLOW_ORIGINS` 控制响应头。`POST` 工具调用仍然必须同时通过 Cloudflare Service Auth 和 MCP Bearer token。

## MCP 客户端配置模板

远程 HTTP 客户端应连接 Cloudflare 域名，而不是服务器本地端口。示例字段名会因客户端不同而略有差异：

```json
{
  "mcpServers": {
    "kingdee": {
      "type": "http",
      "url": "https://your-cloudflare-domain.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <kingdee-mcp-token>",
        "CF-Access-Client-Id": "<cloudflare-access-client-id>",
        "CF-Access-Client-Secret": "<cloudflare-access-client-secret>"
      }
    }
  }
}
```

本地 stdio 只用于开发或单用户测试：

```json
{
  "mcpServers": {
    "kingdee-local": {
      "command": "/public/KingdeeMCP/.venv/bin/kingdee-mcp",
      "env": {
        "MCP_TRANSPORT": "stdio",
        "KINGDEE_SERVER_URL": "https://your-kingdee-host/k3cloud/",
        "KINGDEE_ACCT_ID": "your_acct_id",
        "KINGDEE_USERNAME": "single_test_user",
        "KINGDEE_APP_ID": "your_app_id",
        "KINGDEE_APP_SEC": "your_app_secret",
        "KINGDEE_LCID": "2052"
      }
    }
  }
}
```

## 当前生产工具列表

| 工具 | 说明 | 常用参数 |
| --- | --- | --- |
| `kingdee_smoke_test` | 检查 MCP 认证、token 映射用户、金蝶登录链路，可选小查询。 | `run_query` |
| `kingdee_query_bills` | 通用单据查询。 | `form_id`, `filter_string`, `field_keys`, `limit` |
| `kingdee_view_bill` | 查看单据详情。 | `form_id`, `bill_id`, `mode` |
| `kingdee_query_purchase_orders` | 查询采购订单。 | `filter_string`, `limit` |
| `kingdee_query_purchase_order_progress` | 查询采购订单执行进度。 | `filter_string`, `limit` |
| `kingdee_query_sale_orders` | 查询销售订单。 | `filter_string`, `limit` |
| `kingdee_query_stock_bills` | 查询库存单据。 | `form_id`, `filter_string`, `limit` |
| `kingdee_query_inventory` | 查询即时库存，默认只查有库存记录。 | `filter_string`, `limit` |
| `kingdee_query_materials` | 查询物料档案。 | `filter_string`, `limit` |
| `kingdee_query_partners` | 查询客户或供应商。 | `partner_type`, `filter_string`, `limit` |
| `kingdee_list_forms` | 查看当前内置表单目录。 | `keyword` |
| `kingdee_get_fields` | 查看推荐字段和可用元数据摘要。 | `form_id` |
| `kingdee_query_pending_approvals` | 按状态查询待处理/已审核/驳回类单据。 | `form_id`, `status`, `limit` |
| `kingdee_query_workflow_status` | 查看单据工作流/单据状态摘要。 | `form_id`, `bill_id` |

未注册的 legacy 工具调用应返回 unknown/disallowed，不应触发金蝶 WebAPI。

## 测试

轻量入口目标测试：

```bash
cd /public/KingdeeMCP
. .venv/bin/activate
python -m pytest tests/test_lightweight_mcp.py tests/test_auth_mapping.py tests/test_token_cli.py tests/test_kingdee_session.py -q
```

协议和服务检查：

```bash
curl -sS http://127.0.0.1:8199/healthz
```

真实金蝶链路最小烟测建议先跑：

```text
kingdee_smoke_test(run_query=false)
```

`run_query=false` 只验证认证和登录链路，避免在连通性未确认前放大查询负载。

## 故障排查

| 现象 | 判断 |
| --- | --- |
| `401 missing_or_invalid_bearer` | 缺失、错误或禁用 Bearer token；检查 `MCP_TOKEN_CONFIG`。 |
| `server_busy` | 并发超过 `MCP_MAX_CONCURRENT_TOOLS` 或队列等待超时；稍后重试或调低客户端并发。 |
| 金蝶登录失败 | 检查 `KINGDEE_SERVER_URL`、账套、AppID/AppSecret、token 映射的 `kingdee_username` 是否在金蝶后台允许指定用户登录。 |
| `Connection refused` | 当前服务器到 `KINGDEE_SERVER_URL` 主机/端口不可达，不是 MCP 协议问题。 |
| 客户端拿到 SSE/session 相关错误 | 确认客户端走的是 lightweight HTTP endpoint；生产入口不会返回 SSE 或 `mcp-session-id`。 |
| 服务监听公网 | 立即改回 `MCP_HOST=127.0.0.1` 并重启 systemd。 |

## 文档索引

- [docs/configuration.md](docs/configuration.md): 当前环境变量和安全默认值。
- [docs/rate-limiting.md](docs/rate-limiting.md): lightweight 并发控制策略。
- [docs/streamable-http-auth-design.md](docs/streamable-http-auth-design.md): 当前 HTTP 和多用户认证设计。
- [docs/permission-architecture.md](docs/permission-architecture.md): Bearer Token 到金蝶用户的权限模型。
- [deploy/cloudflared/README.md](deploy/cloudflared/README.md): Cloudflared Docker Compose 运行说明。

## Legacy 说明

旧 FastMCP `server.py`、写操作工具、SQL 探查、usage-log 工具和大量历史 examples 仍可作为参考材料，但不是当前 lightweight 生产工具面。后续如果要恢复写操作，应先重新设计审批、限流、审计和权限边界，再注册到 lightweight 工具表。

## License

MIT
