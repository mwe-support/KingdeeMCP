# 示例：工作流待办与审批

使用已有的真实工作流接口，不用传统审核代替节点审批。
查询需要 full-read/write 或对应工具授权；审批需要 write 或对应写工具授权。

## 1. 查询本人待办

```json
{"tool":"kingdee_workflow_tasks","params":{"form_id":"BD_Material","bill_number":"TEST_MATERIAL","limit":20}}
```

检查返回的 `task_id`、关联单据、节点、处理人和 `can_process`。
不要把物料 FID 或实例编码当作 task_id。

## 2. 读取任务详情

```json
{"tool":"kingdee_workflow_task","params":{"task_id":"<receiver-task-id>"}}
```

## 3. 明确授权后处理

```json
{"tool":"kingdee_workflow_approve","params":{"task_id":"<receiver-task-id>","action":"approve","opinion":"同意"}}
```

驳回使用 `action="reject"`，同样走 WorkflowAudit，绝不是反审核。
可附带 form_id 和 bill_id，服务会先核对其与任务一致。

## 4. 回读验证

检查 `success`、`verified` 和 `after.opinion`，并再次查询任务详情。
通过一级节点后，单据可能仍为 B，不能据此认为审批失败或重复提交。
超时或 `outcome_unknown` 后只读查状态，不盲目重试。
下一节点的待办由下一处理人自己的凭证查询，不自动换人继续审批。

完整字段、安全约束和部署说明见 [工作流工具链](../docs/workflow.md)。
