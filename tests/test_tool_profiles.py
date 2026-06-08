from kingdee_mcp.light_tools import (
    ALL_LIGHTWEIGHT_TOOL_NAMES,
    ALL_READ_TOOL_NAMES,
    CORE_READ_TOOL_NAMES,
    MIGRATED_OPS_TOOL_NAMES,
    MIGRATED_WRITE_TOOL_NAMES,
)
from kingdee_mcp.mcp_lite import tool_allowed


def _visible(scopes: set[str]) -> set[str]:
    allowed = frozenset(scopes)
    return {name for name in ALL_LIGHTWEIGHT_TOOL_NAMES if tool_allowed(name, allowed)}


def test_read_scope_exposes_only_core_read_tools():
    names = _visible({"read"})

    assert names == CORE_READ_TOOL_NAMES
    assert len(names) == 14
    assert "kingdee_smoke_test" in names
    assert "kingdee_save_bill" not in names
    assert "kingdee_query_operation_logs" not in names


def test_full_read_scope_exposes_migrated_read_tools_without_write_or_ops():
    names = _visible({"full-read"})

    assert names == ALL_READ_TOOL_NAMES
    assert "kingdee_query_production_orders" in names
    assert "kingdee_query_operation_logs" in names
    assert "kingdee_save_bill" not in names
    assert "kingdee_usage_stats" not in names


def test_write_scope_exposes_read_and_write_tools_without_ops():
    names = _visible({"write"})

    assert names == ALL_READ_TOOL_NAMES | MIGRATED_WRITE_TOOL_NAMES
    assert "kingdee_save_bill" in names
    assert "kingdee_delete_bills" in names
    assert "kingdee_usage_stats" not in names


def test_ops_scope_exposes_only_lightweight_ops_placeholders():
    names = _visible({"ops"})

    assert names == MIGRATED_OPS_TOOL_NAMES
    assert "kingdee_usage_stats" in names
    assert "kingdee_query_inventory" not in names


def test_all_scope_exposes_complete_lightweight_catalog():
    assert _visible({"all"}) == ALL_LIGHTWEIGHT_TOOL_NAMES
