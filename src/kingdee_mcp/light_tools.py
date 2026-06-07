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
    "PUR_PurchaseOrder": {"name": "????", "alias": ["??", "????", "PO"], "desc": "???????", "fields": "FID,FBillNo,FDate,FDocumentStatus,FSupplierId.FName,FPurchaseDeptId.FName,FTaxAmount,FAllAmount,FReceiveQty,FStockInQty"},
    "SAL_SaleOrder": {"name": "????", "alias": ["??", "????", "SO"], "desc": "???????", "fields": "FID,FBillNo,FDate,FDocumentStatus,FCustId.FName,FTotalAmount"},
    "STK_InStock": {"name": "?????", "alias": ["??", "????"], "desc": "?????????", "fields": "FID,FBillNo,FDate,FDocumentStatus,FStockOrgId.FName"},
    "SAL_OUTSTOCK": {"name": "?????", "alias": ["??", "????"], "desc": "?????????", "fields": "FID,FBillNo,FDate,FDocumentStatus,FStockOrgId.FName"},
    "STK_MisDelivery": {"name": "?????", "alias": ["????", "??"], "desc": "?????????", "fields": "FID,FBillNo,FDate,FDocumentStatus,FStockOrgId.FName"},
    "STK_Miscellaneous": {"name": "?????", "alias": ["????", "??"], "desc": "?????????", "fields": "FID,FBillNo,FDate,FDocumentStatus,FStockOrgId.FName"},
    "STK_TransferDirect": {"name": "?????", "alias": ["??", "????"], "desc": "???????", "fields": "FID,FBillNo,FDate,FDocumentStatus,FStockOutId.FName,FStockInId.FName"},
    "STK_Inventory": {"name": "????", "alias": ["??", "????", "???"], "desc": "???????", "fields": "FMaterialId.FNumber,FMaterialId.FName,FStockId.FName,FBaseQty,FBaseUnitId.FName"},
    "BD_Material": {"name": "??", "alias": ["??", "??", "SKU"], "desc": "???????", "fields": "FMaterialId,FNumber,FName,FSpecification,FMaterialGroup.FName"},
    "BD_Customer": {"name": "??", "alias": ["??"], "desc": "???????", "fields": "FNumber,FName,FShortName,FContact,FPhone,FDocumentStatus"},
    "BD_Supplier": {"name": "???", "alias": ["???"], "desc": "????????", "fields": "FNumber,FName,FShortName,FContact,FPhone,FDocumentStatus"},
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
        return {"tip": "FReceiveQty=???????FStockInQty=??????", "count": len(data), "has_more": len(data) == args["limit"], "data": data}

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
            "name": info.get("name", "????"),
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
        return {"form_id": args["form_id"], "bill_id": args["bill_id"], "document_status": status, "status_name": STATUS_MAP.get(status, "??"), "bill_no": bill_data.get("FBillNo", "") if isinstance(bill_data, dict) else "", "bill_data": bill_data}

    return {
        "kingdee_smoke_test": ToolDefinition("kingdee_smoke_test", "Check MCP auth, mapped Kingdee user login, service limits, and optional tiny read-only query.", smoke_schema(), smoke),
        "kingdee_query_bills": ToolDefinition("kingdee_query_bills", "?????????????????????????", query_schema(required_form=True), query_bills),
        "kingdee_view_bill": ToolDefinition("kingdee_view_bill", "?????? FID ???????", view_schema(), view_bill),
        "kingdee_query_purchase_orders": ToolDefinition("kingdee_query_purchase_orders", "?????????", query_schema(required_form=False), purchase_orders),
        "kingdee_query_purchase_order_progress": ToolDefinition("kingdee_query_purchase_order_progress", "???????????????", purchase_progress_schema(), purchase_progress),
        "kingdee_query_sale_orders": ToolDefinition("kingdee_query_sale_orders", "?????????", query_schema(required_form=False), sale_orders),
        "kingdee_query_stock_bills": ToolDefinition("kingdee_query_stock_bills", "??????????", query_schema(required_form=True), stock_bills),
        "kingdee_query_inventory": ToolDefinition("kingdee_query_inventory", "??????????????????", inventory_schema(), inventory),
        "kingdee_query_materials": ToolDefinition("kingdee_query_materials", "?????????", materials_schema(), materials),
        "kingdee_query_partners": ToolDefinition("kingdee_query_partners", "?????????????", partners_schema(), partners),
        "kingdee_list_forms": ToolDefinition("kingdee_list_forms", "??????????????", object_schema({"keyword": string_prop("??????????????", "")}), list_forms),
        "kingdee_get_fields": ToolDefinition("kingdee_get_fields", "???????????? QueryBusinessInfo ??????", object_schema({"form_id": string_prop("?????? BD_Material?PUR_PurchaseOrder", required=True)}, ["form_id"]), get_fields),
        "kingdee_query_pending_approvals": ToolDefinition("kingdee_query_pending_approvals", "???????/???/??????????", workflow_query_schema(), pending_approvals),
        "kingdee_query_workflow_status": ToolDefinition("kingdee_query_workflow_status", "??????????????", workflow_status_schema(), workflow_status),
    }


