import httpx

from kingdee_mcp.kingdee_client import KingdeeWebAPIClient


def response(status_code: int, text: str) -> httpx.Response:
    return httpx.Response(status_code, content=text.encode("utf-8"))


def test_detects_kingdee_chinese_session_lost_response():
    resp = response(200, '{"Result":{"ResponseStatus":{"IsSuccess":false,"Errors":[{"Message":"会话信息已丢失，请重新登录"}]}}}')

    assert KingdeeWebAPIClient.is_session_expired_response(resp) is True


def test_detects_english_session_lost_response_and_401():
    assert KingdeeWebAPIClient.is_session_expired_response(response(401, "")) is True
    assert KingdeeWebAPIClient.is_session_expired_response(response(200, "Invalid session, please login again")) is True


def test_non_session_business_response_is_not_expired():
    assert KingdeeWebAPIClient.is_session_expired_response(response(200, '[["row-1"]]')) is False
    assert KingdeeWebAPIClient.is_session_expired_response(response(500, "internal error")) is False
