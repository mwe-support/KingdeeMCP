from __future__ import annotations

import base64

import pytest

from kingdee_mcp.auth import OperatorContext
from kingdee_mcp.light_tools import build_migrated_lightweight_tools


PNG_BYTES = b"\x89PNG\r\n\x1a\nkingdee-mcp-image-test"
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode("ascii")


class FakeMaterialImageClient:
    def __init__(self, *, status: str = "A", image_base64: str = PNG_BASE64) -> None:
        self.status = status
        self.image_base64 = image_base64
        self.posts: list[tuple[str, dict, str]] = []
        self.raw_calls: list[tuple[str, str, dict, str]] = []
        self.views: list[tuple[str, str, str]] = []

    @staticmethod
    def query_payload(form_id, field_keys, filter_string="", order_string="FID DESC", start_row=0, limit=20):
        return {
            "FormId": form_id,
            "FieldKeys": field_keys,
            "FilterString": filter_string,
            "OrderString": order_string,
            "StartRow": start_row,
            "Limit": limit,
        }

    async def post(self, ep_key, payload, context):
        self.posts.append((ep_key, payload, context.kingdee_username))
        return [[13007759, "MCPIMGAPI2026082801", "MCP图片接口组合测试物料", self.status]]

    async def raw(self, ep_key, form_id, data_obj, context):
        self.raw_calls.append((ep_key, form_id, data_obj, context.kingdee_username))
        self.image_base64 = data_obj["Model"]["FIMAGE1"]
        return {
            "Result": {
                "ResponseStatus": {
                    "IsSuccess": True,
                    "Errors": [],
                    "SuccessEntitys": [{"Id": 13007759, "Number": "MCPIMGAPI2026082801"}],
                }
            }
        }

    async def view(self, form_id, bill_id, context):
        self.views.append((form_id, bill_id, context.kingdee_username))
        return {
            "Result": {
                "Result": {
                    "FMaterialId": 13007759,
                    "Number": "MCPIMGAPI2026082801",
                    "Name": "MCP图片接口组合测试物料",
                    "DocumentStatus": self.status,
                    "Image": self.image_base64,
                    "ImageFileServer": " ",
                    "ImgStorageType": "A",
                }
            }
        }


def context(*scopes: str) -> OperatorContext:
    return OperatorContext(
        operator="tester",
        kingdee_username="integration-test",
        allowed_tools=frozenset(scopes),
    )


def handler(client: FakeMaterialImageClient):
    tools = build_migrated_lightweight_tools(client)  # type: ignore[arg-type]
    return tools["kingdee_material_image"].handler


def image_args(action: str, image_base64: str = "") -> dict:
    return {
        "action": action,
        "material_id": 13007759,
        "image_base64": image_base64,
    }


@pytest.mark.asyncio
async def test_download_returns_only_verified_database_image() -> None:
    client = FakeMaterialImageClient()

    result = await handler(client)(image_args("download"), context("full-read"))

    assert result["success"] is True
    assert result["action"] == "download"
    assert result["material_id"] == 13007759
    assert result["material_number"] == "MCPIMGAPI2026082801"
    assert result["document_status"] == "A"
    assert result["mime_type"] == "image/png"
    assert result["byte_size"] == len(PNG_BYTES)
    assert result["image_base64"] == PNG_BASE64
    assert result["suggested_filename"] == "MCPIMGAPI2026082801.png"
    assert len(result["sha256"]) == 64
    assert client.raw_calls == []


@pytest.mark.asyncio
async def test_upload_uses_fimage1_and_verifies_round_trip() -> None:
    client = FakeMaterialImageClient(image_base64="")

    result = await handler(client)(image_args("upload", PNG_BASE64), context("write"))

    assert result["success"] is True
    assert result["action"] == "upload"
    assert result["verified"] is True
    assert result["byte_size"] == len(PNG_BYTES)
    assert "image_base64" not in result
    assert len(client.raw_calls) == 1
    ep_key, form_id, data_obj, username = client.raw_calls[0]
    assert ep_key == "save"
    assert form_id == "BD_Material"
    assert username == "integration-test"
    assert data_obj["Model"] == {"FMaterialId": 13007759, "FIMAGE1": PNG_BASE64}
    assert data_obj["NeedUpDateFields"] == ["FIMAGE1"]
    assert data_obj["IsDeleteEntry"] == "false"


@pytest.mark.asyncio
async def test_upload_rejects_read_scope_before_save() -> None:
    client = FakeMaterialImageClient()

    with pytest.raises(PermissionError, match="write permission"):
        await handler(client)(image_args("upload", PNG_BASE64), context("full-read"))

    assert client.posts == []
    assert client.raw_calls == []


@pytest.mark.asyncio
async def test_upload_rejects_audited_material_before_save() -> None:
    client = FakeMaterialImageClient(status="C")

    with pytest.raises(PermissionError, match="unreviewed material"):
        await handler(client)(image_args("upload", PNG_BASE64), context("write"))

    assert client.raw_calls == []


@pytest.mark.asyncio
async def test_upload_rejects_invalid_image() -> None:
    client = FakeMaterialImageClient()
    invalid = base64.b64encode(b"not-an-image").decode("ascii")

    with pytest.raises(ValueError, match="PNG or JPEG"):
        await handler(client)(image_args("upload", invalid), context("write"))

    assert client.raw_calls == []


@pytest.mark.asyncio
async def test_upload_default_limit_allows_image_larger_than_two_mib(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_MATERIAL_IMAGE_MAX_BYTES", raising=False)
    image_bytes = b"\x89PNG\r\n\x1a\n" + (b"x" * (2 * 1024 * 1024))
    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    client = FakeMaterialImageClient(image_base64="")

    result = await handler(client)(image_args("upload", image_base64), context("write"))

    assert result["verified"] is True
    assert result["byte_size"] == len(image_bytes)


@pytest.mark.asyncio
async def test_upload_rejects_image_above_configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeMaterialImageClient()
    monkeypatch.setenv("MCP_MATERIAL_IMAGE_MAX_BYTES", "8")

    with pytest.raises(ValueError, match="exceeds maximum"):
        await handler(client)(image_args("upload", PNG_BASE64), context("write"))

    assert client.raw_calls == []


def test_material_image_schema_uses_one_action_based_tool() -> None:
    client = FakeMaterialImageClient()
    tool = build_migrated_lightweight_tools(client)["kingdee_material_image"]  # type: ignore[arg-type]

    assert tool.input_schema["properties"]["action"]["enum"] == ["upload", "download"]
    assert tool.input_schema["required"] == ["action", "material_id"]
