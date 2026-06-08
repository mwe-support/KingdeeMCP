from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .auth import OperatorContext
from .kingdee_client import KingdeeWebAPIClient, metadata_summary, rows, simplify_view_result

ToolHandler = Callable[[dict[str, Any], OperatorContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler

    def as_mcp_tool(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


CORE_READ_TOOL_NAMES = frozenset(
    {
        "kingdee_smoke_test",
        "kingdee_query_bills",
        "kingdee_view_bill",
        "kingdee_query_purchase_orders",
        "kingdee_query_purchase_order_progress",
        "kingdee_query_sale_orders",
        "kingdee_query_stock_bills",
        "kingdee_query_inventory",
        "kingdee_query_materials",
        "kingdee_query_partners",
        "kingdee_list_forms",
        "kingdee_get_fields",
        "kingdee_query_pending_approvals",
        "kingdee_query_workflow_status",
    }
)

FORM_CATALOG: dict[str, dict[str, Any]] = {
    "PUR_PurchaseOrder": {"name": "采购订单", "alias": ["采购", "采购订单", "PO"], "desc": "供应商采购订单", "fields": "FID,FBillNo,FDate,FDocumentStatus,FSupplierId.FName,FPurchaseDeptId.FName,FTaxAmount,FAllAmount,FReceiveQty,FStockInQty"},
    "SAL_SaleOrder": {"name": "销售订单", "alias": ["销售", "销售订单", "SO"], "desc": "客户销售订单", "fields": "FID,FBillNo,FDate,FDocumentStatus,FCustId.FName,FTotalAmount"},
    "STK_InStock": {"name": "采购入库单", "alias": ["入库", "采购入库"], "desc": "采购业务入库单据", "fields": "FID,FBillNo,FDate,FDocumentStatus,FStockOrgId.FName"},
    "SAL_OUTSTOCK": {"name": "销售出库单", "alias": ["出库", "销售出库"], "desc": "销售业务出库单据", "fields": "FID,FBillNo,FDate,FDocumentStatus,FStockOrgId.FName"},
    "STK_MisDelivery": {"name": "其他出库单", "alias": ["其他出库", "出库"], "desc": "非销售业务出库单据", "fields": "FID,FBillNo,FDate,FDocumentStatus,FStockOrgId.FName"},
    "STK_Miscellaneous": {"name": "其他入库单", "alias": ["其他入库", "入库"], "desc": "非采购业务入库单据", "fields": "FID,FBillNo,FDate,FDocumentStatus,FStockOrgId.FName"},
    "STK_TransferDirect": {"name": "直接调拨单", "alias": ["调拨", "直接调拨"], "desc": "库存调拨单据", "fields": "FID,FBillNo,FDate,FDocumentStatus,FStockOutId.FName,FStockInId.FName"},
    "STK_Inventory": {"name": "即时库存", "alias": ["库存", "即时库存", "库存查询"], "desc": "物料当前库存", "fields": "FMaterialId.FNumber,FMaterialId.FName,FStockId.FName,FBaseQty,FBaseUnitId.FName"},
    "BD_Material": {"name": "物料", "alias": ["物料", "产品", "SKU"], "desc": "物料基础资料", "fields": "FMaterialId,FNumber,FName,FSpecification,FMaterialGroup.FName"},
    "BD_Customer": {"name": "客户", "alias": ["客户"], "desc": "客户基础资料", "fields": "FNumber,FName,FShortName,FContact,FPhone,FDocumentStatus"},
    "BD_Supplier": {"name": "供应商", "alias": ["供应商"], "desc": "供应商基础资料", "fields": "FNumber,FName,FShortName,FContact,FPhone,FDocumentStatus"},
}


def build_core_read_tools(client: KingdeeWebAPIClient) -> dict[str, ToolDefinition]:
    async def smoke(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "operator": context.operator,
            "kingdee_username": context.kingdee_username,
            "allowed_tools": sorted(context.allowed_tools),
            "checks": {},
        }
        await client.ensure_session(context)
        result["checks"]["kingdee_session"] = "ok"
        if args["run_query"]:
            payload = client.query_payload(args["form_id"], args["field_keys"], args["filter_string"], "", 0, args["limit"])
            query_result = await client.post("query", payload, context)
            query_rows = rows(query_result)
            result["checks"]["query"] = "ok"
            result["query"] = {"form_id": args["form_id"], "limit": args["limit"], "row_count": len(query_rows), "has_more": len(query_rows) == args["limit"]}
        else:
            result["checks"]["query"] = "skipped"
        result["ok"] = all(value in {"ok", "skipped"} for value in result["checks"].values())
        return result

    async def query_bills(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        query_result = await client.post("query", client.query_payload(args["form_id"], args["field_keys"], args["filter_string"], args["order_string"], args["start_row"], args["limit"]), context)
        data = rows(query_result)
        return {"form_id": args["form_id"], "start_row": args["start_row"], "count": len(data), "has_more": len(data) == args["limit"], "data": data}

    async def view_bill(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        data = await client.view(args["form_id"], args["bill_id"], context)
        return data if args["mode"] == "full" else simplify_view_result(data)

    async def purchase_orders(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        fields = args["field_keys"] if args["field_keys"] != DEFAULT_QUERY_FIELDS else "FID,FBillNo,FDate,FDocumentStatus,FSupplierId.FName,FPurchaseDeptId.FName,FTaxAmount,FAllAmount,FReceiveQty,FStockInQty"
        data = rows(await client.post("query", client.query_payload("PUR_PurchaseOrder", fields, args["filter_string"], args["order_string"], args["start_row"], args["limit"]), context))
        return {"count": len(data), "has_more": len(data) == args["limit"], "data": data}

    async def purchase_progress(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        fields = "FID,FBillNo,FDate,FDocumentStatus,FSupplierId.FName,FMaterialId.FNumber,FMaterialId.FName,FQty,FReceiveQty,FStockInQty,FPrice,FTaxPrice,FAllAmount"
        data = rows(await client.post("query", client.query_payload("PUR_PurchaseOrder", fields, args["filter_string"] or "FDocumentStatus='C'", "FBillNo DESC,FPOOrderEntry_LineID ASC", args["start_row"], args["limit"]), context))
        return {"tip": "FReceiveQty=累计收料数量，FStockInQty=累计入库数量", "count": len(data), "has_more": len(data) == args["limit"], "data": data}

    async def sale_orders(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        fields = args["field_keys"] if args["field_keys"] != DEFAULT_QUERY_FIELDS else "FID,FBillNo,FDate,FDocumentStatus,FCustId.FName,FTotalAmount"
        data = rows(await client.post("query", client.query_payload("SAL_SaleOrder", fields, args["filter_string"], args["order_string"], args["start_row"], args["limit"]), context))
        return {"count": len(data), "has_more": len(data) == args["limit"], "data": data}

    async def stock_bills(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        fields = args["field_keys"] if args["field_keys"] != DEFAULT_QUERY_FIELDS else "FID,FBillNo,FDate,FDocumentStatus,FStockOrgId.FName"
        data = rows(await client.post("query", client.query_payload(args["form_id"], fields, args["filter_string"], args["order_string"], args["start_row"], args["limit"]), context))
        return {"form_id": args["form_id"], "count": len(data), "has_more": len(data) == args["limit"], "data": data}

    async def inventory(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        data = rows(await client.post("query", client.query_payload("STK_Inventory", args["field_keys"], args["filter_string"], "FMaterialId.FNumber ASC", args["start_row"], args["limit"]), context))
        return {"count": len(data), "data": data}

    async def materials(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        data = rows(await client.post("query", client.query_payload("BD_Material", args["field_keys"], args["filter_string"], "FNumber ASC", args["start_row"], args["limit"]), context))
        return {"count": len(data), "data": data}

    async def partners(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        if args["partner_type"] not in {"BD_Customer", "BD_Supplier"}:
            raise ValueError("partner_type must be BD_Customer or BD_Supplier")
        data = rows(await client.post("query", client.query_payload(args["partner_type"], args["field_keys"], args["filter_string"], "FNumber ASC", args["start_row"], args["limit"]), context))
        return {"type": args["partner_type"], "count": len(data), "data": data}

    async def list_forms(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        keyword = str(args.get("keyword") or "").strip().lower()
        forms = []
        for form_id, info in FORM_CATALOG.items():
            if not keyword or keyword in form_id.lower() or keyword in info["name"].lower() or any(keyword in alias.lower() for alias in info.get("alias", [])):
                forms.append({"form_id": form_id, "name": info["name"], "alias": info.get("alias", []), "desc": info.get("desc", ""), "recommended_fields": info.get("fields", "")})
        return {"count": len(forms), "forms": forms}

    async def get_fields(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        form_id = args["form_id"]
        info = FORM_CATALOG.get(form_id, {})
        result: dict[str, Any] = {
            "form_id": form_id,
            "name": info.get("name", "未知表单"),
            "desc": info.get("desc", ""),
            "recommended_fields": info.get("fields", "FID,FBillNo,FNumber,FName,FDate,FDocumentStatus"),
        }
        try:
            result["metadata"] = metadata_summary(await client.metadata(form_id, context))
        except Exception as exc:
            result["metadata"] = {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        return result

    async def pending_approvals(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        status = args["status"]
        if status == "pending":
            status_filter = "FDocumentStatus IN ('A', 'B', 'D')"
        elif status == "approved":
            status_filter = "FDocumentStatus = 'C'"
        elif status == "rejected":
            status_filter = "FDocumentStatus = 'D'"
        else:
            status_filter = "1=1"
        form_ids = [args["form_id"]] if args["form_id"] else ["PUR_PurchaseOrder", "SAL_SaleOrder", "STK_InStock"]
        results = []
        for form_id in form_ids:
            try:
                data = rows(await client.post("query", client.query_payload(form_id, "FID,FBillNo,FDate,FDocumentStatus", status_filter, "FDate DESC", 0, args["limit"]), context))
            except Exception:
                continue
            if data:
                results.append({"form_id": form_id, "form_name": FORM_CATALOG.get(form_id, {}).get("name", form_id), "count": len(data), "data": data})
        return {"status_filter": status, "total_forms": len(results), "results": results}

    async def workflow_status(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        data = await client.view(args["form_id"], args["bill_id"], context)
        bill_data = data.get("Result", {}).get("Result", data) if isinstance(data, dict) else {}
        status = bill_data.get("FDocumentStatus", "") if isinstance(bill_data, dict) else ""
        return {"form_id": args["form_id"], "bill_id": args["bill_id"], "document_status": status, "status_name": STATUS_MAP.get(status, "未知"), "bill_no": bill_data.get("FBillNo", "") if isinstance(bill_data, dict) else "", "bill_data": bill_data}

    tools = {
        "kingdee_smoke_test": ToolDefinition("kingdee_smoke_test", "Check MCP auth, mapped Kingdee user login, service limits, and optional tiny read-only query.", smoke_schema(), smoke),
        "kingdee_query_bills": ToolDefinition("kingdee_query_bills", "通用单据查询，按表单编码、字段、过滤条件和分页返回数据。", query_schema(required_form=True), query_bills),
        "kingdee_view_bill": ToolDefinition("kingdee_view_bill", "按表单编码和 FID 查看单据详情。", view_schema(), view_bill),
        "kingdee_query_purchase_orders": ToolDefinition("kingdee_query_purchase_orders", "查询采购订单列表。", query_schema(required_form=False), purchase_orders),
        "kingdee_query_purchase_order_progress": ToolDefinition("kingdee_query_purchase_order_progress", "查询采购订单收料和入库进度。", purchase_progress_schema(), purchase_progress),
        "kingdee_query_sale_orders": ToolDefinition("kingdee_query_sale_orders", "查询销售订单列表。", query_schema(required_form=False), sale_orders),
        "kingdee_query_stock_bills": ToolDefinition("kingdee_query_stock_bills", "查询库存相关单据。", query_schema(required_form=True), stock_bills),
        "kingdee_query_inventory": ToolDefinition("kingdee_query_inventory", "查询即时库存，默认只返回有库存的记录。", inventory_schema(), inventory),
        "kingdee_query_materials": ToolDefinition("kingdee_query_materials", "查询物料基础资料。", materials_schema(), materials),
        "kingdee_query_partners": ToolDefinition("kingdee_query_partners", "查询客户或供应商基础资料。", partners_schema(), partners),
        "kingdee_list_forms": ToolDefinition("kingdee_list_forms", "列出常用金蝶表单编码和推荐字段。", object_schema({"keyword": string_prop("按表单编码、名称或别名过滤", "")}), list_forms),
        "kingdee_get_fields": ToolDefinition("kingdee_get_fields", "返回表单推荐字段，并尝试读取 QueryBusinessInfo 元数据。", object_schema({"form_id": string_prop("表单编码，例如 BD_Material 或 PUR_PurchaseOrder", required=True)}, ["form_id"]), get_fields),
        "kingdee_query_pending_approvals": ToolDefinition("kingdee_query_pending_approvals", "查询待提交、审核中、已审核或被驳回的单据。", workflow_query_schema(), pending_approvals),
        "kingdee_query_workflow_status": ToolDefinition("kingdee_query_workflow_status", "查询指定单据的审核状态。", workflow_status_schema(), workflow_status),
    }
    tools.update(build_migrated_lightweight_tools(client, existing=tools))
    return tools


DEFAULT_QUERY_FIELDS = "FID,FBillNo,FDate,FDocumentStatus"
STATUS_MAP = {"A": "创建", "B": "审核中", "C": "已审核", "D": "重新审核", "Z": "暂存"}


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


def string_prop(description: str = "", default: str | None = None, *, required: bool = False) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": "string"}
    if description:
        prop["description"] = description
    if default is not None and not required:
        prop["default"] = default
    return prop


def int_prop(description: str = "", default: int = 0, *, minimum: int = 0, maximum: int | None = None) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": "integer", "default": default, "minimum": minimum}
    if maximum is not None:
        prop["maximum"] = maximum
    if description:
        prop["description"] = description
    return prop


def bool_prop(description: str = "", default: bool = False) -> dict[str, Any]:
    return {"type": "boolean", "default": default, "description": description}


def query_schema(*, required_form: bool) -> dict[str, Any]:
    props = {
        "form_id": string_prop("表单编码", "" if not required_form else None, required=required_form),
        "filter_string": string_prop("过滤条件", ""),
        "field_keys": string_prop("需要返回的字段列表", DEFAULT_QUERY_FIELDS),
        "order_string": string_prop("排序条件", "FID DESC"),
        "start_row": int_prop("起始行号", 0, minimum=0),
        "limit": int_prop("返回条数", 20, minimum=1, maximum=100),
    }
    return object_schema(props, ["form_id"] if required_form else [])


def smoke_schema() -> dict[str, Any]:
    return object_schema(
        {
            "run_query": bool_prop("是否执行一次小型只读查询", True),
            "form_id": string_prop("查询表单编码", "STK_Inventory"),
            "field_keys": string_prop("查询字段列表", "FMaterialId.FNumber,FMaterialId.FName,FStockId.FName,FBaseQty"),
            "filter_string": string_prop("查询过滤条件", "FBaseQty > 0"),
            "limit": int_prop("查询返回条数", 1, minimum=1, maximum=5),
        }
    )


def view_schema() -> dict[str, Any]:
    return object_schema({"form_id": string_prop("表单编码", required=True), "bill_id": string_prop("单据 FID", required=True), "mode": {"type": "string", "enum": ["summary", "full"], "default": "summary"}}, ["form_id", "bill_id"])


def purchase_progress_schema() -> dict[str, Any]:
    return object_schema({"filter_string": string_prop("过滤条件", "FDocumentStatus='C'"), "start_row": int_prop(default=0), "limit": int_prop(default=20, minimum=1, maximum=100)})


def inventory_schema() -> dict[str, Any]:
    return object_schema({"filter_string": string_prop("过滤条件", "FBaseQty>0"), "field_keys": string_prop("字段列表", "FMaterialId.FNumber,FMaterialId.FName,FStockId.FName,FBaseQty,FBaseUnitId.FName"), "start_row": int_prop(default=0), "limit": int_prop(default=20, minimum=1, maximum=100)})


def materials_schema() -> dict[str, Any]:
    return object_schema({"filter_string": string_prop("过滤条件", ""), "field_keys": string_prop("字段列表", "FMaterialId,FNumber,FName,FSpecification,FMaterialGroup.FName"), "start_row": int_prop(default=0), "limit": int_prop(default=20, minimum=1, maximum=100)})


def partners_schema() -> dict[str, Any]:
    return object_schema({"partner_type": {"type": "string", "enum": ["BD_Customer", "BD_Supplier"]}, "filter_string": string_prop("过滤条件", ""), "field_keys": string_prop("字段列表", "FNumber,FName,FShortName,FContact,FPhone,FDocumentStatus"), "start_row": int_prop(default=0), "limit": int_prop(default=20, minimum=1, maximum=100)}, ["partner_type"])


def workflow_query_schema() -> dict[str, Any]:
    return object_schema({"form_id": string_prop("表单编码，留空时查询常用业务单据", ""), "status": {"type": "string", "enum": ["pending", "approved", "rejected", "all"], "default": "pending"}, "limit": int_prop(default=20, minimum=1, maximum=100)})


def workflow_status_schema() -> dict[str, Any]:
    return object_schema({"form_id": string_prop("表单编码", required=True), "bill_id": string_prop("单据 FID", required=True)}, ["form_id", "bill_id"])


# Migrated lightweight catalog.
# These tools use schema-first handlers in the lightweight registry.


@dataclass(frozen=True)
class MigratedQuerySpec:
    name: str
    description: str
    form_id: str
    field_keys: str
    order_string: str = "FID DESC"
    default_filter: str = ""
    default_limit: int = 20
    max_limit: int = 100
    top_style: bool = False


@dataclass(frozen=True)
class MigratedEndpointSpec:
    name: str
    description: str
    ep_key: str
    form_id: str
    field_keys: str
    default_filter: str = ""
    default_limit: int = 20
    max_limit: int = 100


MIGRATED_QUERY_SPECS = (
    MigratedQuerySpec("kingdee_query_expense_reimburse", "Query expense reimbursement bills.", "ER_ExpenseReimburse", "FID,FBillNo,FDate,FDocumentStatus,FApplicantId.FName,FTotalReimAmount,FDescription", "FDate DESC"),
    MigratedQuerySpec("kingdee_query_fixed_asset", "Query fixed asset master data.", "FA_FAGet", "FID,FNumber,FName,FAssetSource,FSpecification,FUsedPeriod,FOriginalAmount,FDepreciateRate,FUseDeptId.FName,FDocumentStatus,FStatus"),
    MigratedQuerySpec("kingdee_query_asset_card", "Query fixed asset cards.", "FA_FAGet", "FID,FNumber,FName,FAssetSource,FOriginalAmount,FTotalDepreciate,FNetAmount,FDepreciateMonth,FUsefulLife,FSalvageValue,FCustodian.FName"),
    MigratedQuerySpec("kingdee_query_asset_depreciation", "Query asset depreciation records.", "FA_DepreciationBill", "FID,FYear,FPeriod,FAssetId.FNumber,FAssetId.FName,FDepreciateDeptId.FName,FDepreciateAmount,FOriginalAmount,FTotalDepreciate,FNetAmount"),
    MigratedQuerySpec("kingdee_query_asset_transfer", "Query asset transfer bills.", "FA_Transfer", "FID,FBillNo,FTransferDate,FDocumentStatus,FAssetId.FNumber,FAssetId.FName,FOldDeptId.FName,FNewDeptId.FName,FTransferReason"),
    MigratedQuerySpec("kingdee_query_asset_scrape", "Query asset disposal bills.", "FA_Scrape", "FID,FBillNo,FScrapeDate,FDocumentStatus,FAssetId.FNumber,FAssetId.FName,FOriginalAmount,FTotalDepreciate,FNetAmount,FScrapeType,FHandleMethod"),
    MigratedQuerySpec("kingdee_query_purchase_requisitions", "Query purchase requisitions.", "PUR_Requisition", "FID,FBillNo,FDate,FDocumentStatus,FApplicantId.FName,FRequestDeptId.FName"),
    MigratedQuerySpec("kingdee_query_sale_quotations", "Query sales quotations.", "SAL_Quotation", "FID,FBillNo,FDate,FDocumentStatus,FCustId.FName,FTotalAmount"),
    MigratedQuerySpec("kingdee_query_quality_inspections", "Query quality inspection bills.", "QIS_InspectBill", "FID,FBillNo,FDate,FDocumentStatus,FSupplierId.FName,FMaterialId.FName,FPassQty,FFailQty"),
    MigratedQuerySpec("kingdee_query_stock_transfer_apply", "Query stock transfer applications.", "STK_TransferApply", "FID,FBillNo,FDate,FDocumentStatus,FSendStockId.FName,FReceiveStockId.FName"),
    MigratedQuerySpec("kingdee_query_audit_log", "Query audit logs.", "BOS_AuditLog", "FID,FCREATEDATE,FCREATORID,FOBJECTID,FFORMID,FOBJECTNO,FAUDITRESULT,FMEMO", "FCREATEDATE DESC", default_limit=50, max_limit=2000),
    MigratedQuerySpec("kingdee_query_operation_logs", "Query operation logs.", "BOS_OperateLog", "FID,FDATETIME,FUSERID,FCOMPUTERNAME,FCLIENTIP,FENVIRONMENT,FOPERATENAME,FDESCRIPTION,FInterId,FTimeConsuming,FClientType", "FDATETIME DESC", default_limit=50, max_limit=2000),
    MigratedQuerySpec("kingdee_query_change_log", "Query document change logs.", "BOS_ModifyLog", "FID,FCREATEDATE,FCREATORID,FOBJECTID,FFORMID,FOBJECTNO,FFIELDNAME,FOLDVALUE,FNEWVALUE", "FCREATEDATE DESC", default_limit=50, max_limit=2000),
    MigratedQuerySpec("kingdee_query_approval_flow", "Query workflow approval records.", "V_SFA_ApprovalRecord", "FID,FCREATEDATE,FCREATORID,FOBJECTID,FFORMID,FOBJECTNO,FNODEID,FNODENAME,FAPPROVERID,FAPPROVERNAME,FAPPROVEDATE,FRESULT,FOPINION,FREMARK", "FCREATEDATE DESC", default_limit=50, max_limit=2000),
    MigratedQuerySpec("kingdee_query_permission", "Query permission change records.", "SEC_Permission", "FID,FCREATEDATE,FCREATORID,FUSERNAME,FTARGETTYPE,FOBJECTTYPE,FOBJECTID,FOBJECTNAME,FACTION,FPRIVILEGE", "FCREATEDATE DESC", default_limit=50, max_limit=2000),
    MigratedQuerySpec("kingdee_query_data_backup", "Query data backup records.", "DB_BackupRecord", "FID,FBACKUPDATE,FOPERATOR,FBACKUPTYPE,FSTATUS,FBACKUPFILE,FBACKUPSIZE,FREMARK", "FBACKUPDATE DESC", default_limit=50, max_limit=2000),
    MigratedQuerySpec("kingdee_query_purchase_inquiry", "Query purchase inquiry bills.", "SVM_InquiryBill", "FID,FBillNo,FDate,FDocumentStatus,FSupplierId.FName"),
    MigratedQuerySpec("kingdee_query_supplier_quotes", "Query supplier quotation bills.", "SVM_QuoteBill", "FID,FBillNo,FDate,FDocumentStatus,FSupplierId.FName,FMaterialId.FName,FPrice"),
    MigratedQuerySpec("kingdee_query_misc_movement_detail", "Query miscellaneous movement details.", "STK_MiscMovementDetail", "FID,FBillNo,FBillDate,FDocumentStatus,FStockOrgId.FName,FMaterialId.FNumber,FMaterialId.FName,FUnitId.FName,FQty,FPrice,FAmount"),
    MigratedQuerySpec("kingdee_query_transfer_pending_detail", "Query pending transfer details.", "STK_TransferPendingDetail", "FID,FBillNo,FOutDate,FInDate,FDocumentStatus,FStockOrgId.FName,FOutStockId.FName,FInStockId.FName,FMaterialId.FNumber,FMaterialId.FName,FUnitId.FName,FOutQty,FInQty,FPendingQty"),
    MigratedQuerySpec("kingdee_query_transfer_apply", "Query transfer applications.", "STK_TransferApply", "FID,FBillNo,FBillDate,FDocumentStatus,FStockOrgId.FName,FOutStockId.FName,FInStockId.FName,FTransferType,FMaterialId.FNumber,FMaterialId.FName,FUnitId.FName,FQty,FPrice,FAmount"),
    MigratedQuerySpec("kingdee_query_transfer_direct", "Query direct transfer bills.", "STK_TransferDirect", "FID,FBillNo,FBillDate,FDocumentStatus,FStockOrgId.FName,FOutStockId.FName,FInStockId.FName,FMaterialId.FNumber,FMaterialId.FName,FUnitId.FName,FQty,FPrice,FAmount"),
    MigratedQuerySpec("kingdee_query_material_cost", "Query material cost records.", "BD_MaterialCost", "FMaterialId.FNumber,FMaterialId.FName,FUnitId.FName,FStdCost,FLatestCost,FAvgCost"),
    MigratedQuerySpec("kingdee_query_material_target_cost", "Query material target cost bills.", "BD_MatTargetCost", "FBillNo,FDate,FDocumentStatus,FMaterialId.FNumber,FMaterialId.FName,FTargetCost"),
    MigratedQuerySpec("kingdee_query_cost_calculation", "Query cost calculation bills.", "CB_CostCalBill", "FYear,FPeriod,FMaterialId.FNumber,FMaterialId.FName,FCostAmt,FMaterialCost,FLabourCost"),
    MigratedQuerySpec("kingdee_query_cost_centers", "Query cost centers.", "CB_CostCenter", "FNumber,FName,FDeptId.FName,FIsActive"),
    MigratedQuerySpec("kingdee_query_cost_items", "Query cost items.", "CB_CostItem", "FNumber,FName,FCostItemType,FIsActive"),
    MigratedQuerySpec("kingdee_query_product_standard_cost", "Query product standard cost.", "STD_ProductCostQuery", "FMaterialId.FNumber,FMaterialId.FName,FUnitId.FName,FStdCost,FMaterialCost,FLabourCost,FFeeCost"),
    MigratedQuerySpec("kingdee_query_cost_adjustments", "Query cost adjustment bills.", "STK_CostAdjust", "FBillNo,FDate,FDocumentStatus,FCostOrgId.FNumber,FCostOrgId.FName,FAdjustType,FAdjustAmount"),
    MigratedQuerySpec("kingdee_query_instant_cost_compare", "Query instant cost comparison.", "STK_InstantCostCompare", "FMaterialId.FNumber,FMaterialId.FName,FStockId.FName,FInstantCost,FCostPrice,FDiffAmt"),
    MigratedQuerySpec("kingdee_query_cost_trend", "Query cost trend.", "STK_CostTrend", "FMaterialId.FNumber,FMaterialId.FName,FDate,FCostPrice,FPriceChange"),
    MigratedQuerySpec("kingdee_query_finished_product_cost", "Query finished product cost.", "CB_FinishInCostQuery", "FMoBillNo,FMaterialId.FNumber,FMaterialId.FName,FFinishQty,FCostPrice,FCostAmt"),
    MigratedQuerySpec("kingdee_query_material_cost_usage", "Query production material cost usage.", "CB_MaterialCostQuery", "FMoBillNo,FMaterialId.FNumber,FMaterialId.FName,FConsumeQty,FCostPrice,FCostAmt"),
    MigratedQuerySpec("kingdee_query_production_orders", "Query production orders.", "PRD_MO", "FID,FBillNo,FDate,FDocumentStatus,FMaterialId.FNumber,FMaterialId.FName,FQty,FPlanStartDate,FPlanFinishDate,FStatus"),
    MigratedQuerySpec("kingdee_query_production_pick_materials", "Query production picking bills.", "PRD_PickMtrl", "FID,FBillNo,FDate,FDocumentStatus,FMoBillNo,FMaterialId.FNumber,FMaterialId.FName,FPickQty,FStockId.FName"),
    MigratedQuerySpec("kingdee_query_production_stock_in", "Query production stock-in bills.", "PRD_Instock", "FID,FBillNo,FDate,FDocumentStatus,FMoBillNo,FMaterialId.FNumber,FMaterialId.FName,FInQty,FStockId.FName"),
    MigratedQuerySpec("kingdee_query_mrp_result", "Query MRP calculation results.", "PLAN_MRPResult", "FDetailId,FPlanQty,FBillNo,FMaterialId,FUnitId,FPlanDate,FMoBillNo,FPOBillNo,FPRBillNo,FSourceBillType,FSrcBillNo,FSupplyOrgId,FRequireOrgId,FSupplyDate,FDocumentStatus", "FCreateDate DESC", default_limit=200, max_limit=2000, top_style=True),
    MigratedQuerySpec("kingdee_query_production_plan", "Query production plans.", "PLAN_ProductionPlan", "FBillNo,FMaterialId,FMaterialName,FPlanQty,FPlanStartDate,FPlanEndDate,FStatus,FWorkShopId,FDocumentStatus", "FCreateDate DESC", default_limit=200, max_limit=2000, top_style=True),
    MigratedQuerySpec("kingdee_query_production_report", "Query production reports.", "PRD_MOReport", "FBillNo,FMOId,FMOBillNo,FMaterialId,FMaterialName,FReportQty,FUnitId,FFinishedQty,FScrapQty,FHourQty,FWorkStationId,FWorkGroupId,FProcessId,FDocumentStatus,FCreateDate", "FCreateDate DESC", default_limit=200, max_limit=2000, top_style=True),
)

MIGRATED_ENDPOINT_SPECS = (
    MigratedEndpointSpec("kingdee_query_user", "Query Kingdee users.", "user", "BD_User", "FUserID,FName,FNumber,FDepartment.FName,FIsActive"),
    MigratedEndpointSpec("kingdee_query_role", "Query Kingdee roles.", "role", "BD_Role", "FRoleID,FName,FNumber,FIsActive"),
    MigratedEndpointSpec("kingdee_query_sequence", "Query sequence rules.", "sequence", "BOS_SequenceRule", "FSequenceRuleId,FName,FNumber,FObjectType,FDescription"),
    MigratedEndpointSpec("kingdee_query_number_rule", "Query bill number rules.", "number_rule", "BOS_NumberRule", "FNumberRuleId,FName,FNumber,FObjectType,FPrefix,FSequenceLength"),
    MigratedEndpointSpec("kingdee_query_system_config", "Query system configuration records.", "sysconfig", "BOS_SystemConfig", "FConfigId,FConfigKey,FConfigValue,FDescription,FCategory"),
)

MIGRATED_WRITE_TOOL_NAMES = frozenset(
    {
        "kingdee_save_bill",
        "kingdee_submit_bills",
        "kingdee_audit_bills",
        "kingdee_unaudit_bills",
        "kingdee_delete_bills",
        "kingdee_push_bill",
        "kingdee_create_and_audit",
        "kingdee_push_and_audit",
        "kingdee_workflow_approve",
        "kingdee_save_asset",
        "kingdee_push_stock_transfer",
        "kingdee_save_cost_adjustment",
        "kingdee_save_production_order",
        "kingdee_submit_production_orders",
        "kingdee_audit_production_orders",
        "kingdee_push_production_pick",
        "kingdee_push_production_stock_in",
    }
)

MIGRATED_OPS_TOOL_NAMES = frozenset(
    {
        "kingdee_usage_report",
        "kingdee_usage_stats",
        "kingdee_discover_tables",
        "kingdee_discover_columns",
        "kingdee_describe_table",
        "kingdee_discover_metadata_candidates",
    }
)

MIGRATED_READ_TOOL_NAMES = frozenset(spec.name for spec in MIGRATED_QUERY_SPECS) | frozenset(spec.name for spec in MIGRATED_ENDPOINT_SPECS) | frozenset({"kingdee_view_production_order"})
ALL_READ_TOOL_NAMES = CORE_READ_TOOL_NAMES | MIGRATED_READ_TOOL_NAMES
ALL_LIGHTWEIGHT_TOOL_NAMES = ALL_READ_TOOL_NAMES | MIGRATED_WRITE_TOOL_NAMES | MIGRATED_OPS_TOOL_NAMES


def object_prop(description: str = "") -> dict[str, Any]:
    prop: dict[str, Any] = {"type": "object"}
    if description:
        prop["description"] = description
    return prop


def array_prop(description: str = "", default: list[Any] | None = None) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": "array"}
    if description:
        prop["description"] = description
    if default is not None:
        prop["default"] = default
    return prop


def fixed_query_schema(spec: MigratedQuerySpec) -> dict[str, Any]:
    props = {
        "filter_string": string_prop("Kingdee filter string", spec.default_filter),
        "field_keys": string_prop("Comma-separated field keys", spec.field_keys),
        "order_string": string_prop("Order string", spec.order_string),
        "start_row": int_prop("Start row", 0, minimum=0),
        "limit": int_prop("Maximum rows", spec.default_limit, minimum=1, maximum=spec.max_limit),
    }
    if spec.top_style:
        props["top"] = int_prop("Maximum rows, compatible with the top parameter", spec.default_limit, minimum=1, maximum=spec.max_limit)
        props["orderby"] = string_prop("Order string, compatible with the orderby parameter", spec.order_string)
    return object_schema(props)


def endpoint_query_schema(spec: MigratedEndpointSpec) -> dict[str, Any]:
    return object_schema(
        {
            "filter_string": string_prop("Kingdee filter string", spec.default_filter),
            "field_keys": string_prop("Comma-separated field keys", spec.field_keys),
            "start_row": int_prop("Start row", 0, minimum=0),
            "limit": int_prop("Maximum rows", spec.default_limit, minimum=1, maximum=spec.max_limit),
        }
    )


def save_schema(*, default_form_id: str = "", required_form: bool = True) -> dict[str, Any]:
    props = {
        "model": object_prop("Kingdee Model object"),
        "need_update_fields": array_prop("NeedUpDateFields", []),
        "is_delete_entry": bool_prop("Whether to delete entries not included in the model", True),
    }
    required = ["model"]
    if default_form_id or not required_form:
        props["form_id"] = string_prop("Kingdee form id", default_form_id)
    else:
        props["form_id"] = string_prop("Kingdee form id", required=True)
        required.insert(0, "form_id")
    return object_schema(props, required)


def bill_ids_schema(*, default_form_id: str = "", required_form: bool = True) -> dict[str, Any]:
    props = {"bill_ids": array_prop("Kingdee bill FID list")}
    required = ["bill_ids"]
    if default_form_id or not required_form:
        props["form_id"] = string_prop("Kingdee form id", default_form_id)
    else:
        props["form_id"] = string_prop("Kingdee form id", required=True)
        required.insert(0, "form_id")
    return object_schema(props, required)


def push_schema(*, default_form_id: str = "", default_target_form_id: str = "", required_form: bool = True) -> dict[str, Any]:
    props = {
        "source_bill_nos": array_prop("Source bill numbers"),
        "target_form_id": string_prop("Target form id", default_target_form_id),
        "rule_id": string_prop("Convert rule id", ""),
        "entry_ids": string_prop("Optional selected entry ids", ""),
        "custom_params": object_prop("Optional custom push parameters"),
    }
    required = ["source_bill_nos"]
    if not default_target_form_id:
        required.append("target_form_id")
    if default_form_id or not required_form:
        props["form_id"] = string_prop("Source form id", default_form_id)
    else:
        props["form_id"] = string_prop("Source form id", required=True)
        required.insert(0, "form_id")
    return object_schema(props, required)


def workflow_action_schema() -> dict[str, Any]:
    return object_schema(
        {
            "form_id": string_prop("Kingdee form id", required=True),
            "bill_id": string_prop("Bill FID", required=True),
            "action": {"type": "string", "enum": ["approve", "reject"], "default": "approve"},
            "opinion": string_prop("Approval opinion", ""),
        },
        ["form_id", "bill_id"],
    )


def _selected_form_id(args: dict[str, Any], default_form_id: str = "") -> str:
    form_id = str(args.get("form_id") or default_form_id or "").strip()
    if not form_id:
        raise ValueError("form_id is required")
    return form_id


def _result_status(result: Any, op: str) -> dict[str, Any]:
    rs = result.get("Result", result) if isinstance(result, dict) else {}
    status = rs.get("ResponseStatus", {}) if isinstance(rs, dict) else {}
    success = bool(status.get("IsSuccess", True)) if isinstance(status, dict) else True
    out: dict[str, Any] = {"op": op, "success": success, "response_status": status}
    if isinstance(rs, dict):
        fid = rs.get("FID") or rs.get("Id")
        bill_no = rs.get("FBillNo") or rs.get("Number")
        ids = rs.get("Ids") or fid
        if fid:
            out["fid"] = fid
        if bill_no:
            out["bill_no"] = bill_no
        if ids:
            out["ids"] = ids if isinstance(ids, list) else [ids]
    if not success and isinstance(status, dict):
        out["errors"] = status.get("Errors") or status.get("ErrorCode") or status.get("Message")
    return out


def _extract_first_id(status: dict[str, Any]) -> str:
    if status.get("fid"):
        return str(status["fid"])
    ids = status.get("ids") or []
    if ids:
        return str(ids[0])
    return ""


def _save_data(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "Model": args["model"],
        "NeedUpDateFields": args.get("need_update_fields") or [],
        "IsDeleteEntry": "true" if args.get("is_delete_entry", True) else "false",
        "IsVerifyBaseDataField": "false",
        "IsAutoSubmitAndAudit": "false",
        "ValidateRepeatJson": "false",
    }


def _push_data(args: dict[str, Any], target_form_id: str = "") -> dict[str, Any]:
    data: dict[str, Any] = {
        "TargetFormId": args.get("target_form_id") or target_form_id,
        "Numbers": args.get("source_bill_nos") or [],
        "IsEnableDefaultRule": "true",
        "IsDraftWhenSaveFail": "true",
    }
    if args.get("rule_id"):
        data["RuleId"] = args["rule_id"]
    if args.get("entry_ids"):
        data["EntryIds"] = args["entry_ids"]
    if isinstance(args.get("custom_params"), dict):
        data.update(args["custom_params"])
    return data


def _next_action_for_op(op: str) -> str | None:
    if op == "save":
        return "submit"
    if op == "submit":
        return "audit"
    if op == "push":
        return "submit+audit"
    return None


def _make_query_handler(client: KingdeeWebAPIClient, spec: MigratedQuerySpec) -> ToolHandler:
    async def handler(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        limit = args.get("top") if spec.top_style and args.get("top") is not None else args["limit"]
        order = args.get("orderby") if spec.top_style and args.get("orderby") else args["order_string"]
        payload = client.query_payload(spec.form_id, args["field_keys"], args["filter_string"], order, args["start_row"], limit)
        data = rows(await client.post("query", payload, context))
        return {"form_id": spec.form_id, "count": len(data), "has_more": len(data) == limit, "data": data}

    return handler


def _make_endpoint_handler(client: KingdeeWebAPIClient, spec: MigratedEndpointSpec) -> ToolHandler:
    async def handler(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        payload = [spec.form_id, {"FieldKeys": args["field_keys"], "FilterString": args["filter_string"], "StartRow": args["start_row"], "Limit": args["limit"]}]
        data = rows(await client.post(spec.ep_key, payload, context))
        return {"form_id": spec.form_id, "count": len(data), "has_more": len(data) == args["limit"], "data": data}

    return handler


def _make_save_handler(client: KingdeeWebAPIClient, op_name: str, default_form_id: str = "") -> ToolHandler:
    async def handler(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        form_id = _selected_form_id(args, default_form_id)
        result = await client.raw("save", form_id, _save_data(args), context)
        status = _result_status(result, "save")
        status["form_id"] = form_id
        status["next_action"] = _next_action_for_op("save") if status["success"] else None
        status["tool"] = op_name
        return status

    return handler


def _make_ids_handler(client: KingdeeWebAPIClient, ep_key: str, default_form_id: str = "") -> ToolHandler:
    async def handler(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        form_id = _selected_form_id(args, default_form_id)
        succeeded: list[str] = []
        failed: list[dict[str, Any]] = []
        for bill_id in args["bill_ids"]:
            bill_id = str(bill_id).strip()
            if not bill_id:
                continue
            try:
                result = await client.raw(ep_key, form_id, {"Ids": bill_id}, context)
                status = _result_status(result, ep_key)
                if status.get("success"):
                    succeeded.append(bill_id)
                else:
                    failed.append({"id": bill_id, "status": status})
            except Exception as exc:
                failed.append({"id": bill_id, "error": f"{type(exc).__name__}: {exc}"[:300]})
        return {
            "op": ep_key,
            "form_id": form_id,
            "success": not failed,
            "total": len(args["bill_ids"]),
            "succeeded_count": len(succeeded),
            "failed_count": len(failed),
            "succeeded_ids": succeeded,
            "bill_ids": succeeded,
            "failed_details": failed,
            "next_action": _next_action_for_op(ep_key) if succeeded and not failed else None,
        }

    return handler


def _make_push_handler(client: KingdeeWebAPIClient, default_form_id: str = "", default_target_form_id: str = "") -> ToolHandler:
    async def handler(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        form_id = _selected_form_id(args, default_form_id)
        result = await client.raw("push", form_id, _push_data(args, default_target_form_id), context)
        status = _result_status(result, "push")
        status["form_id"] = form_id
        status["target_form_id"] = args.get("target_form_id") or default_target_form_id
        status["source_bill_nos"] = args.get("source_bill_nos") or []
        status["next_action"] = _next_action_for_op("push") if status["success"] else None
        return status

    return handler


def _make_create_and_audit_handler(client: KingdeeWebAPIClient) -> ToolHandler:
    async def handler(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        form_id = _selected_form_id(args)
        save_status = _result_status(await client.raw("save", form_id, _save_data(args), context), "save")
        fid = _extract_first_id(save_status)
        steps: list[dict[str, Any]] = [{"step": "save", "status": save_status}]
        if save_status.get("success") and fid:
            submit_status = _result_status(await client.raw("submit", form_id, {"Ids": fid}, context), "submit")
            steps.append({"step": "submit", "status": submit_status})
            if submit_status.get("success"):
                audit_status = _result_status(await client.raw("audit", form_id, {"Ids": fid}, context), "audit")
                steps.append({"step": "audit", "status": audit_status})
        return {"op": "create_and_audit", "form_id": form_id, "success": all(step["status"].get("success") for step in steps), "fid": fid, "steps": steps}

    return handler


def _make_push_and_audit_handler(client: KingdeeWebAPIClient) -> ToolHandler:
    async def handler(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        form_id = _selected_form_id(args)
        target_form_id = args.get("target_form_id") or ""
        push_status = _result_status(await client.raw("push", form_id, _push_data(args), context), "push")
        steps: list[dict[str, Any]] = [{"step": "push", "status": push_status}]
        target_ids = push_status.get("ids") or []
        for fid in target_ids:
            submit_status = _result_status(await client.raw("submit", target_form_id, {"Ids": str(fid)}, context), "submit")
            steps.append({"step": "submit", "fid": fid, "status": submit_status})
            if submit_status.get("success"):
                audit_status = _result_status(await client.raw("audit", target_form_id, {"Ids": str(fid)}, context), "audit")
                steps.append({"step": "audit", "fid": fid, "status": audit_status})
        return {"op": "push_and_audit", "form_id": form_id, "target_form_id": target_form_id, "success": all(step["status"].get("success") for step in steps), "steps": steps}

    return handler


def _workflow_approve_handler(client: KingdeeWebAPIClient) -> ToolHandler:
    async def handler(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        ep_key = "audit" if args["action"] == "approve" else "unaudit"
        status = _result_status(await client.raw(ep_key, args["form_id"], {"Ids": args["bill_id"]}, context), ep_key)
        status["action"] = args["action"]
        status["opinion"] = args.get("opinion") or ""
        return status

    return handler


def _ops_stub_handler(tool_name: str) -> ToolHandler:
    async def handler(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool_name,
            "operator": context.operator,
            "reason": "This lightweight build does not keep in-process usage logs or open SQL Server probing connections.",
            "migration": "Use structured service logs or add an explicit optional ops module if this capability is required.",
        }

    return handler


def build_migrated_lightweight_tools(client: KingdeeWebAPIClient, *, existing: dict[str, ToolDefinition] | None = None) -> dict[str, ToolDefinition]:
    existing_names = set(existing or {})
    tools: dict[str, ToolDefinition] = {}

    for spec in MIGRATED_QUERY_SPECS:
        if spec.name not in existing_names:
            tools[spec.name] = ToolDefinition(spec.name, spec.description, fixed_query_schema(spec), _make_query_handler(client, spec))

    for spec in MIGRATED_ENDPOINT_SPECS:
        if spec.name not in existing_names:
            tools[spec.name] = ToolDefinition(spec.name, spec.description, endpoint_query_schema(spec), _make_endpoint_handler(client, spec))

    if "kingdee_view_production_order" not in existing_names:
        async def view_production(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
            data = await client.view("PRD_MO", args["bill_id"], context)
            return data if args["mode"] == "full" else simplify_view_result(data)

        tools["kingdee_view_production_order"] = ToolDefinition(
            "kingdee_view_production_order",
            "View a production order by FID.",
            object_schema({"bill_id": string_prop("Production order FID", required=True), "mode": {"type": "string", "enum": ["summary", "full"], "default": "summary"}}, ["bill_id"]),
            view_production,
        )

    write_defs: dict[str, ToolDefinition] = {
        "kingdee_save_bill": ToolDefinition("kingdee_save_bill", "Save a Kingdee bill model.", save_schema(), _make_save_handler(client, "kingdee_save_bill")),
        "kingdee_submit_bills": ToolDefinition("kingdee_submit_bills", "Submit Kingdee bills.", bill_ids_schema(), _make_ids_handler(client, "submit")),
        "kingdee_audit_bills": ToolDefinition("kingdee_audit_bills", "Audit Kingdee bills.", bill_ids_schema(), _make_ids_handler(client, "audit")),
        "kingdee_unaudit_bills": ToolDefinition("kingdee_unaudit_bills", "Unaudit Kingdee bills.", bill_ids_schema(), _make_ids_handler(client, "unaudit")),
        "kingdee_delete_bills": ToolDefinition("kingdee_delete_bills", "Delete Kingdee draft bills.", bill_ids_schema(), _make_ids_handler(client, "delete")),
        "kingdee_push_bill": ToolDefinition("kingdee_push_bill", "Push source bills to a target form.", push_schema(), _make_push_handler(client)),
        "kingdee_create_and_audit": ToolDefinition("kingdee_create_and_audit", "Save, submit, and audit one bill.", save_schema(), _make_create_and_audit_handler(client)),
        "kingdee_push_and_audit": ToolDefinition("kingdee_push_and_audit", "Push source bills and audit generated target bills when ids are returned.", push_schema(), _make_push_and_audit_handler(client)),
        "kingdee_workflow_approve": ToolDefinition("kingdee_workflow_approve", "Approve or reject a bill through the lightweight audit/unaudit mapping.", workflow_action_schema(), _workflow_approve_handler(client)),
        "kingdee_save_asset": ToolDefinition("kingdee_save_asset", "Save a fixed asset card.", save_schema(default_form_id="FA_FAGet", required_form=False), _make_save_handler(client, "kingdee_save_asset", "FA_FAGet")),
        "kingdee_push_stock_transfer": ToolDefinition("kingdee_push_stock_transfer", "Push stock transfer applications to direct transfer bills.", push_schema(default_form_id="STK_TransferApply", default_target_form_id="STK_TransferDirect", required_form=False), _make_push_handler(client, "STK_TransferApply", "STK_TransferDirect")),
        "kingdee_save_cost_adjustment": ToolDefinition("kingdee_save_cost_adjustment", "Save a cost adjustment bill.", save_schema(default_form_id="STK_CostAdjust", required_form=False), _make_save_handler(client, "kingdee_save_cost_adjustment", "STK_CostAdjust")),
        "kingdee_save_production_order": ToolDefinition("kingdee_save_production_order", "Save a production order.", save_schema(default_form_id="PRD_MO", required_form=False), _make_save_handler(client, "kingdee_save_production_order", "PRD_MO")),
        "kingdee_submit_production_orders": ToolDefinition("kingdee_submit_production_orders", "Submit production orders.", bill_ids_schema(default_form_id="PRD_MO", required_form=False), _make_ids_handler(client, "submit", "PRD_MO")),
        "kingdee_audit_production_orders": ToolDefinition("kingdee_audit_production_orders", "Audit production orders.", bill_ids_schema(default_form_id="PRD_MO", required_form=False), _make_ids_handler(client, "audit", "PRD_MO")),
        "kingdee_push_production_pick": ToolDefinition("kingdee_push_production_pick", "Push production orders to picking bills.", push_schema(default_form_id="PRD_MO", default_target_form_id="PRD_PickMtrl", required_form=False), _make_push_handler(client, "PRD_MO", "PRD_PickMtrl")),
        "kingdee_push_production_stock_in": ToolDefinition("kingdee_push_production_stock_in", "Push production picking bills to stock-in bills.", push_schema(default_form_id="PRD_PickMtrl", default_target_form_id="PRD_Instock", required_form=False), _make_push_handler(client, "PRD_PickMtrl", "PRD_Instock")),
    }
    for name, definition in write_defs.items():
        if name not in existing_names:
            tools[name] = definition

    ops_schema = object_schema({"keyword": string_prop("Optional keyword", ""), "limit": int_prop("Maximum rows", 20, minimum=1, maximum=100)})
    for name in MIGRATED_OPS_TOOL_NAMES:
        if name not in existing_names:
            tools[name] = ToolDefinition(name, "Lightweight ops placeholder; SQL probing and usage logs are not enabled in production.", ops_schema, _ops_stub_handler(name))

    return tools
