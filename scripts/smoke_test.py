"""Manual smoke test against a real Taiga account.

Run with:  uv run python scripts/smoke_test.py

The smoke test authenticates with its OWN credentials, separate from the MCP
server's. The server uses TAIGA_URL / TAIGA_USERNAME / TAIGA_PASSWORD; the smoke
test uses TAIGA_SMOKE_URL / TAIGA_SMOKE_USERNAME / TAIGA_SMOKE_PASSWORD. These
are required (there is no fallback to the server's TAIGA_* values), which lets
you point the write lifecycle at a throwaway project on a different account.

By default this is READ-ONLY: it lists projects and exercises the read tools
against the first project without mutating anything.

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

from taiga_mcp import server  # importing loads .env via server's load_dotenv()
from taiga_mcp.auth import authenticate
from taiga_mcp.client import TaigaClient


async def refresh_check() -> None:
    """Verify the client recovers from an expired/invalid token transparently.

    Corrupts the live token to force a real 401 from Taiga, then confirms the
    next call succeeds anyway via the refresh_token callback — this is the
    one thing respx-mocked unit tests can't prove: that Taiga's actual auth
    endpoint and 401 behavior line up with what the client expects.
    """
    print("\n== refresh on expired/invalid token ==")
    client = server._get_client()
    client._client.headers["Authorization"] = "Bearer invalid-token"
    projects = await client.list_projects()
    print(f"list_projects succeeded after forced 401 ({len(projects)} project(s)) "
          "— token was refreshed transparently.")


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
    assert epic.project_slug, "create_epic response is missing project_extra_info"

    print("\n== get_epic ==")
    print(await server.get_epic(epic_id=epic.id))

    # Exercise status name->id resolution using a real status from this project.
    epic_statuses = await client._get("/epic-statuses", params={"project": pid})
    epic_status = epic_statuses[-1]["name"] if epic_statuses else None

    print("\n== update_epic ==")
    result = await server.update_epic(
        epic_id=epic.id,
        description="Updated by smoke_test.py",
        status=epic_status,
    )
    print(result)
    # The verification link depends on the real API including
    # project_extra_info in write responses — mocked tests can't prove that.
    assert "Link:" in result, "update_epic output is missing the UI link"

    print(f"\n== create_story (project {pid}, linked to epic #{epic.ref}) ==")
    story = await client.create_story(
        project_id=pid,
        subject=f"[smoke {stamp}] story",
        description="Created by smoke_test.py",
        epic_id=epic.id,
    )
    print(f"created story #{story.ref} (id {story.id})")
    assert story.project_slug, "create_story response is missing project_extra_info"

    print("\n== get_story (should show tags/epic linkage) ==")
    print(await server.get_story(story_id=story.id))

    story_statuses = await client._get(
        "/userstory-statuses", params={"project": pid}
    )
    story_status = story_statuses[-1]["name"] if story_statuses else None

    print("\n== update_story ==")
    result = await server.update_story(
        story_id=story.id,
        description="Updated by smoke_test.py",
        status=story_status,
    )
    print(result)
    assert "Link:" in result, "update_story output is missing the UI link"


def _smoke_env(name: str) -> str:
    """Read a required TAIGA_SMOKE_<NAME> variable.

    The smoke test runs only with its own credentials — there is no fallback
    to the MCP server's TAIGA_* variables.
    """
    value = os.environ.get(f"TAIGA_SMOKE_{name}")
    if not value:
        raise SystemExit(
            f"TAIGA_SMOKE_{name} is not set. The smoke test requires its own "
            f"credentials (TAIGA_SMOKE_URL / TAIGA_SMOKE_USERNAME / "
            f"TAIGA_SMOKE_PASSWORD), separate from the MCP server's TAIGA_*."
        )
    return value


async def main() -> None:
    # The smoke test runs against its own account (TAIGA_SMOKE_* creds),
    # separate from the MCP server (TAIGA_*). Build a client for it and install
    # it as the module client so the server.* tools operate on this account.
    url = _smoke_env("URL")
    username = _smoke_env("USERNAME")
    password = _smoke_env("PASSWORD")
    timeout = float(os.environ.get("TAIGA_TIMEOUT", "30"))

    async def refresh_token() -> str:
        token, _ = await authenticate(url, username, password, timeout)
        return token

    token, user_id = await authenticate(url, username, password, timeout)
    server._client = TaigaClient(
        url, token, user_id, timeout=timeout, refresh_token=refresh_token
    )
    # server.init() is bypassed here, so set the UI base the same way it
    # would — the write lifecycle asserts the tools return UI links.
    server._ui_base = server._derive_ui_base(url)

    print(f"== list_projects (user: {username}) ==")
    print(await server.list_projects())

    await refresh_check()

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
                f"TAIGA_SMOKE_PROJECT_SLUG='{slug}' not found among this "
                f"account's projects. Available slugs: {available}"
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
