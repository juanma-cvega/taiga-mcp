import pytest
import respx
import httpx
from taiga_mcp.auth import authenticate

TAIGA_URL = "https://api.taiga.io/api/v1"


@respx.mock
async def test_authenticate_returns_token_and_user_id():
    respx.post(f"{TAIGA_URL}/auth").mock(
        return_value=httpx.Response(
            200, json={"auth_token": "test-token-123", "id": 42}
        )
    )
    token, user_id = await authenticate(TAIGA_URL, "user", "pass")
    assert token == "test-token-123"
    assert user_id == 42


@respx.mock
async def test_authenticate_raises_on_bad_credentials():
    respx.post(f"{TAIGA_URL}/auth").mock(
        return_value=httpx.Response(400, json={"_error_message": "Invalid credentials"})
    )
    with pytest.raises(RuntimeError, match="Authentication failed"):
        await authenticate(TAIGA_URL, "user", "wrong")
