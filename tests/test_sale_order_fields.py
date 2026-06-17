from kingdee_mcp.light_tools import FORM_CATALOG


def test_sale_order_catalog_uses_existing_amount_field():
    fields = FORM_CATALOG["SAL_SaleOrder"]["fields"]

    assert "FAllAmount" in fields
    assert "FTotalAmount" not in fields
