from kingdee_mcp import server


def _all_tools():
    return server._original_tool_manager_list_tools()


def test_read_scope_exposes_only_core_read_tools():
    names = {
        tool.name
        for tool in server._filter_tools_for_scopes(_all_tools(), frozenset({"read"}))
    }

    assert names == server._CORE_READ_TOOLS
    assert len(names) == 14
    assert "kingdee_smoke_test" in names
    assert "kingdee_delete_bills" not in names
    assert "kingdee_query_operation_logs" not in names


def test_write_and_core_scopes_expose_curated_core_tools():
    all_tools = _all_tools()
    write_names = {
        tool.name
        for tool in server._filter_tools_for_scopes(all_tools, frozenset({"write"}))
    }
    core_names = {
        tool.name
        for tool in server._filter_tools_for_scopes(all_tools, frozenset({"core"}))
    }

    assert write_names == server._CORE_TOOLS
    assert core_names == server._CORE_TOOLS
    assert len(write_names) == 20
    assert "kingdee_save_bill" in write_names
    assert "kingdee_unaudit_bills" not in write_names
    assert "kingdee_push_and_audit" not in write_names
    assert "kingdee_delete_bills" not in write_names


def test_high_scope_exposes_full_catalog():
    all_tools = _all_tools()
    high_names = {
        tool.name
        for tool in server._filter_tools_for_scopes(all_tools, frozenset({"high"}))
    }

    assert high_names == {tool.name for tool in all_tools}
    assert len(high_names) > len(server._CORE_TOOLS)


def test_tool_manager_list_tools_uses_current_scope(monkeypatch):
    monkeypatch.setattr(server, "_current_allowed_tool_scopes", lambda: frozenset({"read"}))

    names = {tool.name for tool in server.mcp._tool_manager.list_tools()}

    assert names == server._CORE_READ_TOOLS
