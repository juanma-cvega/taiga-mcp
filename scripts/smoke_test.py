"""Manual smoke test against a real Taiga account.

Run with:  uv run python scripts/smoke_test.py
Reads credentials from .env (TAIGA_URL / TAIGA_USERNAME / TAIGA_PASSWORD).

By default this is READ-ONLY: it lists projects and exercises the read tools
against your first project without mutating anything.

To exercise the full create/get/update lifecycle, point it at a dedicated
throwaway project via TAIGA_SMOKE_PROJECT_SLUG (create the project once in
Taiga first — this tool cannot create projects). When set, the run creates an
epic and a linked story in that project, updates them, and reads them back.

    TAIGA_SMOKE_PROJECT_SLUG=your-smoke-project uv run python scripts/smoke_test.py

Note: the client has no delete operation, so each full run leaves a new
(timestamped) epic + story behind in the smoke project.
"""

import asyncio
import os
from datetime import datetime, timezone

from taiga_mcp import server


async def read_only_checks(pid: int) -> None:
    """Exercise the non-mutating tools against project `pid`."""
    print(f"\n== get_current_sprint (project {pid}) ==")
    print(await server.get_current_sprint(project_id=pid))

    print(f"\n== list_epics (project {pid}) ==")
    print(await server.list_epics(project_id=pid))

    print(f"\n== list_user_stories (project {pid}) ==")
    print(await server.list_user_stories(project_id=pid))

    print(f"\n== list_tasks (project {pid}) ==")
    print(await server.list_tasks(project_id=pid))


async def write_lifecycle(pid: int) -> None:
    """Exercise create/get/update for epics and stories in the smoke project.

    Uses the client directly to capture the created objects' ids, then drives
    the MCP tools (server.*) for get/update so both layers are exercised.
    """
    client = server._get_client()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"\n== create_epic (project {pid}) ==")
    epic = await client.create_epic(
        project_id=pid,
        subject=f"[smoke {stamp}] epic",
        description="Created by smoke_test.py",
    )
    print(f"created epic #{epic.ref} (id {epic.id})")

    print("\n== get_epic ==")
    print(await server.get_epic(epic_id=epic.id))

    # Exercise status name->id resolution using a real status from this project.
    epic_statuses = await client._get("/epic-statuses", params={"project": pid})
    epic_status = epic_statuses[-1]["name"] if epic_statuses else None

    print("\n== update_epic ==")
    print(await server.update_epic(
        epic_id=epic.id,
        description="Updated by smoke_test.py",
        status=epic_status,
    ))

    print(f"\n== create_story (project {pid}, linked to epic #{epic.ref}) ==")
    story = await client.create_story(
        project_id=pid,
        subject=f"[smoke {stamp}] story",
        description="Created by smoke_test.py",
        epic_id=epic.id,
    )
    print(f"created story #{story.ref} (id {story.id})")

    print("\n== get_story (should show tags/epic linkage) ==")
    print(await server.get_story(story_id=story.id))

    story_statuses = await client._get(
        "/userstory-statuses", params={"project": pid}
    )
    story_status = story_statuses[-1]["name"] if story_statuses else None

    print("\n== update_story ==")
    print(await server.update_story(
        story_id=story.id,
        description="Updated by smoke_test.py",
        status=story_status,
    ))


async def main() -> None:
    await server.init()  # loads .env, fetches auth token, builds client

    print("== list_projects ==")
    print(await server.list_projects())

    projects = await server._get_client().list_projects()
    if not projects:
        print("\nNo projects on this account — nothing else to test.")
        return

    slug = os.environ.get("TAIGA_SMOKE_PROJECT_SLUG")
    if slug:
        smoke = next((p for p in projects if p.slug == slug), None)
        if smoke is None:
            available = ", ".join(p.slug for p in projects)
            raise SystemExit(
                f"TAIGA_SMOKE_PROJECT_SLUG='{slug}' not found among your "
                f"projects. Available slugs: {available}"
            )
        print(f"\nUsing smoke project '{smoke.name}' (slug: {smoke.slug}, "
              f"id: {smoke.id}) — FULL lifecycle (writes enabled).")
        await read_only_checks(smoke.id)
        await write_lifecycle(smoke.id)
    else:
        pid = projects[0].id
        print(f"\nTAIGA_SMOKE_PROJECT_SLUG not set — READ-ONLY run against "
              f"project {pid}. Set it to a throwaway project to test writes.")
        await read_only_checks(pid)


if __name__ == "__main__":
    asyncio.run(main())
