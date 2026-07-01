"""Manual smoke test against a real Taiga account.

Run with:  uv run python scripts/smoke_test.py
Reads credentials from .env (TAIGA_URL / TAIGA_USERNAME / TAIGA_PASSWORD).
"""

import asyncio

from taiga_mcp import server


async def main() -> None:
    await server.init()  # loads .env, fetches auth token, builds client

    print("== list_projects ==")
    print(await server.list_projects())

    # Grab the first project id to exercise the other tools.
    projects = await server._get_client().list_projects()
    if not projects:
        print("\nNo projects on this account — nothing else to test.")
        return

    pid = projects[0].id
    print(f"\n== get_current_sprint (project {pid}) ==")
    print(await server.get_current_sprint(project_id=pid))

    print(f"\n== list_user_stories (project {pid}) ==")
    print(await server.list_user_stories(project_id=pid))

    print(f"\n== list_tasks (project {pid}) ==")
    print(await server.list_tasks(project_id=pid))


if __name__ == "__main__":
    asyncio.run(main())
