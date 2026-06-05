import pytest
import respx
import httpx
from taiga_mcp.auth import fetch_token

TAIGA_URL = "https://api.taiga.io/api/v1"


@respx.mock
async def test_fetch_token_returns_auth_token():
    respx.post(f"{TAIGA_URL}/auth").mock(
        return_value=httpx.Response(200, json={"auth_token": "test-token-123"})
    )
    token = await fetch_token(TAIGA_URL, "user", "pass")
    assert token == "test-token-123"


@respx.mock
async def test_fetch_token_raises_on_bad_credentials():
    respx.post(f"{TAIGA_URL}/auth").mock(
        return_value=httpx.Response(400, json={"_error_message": "Invalid credentials"})
    )
    with pytest.raises(RuntimeError, match="Authentication failed"):
        await fetch_token(TAIGA_URL, "user", "wrong")