DEFAULT_QUERY_FIELDS = "FID,FBillNo,FDate,FDocumentStatus"
STATUS_MAP = {"A": "??", "B": "???", "C": "???", "D": "????", "Z": "??"}


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
        "form_id": string_prop("??????", "" if not required_form else None, required=required_form),
        "filter_string": string_prop("????", ""),
        "field_keys": string_prop("?????????", DEFAULT_QUERY_FIELDS),
        "order_string": string_prop("????", "FID DESC"),
        "start_row": int_prop("?????", 0, minimum=0),
        "limit": int_prop("????", 20, minimum=1, maximum=100),
    }
    return object_schema(props, ["form_id"] if required_form else [])


def smoke_schema() -> dict[str, Any]:
    return object_schema(
        {
            "run_query": bool_prop("?????????????", True),
            "form_id": string_prop("??????", "STK_Inventory"),
            "field_keys": string_prop("??????", "FMaterialId.FNumber,FMaterialId.FName,FStockId.FName,FBaseQty"),
            "filter_string": string_prop("??????", "FBaseQty > 0"),
            "limit": int_prop("????????", 1, minimum=1, maximum=5),
        }
    )


def view_schema() -> dict[str, Any]:
    return object_schema({"form_id": string_prop("??????", required=True), "bill_id": string_prop("???? FID", required=True), "mode": {"type": "string", "enum": ["summary", "full"], "default": "summary"}}, ["form_id", "bill_id"])


def purchase_progress_schema() -> dict[str, Any]:
    return object_schema({"filter_string": string_prop("????", "FDocumentStatus='C'"), "start_row": int_prop(default=0), "limit": int_prop(default=20, minimum=1, maximum=100)})


def inventory_schema() -> dict[str, Any]:
    return object_schema({"filter_string": string_prop("????", "FBaseQty>0"), "field_keys": string_prop("????", "FMaterialId.FNumber,FMaterialId.FName,FStockId.FName,FBaseQty,FBaseUnitId.FName"), "start_row": int_prop(default=0), "limit": int_prop(default=20, minimum=1, maximum=100)})


def materials_schema() -> dict[str, Any]:
    return object_schema({"filter_string": string_prop("????", ""), "field_keys": string_prop("????", "FMaterialId,FNumber,FName,FSpecification,FMaterialGroup.FName"), "start_row": int_prop(default=0), "limit": int_prop(default=20, minimum=1, maximum=100)})


def partners_schema() -> dict[str, Any]:
    return object_schema({"partner_type": {"type": "string", "enum": ["BD_Customer", "BD_Supplier"]}, "filter_string": string_prop("????", ""), "field_keys": string_prop("????", "FNumber,FName,FShortName,FContact,FPhone,FDocumentStatus"), "start_row": int_prop(default=0), "limit": int_prop(default=20, minimum=1, maximum=100)}, ["partner_type"])


def workflow_query_schema() -> dict[str, Any]:
    return object_schema({"form_id": string_prop("?????????????", ""), "status": {"type": "string", "enum": ["pending", "approved", "rejected", "all"], "default": "pending"}, "limit": int_prop(default=20, minimum=1, maximum=100)})


def workflow_status_schema() -> dict[str, Any]:
    return object_schema({"form_id": string_prop("????", required=True), "bill_id": string_prop("???? FID", required=True)}, ["form_id", "bill_id"])
