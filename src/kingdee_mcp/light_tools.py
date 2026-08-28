from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
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
    "SAL_SaleOrder": {"name": "销售订单", "alias": ["销售", "销售订单", "SO"], "desc": "客户销售订单", "fields": "FID,FBillNo,FDate,FDocumentStatus,FCustId.FName,FAllAmount"},
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
        fields = args["field_keys"] if args["field_keys"] != DEFAULT_QUERY_FIELDS else "FID,FBillNo,FDate,FDocumentStatus,FCustId.FName,FAllAmount"
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

    async def subledger(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        start_period = (args["start_year"], args["start_period"])
        end_period = (args["end_year"], args["end_period"])
        if start_period > end_period:
            raise ValueError("start_year/start_period must not be later than end_year/end_period")

        account_book_number = str(args["account_book_number"]).strip()
        if not account_book_number:
            raise ValueError("account_book_number must not be empty")
        start_account_number = str(args["start_account_number"]).strip()
        if not start_account_number:
            raise ValueError("start_account_number must not be empty")
        end_account_number = str(args["end_account_number"]).strip() or start_account_number
        currency_number = str(args["currency_number"]).strip()

        balance_filters = [
            f"FACCOUNTBOOKID.FNumber = {filter_literal(account_book_number)}",
            f"FAccountID.FNumber >= {filter_literal(start_account_number)}",
            f"FAccountID.FNumber <= {filter_literal(end_account_number)}",
        ]
        voucher_filters = [
            f"FAccountBookID.FNumber = {filter_literal(account_book_number)}",
            f"FACCOUNTID.FNumber >= {filter_literal(start_account_number)}",
            f"FACCOUNTID.FNumber <= {filter_literal(end_account_number)}",
            period_range_filter(args["start_year"], args["start_period"], args["end_year"], args["end_period"]),
        ]
        if currency_number:
            balance_filters.append(f"FCurrencyID.FNumber = {filter_literal(currency_number)}")
            voucher_filters.append(f"FCURRENCYID.FNumber = {filter_literal(currency_number)}")
        voucher_filters.append("FInvalid = '0'")
        if args["exclude_adjustment_vouchers"]:
            balance_filters.append("FAdjustPeriod = 0")
            voucher_filters.append("FISADJUSTVOUCHER = 0")
        if not args["include_unposted_vouchers"]:
            voucher_filters.append("FPOSTERID > 0")

        async def query_balance(year: int, period: int) -> tuple[list[dict[str, Any]], bool]:
            period_filter = [*balance_filters, f"FYear = {year}", f"FPeriod = {period}"]
            payload = client.query_payload(
                SUBLEDGER_BALANCE_FORM_ID,
                SUBLEDGER_BALANCE_FIELD_KEYS,
                " AND ".join(period_filter),
                "FAccountID.FNumber ASC,FCurrencyID.FNumber ASC",
                args["balance_start_row"],
                args["balance_limit"] + 1,
            )
            mapped = map_query_rows(rows(await client.post("query", payload, context)), SUBLEDGER_BALANCE_OUTPUT_FIELDS)
            return mapped[: args["balance_limit"]], len(mapped) > args["balance_limit"]

        opening_balances, opening_balances_has_more = await query_balance(args["start_year"], args["start_period"])
        if start_period == end_period:
            closing_balances = opening_balances
            closing_balances_has_more = opening_balances_has_more
        else:
            closing_balances, closing_balances_has_more = await query_balance(args["end_year"], args["end_period"])

        voucher_payload = client.query_payload(
            SUBLEDGER_VOUCHER_FORM_ID,
            SUBLEDGER_VOUCHER_FIELD_KEYS,
            " AND ".join(voucher_filters),
            "FDate ASC,FVOUCHERGROUPNO ASC,FBillNo ASC,FEntity_FEntryID ASC",
            args["start_row"],
            args["limit"] + 1,
        )
        mapped_entries = map_query_rows(
            rows(await client.post("query", voucher_payload, context)),
            SUBLEDGER_VOUCHER_OUTPUT_FIELDS,
        )
        entries = mapped_entries[: args["limit"]]
        return {
            "report_form_id": SUBLEDGER_REPORT_FORM_ID,
            "report_name": "明细分类账",
            "data_sources": [SUBLEDGER_BALANCE_FORM_ID, SUBLEDGER_VOUCHER_FORM_ID],
            "account_book_number": account_book_number,
            "start_period": {"year": args["start_year"], "period": args["start_period"]},
            "end_period": {"year": args["end_year"], "period": args["end_period"]},
            "account_range": {"start": start_account_number, "end": end_account_number},
            "currency_number": currency_number,
            "exclude_adjustment_vouchers": args["exclude_adjustment_vouchers"],
            "include_unposted_vouchers": args["include_unposted_vouchers"],
            "balance_start_row": args["balance_start_row"],
            "balance_limit": args["balance_limit"],
            "opening_balances": opening_balances,
            "opening_balances_has_more": opening_balances_has_more,
            "closing_balances": closing_balances,
            "closing_balances_has_more": closing_balances_has_more,
            "start_row": args["start_row"],
            "count": len(entries),
            "has_more": len(mapped_entries) > args["limit"],
            "entries": entries,
            "note": (
                "GL_BALANCE stores posted accounting balances. When include_unposted_vouchers=true, "
                "the returned voucher entries can include amounts not reflected in opening_balances or closing_balances."
            ),
        }

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
        "kingdee_query_subledger": ToolDefinition("kingdee_query_subledger", "组合查询 GL_BALANCE 科目余额与 GL_VOUCHER 凭证分录，返回明细分类账基础数据；不调用仅支持简单账表的 GetSysReportData。", subledger_schema(), subledger),
        "kingdee_get_fields": ToolDefinition("kingdee_get_fields", "返回表单推荐字段，并尝试读取 QueryBusinessInfo 元数据。", object_schema({"form_id": string_prop("表单编码，例如 BD_Material 或 PUR_PurchaseOrder", required=True)}, ["form_id"]), get_fields),
        "kingdee_query_pending_approvals": ToolDefinition("kingdee_query_pending_approvals", "查询待提交、审核中、已审核或被驳回的单据。", workflow_query_schema(), pending_approvals),
        "kingdee_query_workflow_status": ToolDefinition("kingdee_query_workflow_status", "查询指定单据的审核状态。", workflow_status_schema(), workflow_status),
    }
    tools.update(build_migrated_lightweight_tools(client, existing=tools))
    return tools


