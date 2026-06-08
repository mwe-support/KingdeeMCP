# 金蝶 MCP 使用示例

当前 lightweight registry 已迁入只读、写入、审核、下推和轻量运维工具。默认 `read` token 只显示 14 个核心只读工具。这个目录里保留了两类材料：

- 当前可用的只读查询示例。
- 需要 `allowed_tools` 包含 `write` 的写操作、下推、审批示例。

## 当前 lightweight 生产可用示例

| 场景 | 文件 | 主要工具 |
| --- | --- | --- |
| 查询已审核采购订单 | [`procurement-query.md`](./procurement-query.md) | `kingdee_query_purchase_orders` |
| 查询销售订单 | [`sales-query.md`](./sales-query.md) | `kingdee_query_sale_orders` |
| 查询即时库存 | [`inventory-query.md`](./inventory-query.md) | `kingdee_query_inventory` |
| 查询物料档案 | [`material-query.md`](./material-query.md) | `kingdee_query_materials` |
| 查询客户供应商 | [`partner-query.md`](./partner-query.md) | `kingdee_query_partners` |
| 通用查询条件和字段 | [`query-examples.md`](./query-examples.md) | `kingdee_query_bills` |
| 采购询价单只读查询 | [`purchase-inquiry.md`](./purchase-inquiry.md) | `kingdee_query_bills` |
| 调拨申请单只读查询 | [`stock-transfer.md`](./stock-transfer.md) | `kingdee_query_stock_bills` |

## Write Profile 示例

下面这些文档涉及写入、提交、审核、反审核、删除、下推或复合工作流。调用前需要 Bearer token 的 `allowed_tools` 包含 `write`、`all`、`high` 或明确工具名：

| 场景 | 文件 |
| --- | --- |
| 新建采购订单 | [`procurement-create.md`](./procurement-create.md) |
| 批量审核单据 | [`procurement-audit.md`](./procurement-audit.md) |
| 下推生成入库单 | [`push-stock-in.md`](./push-stock-in.md) |
| 生产订单/领料/入库全流程 | [`production-mgmt.md`](./production-mgmt.md) |
| 质量检验单写操作 | [`quality-inspection.md`](./quality-inspection.md) |
| 审批流操作 | [`workflow-approve.md`](./workflow-approve.md) |
| 单据生命周期与写操作提示 | [`workflow-hints.md`](./workflow-hints.md) |
| 操作日志查询 | [`operation-log.md`](./operation-log.md) |
| 成本管理扩展场景 | [`cost-mgmt.md`](./cost-mgmt.md) |

## 通用查询技巧

```sql
FDocumentStatus='C'
FDate>='2026-04-01' and FDate<='2026-04-30'
FSupplierId.FNumber='S001'
FMaterialId.FNumber='MAT001'
FBillNo='PO2026040001'
FMaterialId.FName like '%钢材%'
```

默认查询应限制结果数量。大多数 lightweight 工具默认 `limit=20`，上限通常为 `100`。
