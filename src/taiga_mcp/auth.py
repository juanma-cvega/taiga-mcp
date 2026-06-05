import httpx


async def fetch_token(base_url: str, username: str, password: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/auth",
            json={"type": "normal", "username": username, "password": password},
        )
    if response.status_code != 200:
        raise RuntimeError(f"Authentication failed: {response.text}")
    return response.json()["auth_token"]