DEFAULT_QUERY_FIELDS = "FID,FBillNo,FDate,FDocumentStatus"
STATUS_MAP = {"A": "创建", "B": "审核中", "C": "已审核", "D": "重新审核", "Z": "暂存"}
SUBLEDGER_REPORT_FORM_ID = "GL_RPT_SubLedger"
SUBLEDGER_BALANCE_FORM_ID = "GL_BALANCE"
SUBLEDGER_VOUCHER_FORM_ID = "GL_VOUCHER"
SUBLEDGER_BALANCE_FIELD_KEYS = (
    "FACCOUNTBOOKID.FNumber,FYear,FPeriod,FAccountID.FNumber,FAccountID.FName,"
    "FCurrencyID.FNumber,FCurrencyID.FName,FBeginBalance,FDebit,FCredit,"
    "FYtdDebit,FYtdCredit,FEndBalance,FAdjustPeriod"
)
SUBLEDGER_BALANCE_OUTPUT_FIELDS = (
    "account_book_number",
    "year",
    "period",
    "account_number",
    "account_name",
    "currency_number",
    "currency_name",
    "begin_balance",
    "debit",
    "credit",
    "ytd_debit",
    "ytd_credit",
    "end_balance",
    "adjust_period",
)
SUBLEDGER_VOUCHER_FIELD_KEYS = (
    "FBillNo,FDate,FVOUCHERGROUPID.FName,FVOUCHERGROUPNO,FEXPLANATION,"
    "FACCOUNTID.FNumber,FACCOUNTID.FName,FCURRENCYID.FNumber,FCURRENCYID.FName,"
    "FDEBIT,FCREDIT,FDC,FDocumentStatus,FPOSTERID.FName,FEntity_FEntryID"
)
SUBLEDGER_VOUCHER_OUTPUT_FIELDS = (
    "voucher_number",
    "date",
    "voucher_group",
    "voucher_group_number",
    "explanation",
    "account_number",
    "account_name",
    "currency_number",
    "currency_name",
    "debit",
    "credit",
    "direction",
    "document_status",
    "poster_name",
    "entry_id",
)


