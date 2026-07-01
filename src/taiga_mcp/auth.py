import httpx


async def authenticate(
    base_url: str, username: str, password: str
) -> tuple[str, int]:
    """Authenticate against Taiga, returning (auth_token, user_id).

    The user id is needed to scope project queries to the authenticated
    user — an unfiltered /projects returns every public project on the
    platform.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/auth",
            json={"type": "normal", "username": username, "password": password},
        )
    if response.status_code != 200:
        raise RuntimeError(f"Authentication failed: {response.text}")
    payload = response.json()
    return payload["auth_token"], payload["id"]
