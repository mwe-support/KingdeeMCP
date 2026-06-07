# 金蝶云星空 MCP 轻量网关：让 AI 安全查询 ERP 数据

本文介绍当前 KingdeeMCP 的 lightweight 生产实现：通过 MCP（Model Context Protocol）让 Claude、Cursor、Windsurf、Cline 等客户端访问金蝶云星空 K/3 Cloud WebAPI。

当前生产版本聚焦安全和稳定：只暴露 14 个核心只读工具，MCP 服务只监听 `127.0.0.1:8199`，远程访问通过 Cloudflare Tunnel/Access 进入。

## 适合解决什么问题

- 业务人员想快速查询采购订单、销售订单、库存、物料、客户和供应商。
- 实施人员想用自然语言验证金蝶 WebAPI 配置和字段。
- 管理员希望不同 MCP token 映射到不同金蝶用户，继续沿用金蝶原有角色和权限。
- 运维希望 MCP 服务轻量、低内存、无 FastMCP/uvicorn/SSE 长连接负担。

## 当前生产能力

当前 lightweight 入口注册 14 个只读工具：

- `kingdee_smoke_test`
- `kingdee_query_bills`
- `kingdee_view_bill`
- `kingdee_query_purchase_orders`
- `kingdee_query_purchase_order_progress`
- `kingdee_query_sale_orders`
- `kingdee_query_stock_bills`
- `kingdee_query_inventory`
- `kingdee_query_materials`
- `kingdee_query_partners`
- `kingdee_list_forms`
- `kingdee_get_fields`
- `kingdee_query_pending_approvals`
- `kingdee_query_workflow_status`

写入、提交、审核、反审核、删除、下推、SQL 探查不属于第一版 lightweight 生产工具面。

## 认证模型

KingdeeMCP 自身使用 Bearer Token 认证。每个 token 在 `MCP_TOKEN_CONFIG` 中映射到：

```json
{
  "operator": "zhangsan",
  "kingdee_username": "zhangsan",
  "enabled": true,
  "allowed_tools": ["read"]
}
```

- `operator` 是 MCP 调用方身份。
- `kingdee_username` 是真正用于 `LoginByAppSecret` 的金蝶用户。
- 金蝶自身的角色、功能权限、数据权限继续生效。

## 安全部署建议

`.env` 中保持：

```env
MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=8199
MCP_PATH=/mcp
MCP_AUTH_DISABLED=false
```

不要把 MCP origin 直接暴露到公网。外部访问建议使用 Cloudflare Tunnel/Access，并在客户端同时传：

```text
Authorization: Bearer <kingdee mcp bearer token>
CF-Access-Client-Id: <cloudflare access client id>
CF-Access-Client-Secret: <cloudflare access client secret>
```

`User-Agent: KingdeeMCP-Client/1.0` 只作为 Cloudflare 浏览器类检查影响 API 客户端时的可选兼容项。

## 快速安装

```bash
cd /public/KingdeeMCP
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
chmod 600 .env
```

生成只读 token：

```bash
kingdee-mcp-token create \
  --operator zhangsan \
  --kingdee-username zhangsan \
  --allow read \
  --config /public/KingdeeMCP/secrets/tokens.json
```

启动 systemd：

```bash
sudo /public/KingdeeMCP/scripts/install_systemd_service.sh
sudo systemctl restart kingdee-mcp.service
curl -sS http://127.0.0.1:8199/healthz
```

## 客户端示例

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

## 典型问题

可以直接问 AI：

- 查询最近 20 条已审核的采购订单。
- 查一下有库存的前 20 条记录。
- 查询某个客户的销售订单。
- 查看 `STK_Inventory` 有哪些推荐字段。
- 验证当前 token 映射的金蝶用户能否登录。

## 项目地址

- GitHub: https://github.com/WaHaiLong/KingdeeMCP
- PyPI: https://pypi.org/project/kingdee-mcp/
- MCP 协议: https://modelcontextprotocol.io/

关键词：金蝶 MCP、金蝶云星空 AI、MCP Server、金蝶 ERP 查询、Cloudflare Access、Bearer Token、轻量 MCP 网关