def filter_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def period_range_filter(start_year: int, start_period: int, end_year: int, end_period: int) -> str:
    return (
        f"((FYEAR > {start_year}) OR (FYEAR = {start_year} AND FPERIOD >= {start_period})) "
        f"AND ((FYEAR < {end_year}) OR (FYEAR = {end_year} AND FPERIOD <= {end_period}))"
    )


def map_query_rows(data: list[Any], field_names: tuple[str, ...]) -> list[dict[str, Any]]:
    error_message = query_error_message(data)
    if error_message:
        raise RuntimeError(error_message)
    mapped: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, list):
            raise RuntimeError("金蝶 ExecuteBillQuery 返回了无法识别的数据行")
        mapped.append({name: row[index] if index < len(row) else None for index, name in enumerate(field_names)})
    return mapped


def query_error_message(data: list[Any]) -> str:
    if len(data) != 1 or not isinstance(data[0], list) or len(data[0]) != 1:
        return ""
    cell = data[0][0]
    if not isinstance(cell, dict):
        return ""
    result = cell.get("Result")
    if not isinstance(result, dict):
        return ""
    status = result.get("ResponseStatus")
    if not isinstance(status, dict) or status.get("IsSuccess") is not False:
        return ""
    messages = [
        str(error.get("Message") or "").strip()
        for error in status.get("Errors") or []
        if isinstance(error, dict) and str(error.get("Message") or "").strip()
    ]
    return "; ".join(messages) or str(status.get("Message") or "金蝶 ExecuteBillQuery 查询失败")


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


def subledger_schema() -> dict[str, Any]:
    year_prop = {
        "type": "integer",
        "minimum": 2000,
        "maximum": 9999,
        "description": "会计年度",
    }
    return object_schema(
        {
            "start_year": year_prop,
            "start_period": int_prop("开始期间；当前组合查询仅支持普通期间 1-12", 1, minimum=1, maximum=12),
            "end_year": year_prop,
            "end_period": int_prop("结束期间；当前组合查询仅支持普通期间 1-12", 1, minimum=1, maximum=12),
            "account_book_number": string_prop("账簿编码，对应 FACCTBOOKID.FNumber，例如 001", required=True),
            "start_account_number": string_prop("起始科目编码，例如 1001", required=True),
            "end_account_number": string_prop("结束科目编码；留空时等于起始科目", ""),
            "currency_number": string_prop("币别编码；留空时返回所有币别，当前账套人民币为 PRE001", ""),
            "exclude_adjustment_vouchers": bool_prop("是否排除调整期间余额和凭证", True),
            "include_unposted_vouchers": bool_prop("是否包含未过账凭证", False),
            "balance_start_row": int_prop("期初和期末余额的起始行号", 0, minimum=0),
            "balance_limit": int_prop("期初和期末余额每页返回条数", 100, minimum=1, maximum=100),
            "start_row": int_prop("起始行号", 0, minimum=0),
            "limit": int_prop("返回条数；轻量网关为控制响应体积最多返回 100 行", 20, minimum=1, maximum=100),
        },
        ["start_year", "end_year", "account_book_number", "start_account_number"],
    )


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
    MigratedQuerySpec("kingdee_query_sale_quotations", "Query sales quotations.", "SAL_Quotation", "FID,FBillNo,FDate,FDocumentStatus,FCustId.FName,FAllAmount"),
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

