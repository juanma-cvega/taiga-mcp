import asyncio
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from taiga_mcp.auth import authenticate
from taiga_mcp.client import TaigaClient

load_dotenv()

mcp = FastMCP("taiga")
_client: TaigaClient | None = None


def _get_client() -> TaigaClient:
    if _client is None:
        raise RuntimeError("Client not initialised — call init() first")
    return _client


async def init() -> None:
    global _client
    base_url = os.environ["TAIGA_URL"]
    username = os.environ["TAIGA_USERNAME"]
    password = os.environ["TAIGA_PASSWORD"]
    token, user_id = await authenticate(base_url, username, password)
    _client = TaigaClient(base_url, token, user_id)


@mcp.tool()
async def list_projects() -> str:
    """List all Taiga projects accessible to the authenticated user."""
    projects = await _get_client().list_projects()
    if not projects:
        return "No projects found."
    return "\n".join(
        f"- {p.name} (slug: {p.slug}, id: {p.id})" for p in projects
    )


@mcp.tool()
async def list_user_stories(
    project_id: int,
    sprint_id: int | None = None,
    status: str | None = None,
) -> str:
    """
    List user stories for a Taiga project.

    Args:
        project_id: Numeric Taiga project ID.
        sprint_id: Optional sprint (milestone) ID to filter by.
        status: Optional filter — 'open' or 'closed'.
    """
    stories = await _get_client().list_user_stories(
        project_id=project_id, sprint_id=sprint_id, status=status
    )
    if not stories:
        return "No user stories found."
    return "\n".join(
        f"- #{s.ref} {s.subject} [{s.status}]"
        + (f" (sprint: {s.milestone_name})" if s.milestone_name else "")
        for s in stories
    )


@mcp.tool()
async def list_tasks(project_id: int, user_story_id: int | None = None) -> str:
    """
    List tasks for a Taiga project, optionally filtered by user story.

    Args:
        project_id: Numeric Taiga project ID.
        user_story_id: Optional user story ID to scope the task list.
    """
    tasks = await _get_client().list_tasks(
        project_id=project_id, user_story_id=user_story_id
    )
    if not tasks:
        return "No tasks found."
    return "\n".join(f"- #{t.ref} {t.subject} [{t.status}]" for t in tasks)


@mcp.tool()
async def list_epics(project_id: int) -> str:
    """
    List epics for a Taiga project.

    Args:
        project_id: Numeric Taiga project ID.
    """
    epics = await _get_client().list_epics(project_id=project_id)
    if not epics:
        return "No epics found."
    return "\n".join(f"- #{e.ref} {e.subject} [{e.status}]" for e in epics)


@mcp.tool()
async def get_current_sprint(project_id: int) -> str:
    """
    Get the currently open sprint for a Taiga project.

    Args:
        project_id: Numeric Taiga project ID.
    """
    sprints = await _get_client().list_sprints(project_id=project_id, closed=False)
    if not sprints:
        return "No open sprint found for this project."
    s = sprints[0]
    return (
        f"Sprint: {s.name}\n"
        f"Start:  {s.estimated_start}\n"
        f"End:    {s.estimated_finish}\n"
        f"ID:     {s.id}"
    )


def main() -> None:
    asyncio.run(init())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