MATERIAL_IMAGE_TOOL_NAME = "kingdee_material_image"
MIGRATED_READ_TOOL_NAMES = frozenset(spec.name for spec in MIGRATED_QUERY_SPECS) | frozenset(spec.name for spec in MIGRATED_ENDPOINT_SPECS) | frozenset({"kingdee_view_production_order", MATERIAL_IMAGE_TOOL_NAME})
EXPERIMENTAL_READ_TOOL_NAMES = frozenset({"kingdee_query_subledger"})
ALL_READ_TOOL_NAMES = CORE_READ_TOOL_NAMES | MIGRATED_READ_TOOL_NAMES | EXPERIMENTAL_READ_TOOL_NAMES
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


def material_image_schema() -> dict[str, Any]:
    return object_schema(
        {
            "action": {"type": "string", "enum": ["upload", "download"]},
            "material_id": int_prop("物料 FMaterialId，仅允许操作明确指定的物料", minimum=1),
            "image_base64": string_prop("上传时必填，PNG/JPEG 的纯 Base64 或 data URL", ""),
        },
        ["action", "material_id"],
    )


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


_MATERIAL_IMAGE_WRITE_SCOPES = frozenset({"write", "all", "high", "*"})
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_DATA_URL_PATTERN = re.compile(r"^data:(image/(?:png|jpeg));base64,(.*)$", re.IGNORECASE | re.DOTALL)


def _material_image_limit_bytes() -> int:
    raw = os.getenv("MCP_MATERIAL_IMAGE_MAX_BYTES", "5242880").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("MCP_MATERIAL_IMAGE_MAX_BYTES must be an integer") from exc
    if value < 1:
        raise ValueError("MCP_MATERIAL_IMAGE_MAX_BYTES must be >= 1")
    return value


def _decode_material_image(image_base64: str, *, enforce_limit: bool) -> dict[str, Any]:
    raw_value = str(image_base64 or "").strip()
    if not raw_value:
        raise ValueError("image_base64 is required for upload")

    declared_mime = ""
    match = _DATA_URL_PATTERN.fullmatch(raw_value)
    if match:
        declared_mime = match.group(1).lower()
        raw_value = match.group(2).strip()
    raw_value = "".join(raw_value.split())

    try:
        image_bytes = base64.b64decode(raw_value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image_base64 must be valid Base64") from exc

    if image_bytes.startswith(_PNG_SIGNATURE):
        mime_type = "image/png"
        extension = "png"
    elif image_bytes.startswith(_JPEG_SIGNATURE):
        mime_type = "image/jpeg"
        extension = "jpg"
    else:
        raise ValueError("material image must be PNG or JPEG")
    if declared_mime and declared_mime != mime_type:
        raise ValueError("data URL MIME type does not match image content")
    if enforce_limit:
        maximum = _material_image_limit_bytes()
        if len(image_bytes) > maximum:
            raise ValueError(f"material image exceeds maximum size of {maximum} bytes")

    return {
        "image_base64": raw_value,
        "image_bytes": image_bytes,
        "mime_type": mime_type,
        "extension": extension,
        "byte_size": len(image_bytes),
        "sha256": hashlib.sha256(image_bytes).hexdigest(),
    }


def _material_image_view_model(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    result = payload.get("Result", payload)
    if isinstance(result, dict):
        nested = result.get("Result", result)
        return nested if isinstance(nested, dict) else {}
    return {}


async def _material_image_record(
    client: KingdeeWebAPIClient,
    material_id: int,
    context: OperatorContext,
) -> dict[str, Any]:
    payload = client.query_payload(
        "BD_Material",
        "FMaterialId,FNumber,FName,FDocumentStatus",
        f"FMaterialId = {material_id}",
        "FMaterialId DESC",
        0,
        1,
    )
    data = map_query_rows(
        rows(await client.post("query", payload, context)),
        ("material_id", "material_number", "material_name", "document_status"),
    )
    if not data:
        raise ValueError(f"material not found: {material_id}")
    record = data[0]
    record["material_id"] = int(record["material_id"])
    record["material_number"] = str(record.get("material_number") or "").strip()
    record["material_name"] = str(record.get("material_name") or "").strip()
    record["document_status"] = str(record.get("document_status") or "").strip()
    return record


def _material_image_filename(record: dict[str, Any], extension: str) -> str:
    source = record.get("material_number") or f"material-{record['material_id']}"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(source)).strip("._")
    return f"{safe or record['material_id']}.{extension}"


def _make_material_image_handler(client: KingdeeWebAPIClient) -> ToolHandler:
    async def handler(args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        action = str(args.get("action") or "").strip().lower()
        if action not in {"upload", "download"}:
            raise ValueError("action must be upload or download")
        material_id = int(args["material_id"])
        if action == "upload" and not context.allowed_tools.intersection(_MATERIAL_IMAGE_WRITE_SCOPES):
            raise PermissionError("material image upload requires write permission")
        record = await _material_image_record(client, material_id, context)

        if action == "download":
            view_model = _material_image_view_model(await client.view("BD_Material", str(material_id), context))
            image_value = str(view_model.get("Image") or "").strip()
            if not image_value:
                raise FileNotFoundError(f"material has no database image: {material_id}")
            image = _decode_material_image(image_value, enforce_limit=False)
            return {
                "success": True,
                "action": action,
                **record,
                "storage_type": "database",
                "mime_type": image["mime_type"],
                "byte_size": image["byte_size"],
                "sha256": image["sha256"],
                "suggested_filename": _material_image_filename(record, image["extension"]),
                "image_base64": image["image_base64"],
            }

        if record["document_status"] != "A":
            raise PermissionError("material image upload is allowed only for an unreviewed material with DocumentStatus A")
        image = _decode_material_image(args.get("image_base64") or "", enforce_limit=True)
        save_data = {
            "Model": {"FMaterialId": material_id, "FIMAGE1": image["image_base64"]},
            "NeedUpDateFields": ["FIMAGE1"],
            "IsDeleteEntry": "false",
            "IsVerifyBaseDataField": "false",
            "IsAutoSubmitAndAudit": "false",
            "ValidateRepeatJson": "false",
        }
        save_status = _result_status(await client.raw("save", "BD_Material", save_data, context), "save")
        if not save_status.get("success"):
            raise RuntimeError(f"Kingdee material image save failed: {save_status.get('errors') or save_status.get('response_status')}")

        view_model = _material_image_view_model(await client.view("BD_Material", str(material_id), context))
        saved_image = _decode_material_image(str(view_model.get("Image") or ""), enforce_limit=False)
        verified = saved_image["sha256"] == image["sha256"] and saved_image["byte_size"] == image["byte_size"]
        if not verified:
            raise RuntimeError("Kingdee material image round-trip verification failed")
        return {
            "success": True,
            "action": action,
            **record,
            "storage_type": "database",
            "mime_type": image["mime_type"],
            "byte_size": image["byte_size"],
            "sha256": image["sha256"],
            "verified": True,
        }

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

    if MATERIAL_IMAGE_TOOL_NAME not in existing_names:
        tools[MATERIAL_IMAGE_TOOL_NAME] = ToolDefinition(
            MATERIAL_IMAGE_TOOL_NAME,
            "上传或下载物料数据库图片；上传仅允许未审核物料并要求 write 权限。",
            material_image_schema(),
            _make_material_image_handler(client),
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
