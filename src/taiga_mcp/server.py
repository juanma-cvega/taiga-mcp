import asyncio
import os
import re
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from taiga_mcp.auth import authenticate
from taiga_mcp.client import TaigaClient
from taiga_mcp.models import Epic, Sprint, Task

load_dotenv()

mcp = FastMCP("taiga")
_client: TaigaClient | None = None
_ui_base: str | None = None


def _get_client() -> TaigaClient:
    if _client is None:
        raise RuntimeError("Client not initialised — call init() first")
    return _client


def _derive_ui_base(api_url: str) -> str:
    """Derive the web-UI base URL from the API URL: drop the trailing
    /api/vN path segment, and map Taiga Cloud's API host to its UI host
    (the two live on different subdomains)."""
    ui_url = re.sub(r"/api/v\d+/?$", "", api_url.rstrip("/"))
    parts = urlsplit(ui_url)
    if parts.netloc == "api.taiga.io":
        parts = parts._replace(netloc="tree.taiga.io")
    return urlunsplit(parts)


def _permalink(item) -> str | None:
    """Web-UI URL for an epic, story, task or sprint, so a human can eyeball
    the result of a write. None when the UI base or project slug is
    unavailable."""
    slug = getattr(item, "project_slug", None)
    if _ui_base is None or slug is None:
        return None
    if isinstance(item, Sprint):
        # A sprint has no #ref; the UI addresses its taskboard by sprint slug.
        if item.slug is None:
            return None
        return f"{_ui_base}/project/{slug}/taskboard/{item.slug}"
    if isinstance(item, Epic):
        kind = "epic"
    elif isinstance(item, Task):
        kind = "task"
    else:
        kind = "us"
    return f"{_ui_base}/project/{slug}/{kind}/{item.ref}"


def _with_link(message: str, item) -> str:
    link = _permalink(item)
    return f"{message}\nLink: {link}" if link else message


def _format_detail(item) -> str:
    lines = [f"#{item.ref} {item.subject} [{item.status}]"]
    link = _permalink(item)
    if link:
        lines.append(f"Link: {link}")
    if getattr(item, "milestone_name", None):
        lines.append(f"Sprint: {item.milestone_name}")
    if item.assigned_to is not None:
        lines.append(f"Assigned to: {item.assigned_to}")
    blocked = f"Blocked: {bool(item.is_blocked)}"
    if item.blocked_note:
        blocked += f" ({item.blocked_note})"
    lines.append(blocked)
    if item.tags:
        names = [tag[0] if isinstance(tag, (list, tuple)) else tag for tag in item.tags]
        lines.append(f"Tags: {', '.join(names)}")
    epics = getattr(item, "epics", None)
    if epics:
        lines.append(
            "Epics: "
            + ", ".join(
                f"#{e.get('ref', '?')} {e.get('subject', 'unknown')}" for e in epics
            )
        )
    lines.append(f"Description:\n{item.description or '—'}")
    return "\n".join(lines)


def _format_sprint(sprint: Sprint) -> str:
    lines = [
        f"Sprint: {sprint.name} (id: {sprint.id})",
        f"Start:  {sprint.estimated_start}",
        f"End:    {sprint.estimated_finish}",
        f"Status: {'closed' if sprint.closed else 'open'}",
    ]
    link = _permalink(sprint)
    if link:
        lines.append(f"Link: {link}")
    return "\n".join(lines)


async def init() -> None:
    global _client, _ui_base
    base_url = os.environ["TAIGA_URL"]
    _ui_base = os.environ.get("TAIGA_UI_URL", "").rstrip("/") or _derive_ui_base(
        base_url
    )
    username = os.environ["TAIGA_USERNAME"]
    password = os.environ["TAIGA_PASSWORD"]
    timeout = float(os.environ.get("TAIGA_TIMEOUT", "30"))

    async def refresh_token() -> str:
        token, _ = await authenticate(base_url, username, password, timeout=timeout)
        return token

    token, user_id = await authenticate(base_url, username, password, timeout=timeout)
    _client = TaigaClient(
        base_url, token, user_id, timeout=timeout, refresh_token=refresh_token
    )


@mcp.tool()
async def list_projects() -> str:
    """List all Taiga projects accessible to the authenticated user."""
    projects = await _get_client().list_projects()
    if not projects:
        return "No projects found."
    return "\n".join(f"- {p.name} (slug: {p.slug}, id: {p.id})" for p in projects)


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
        f"- #{s.ref} {s.subject} (id: {s.id}) [{s.status}]"
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

    def line(t) -> str:
        text = f"- #{t.ref} {t.subject} (id: {t.id}) [{t.status}]"
        link = _permalink(t)
        return f"{text} — {link}" if link else text

    return "\n".join(line(t) for t in tasks)


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
    return "\n".join(f"- #{e.ref} {e.subject} (id: {e.id}) [{e.status}]" for e in epics)


@mcp.tool()
async def get_epic(epic_id: int) -> str:
    """Get a single Taiga epic by its numeric id.

    Args:
        epic_id: Numeric Taiga epic ID.
    """
    return _format_detail(await _get_client().get_epic(epic_id))


@mcp.tool()
async def get_story(story_id: int) -> str:
    """Get a single Taiga user story by its numeric id.

    Args:
        story_id: Numeric Taiga user story ID.
    """
    return _format_detail(await _get_client().get_story(story_id))


@mcp.tool()
async def get_epic_by_ref(project_id: int, ref: int) -> str:
    """Get a single Taiga epic by its per-project #ref (the number shown in
    the Taiga UI), not its internal id.

    Args:
        project_id: Numeric Taiga project ID.
        ref: The epic's #ref within that project.
    """
    return _format_detail(await _get_client().get_epic_by_ref(project_id, ref))


@mcp.tool()
async def get_story_by_ref(project_id: int, ref: int) -> str:
    """Get a single Taiga user story by its per-project #ref (the number shown
    in the Taiga UI), not its internal id.

    Args:
        project_id: Numeric Taiga project ID.
        ref: The story's #ref within that project.
    """
    return _format_detail(await _get_client().get_story_by_ref(project_id, ref))


@mcp.tool()
async def create_epic(
    project_id: int,
    subject: str,
    description: str | None = None,
    status: str | None = None,
    assigned_to: int | None = None,
    tags: list | None = None,
    is_blocked: bool | None = None,
    blocked_note: str | None = None,
    color: str | None = None,
) -> str:
    """
    Create a Taiga epic.

    Args:
        project_id: Numeric Taiga project ID.
        subject: Epic title (required).
        description: Optional body text.
        status: Optional status NAME (resolved to the project's status id).
        assigned_to: Optional numeric user id.
        tags: Optional list of tags.
        is_blocked: Optional blocked flag.
        blocked_note: Optional reason when blocked.
        color: Optional hex color.
    """
    epic = await _get_client().create_epic(
        project_id=project_id,
        subject=subject,
        description=description,
        status=status,
        assigned_to=assigned_to,
        tags=tags,
        is_blocked=is_blocked,
        blocked_note=blocked_note,
        color=color,
    )
    return _with_link(f"Created #{epic.ref} {epic.subject} (id: {epic.id})", epic)


@mcp.tool()
async def create_story(
    project_id: int,
    subject: str,
    description: str | None = None,
    status: str | None = None,
    sprint_id: int | None = None,
    epic_id: int | None = None,
    assigned_to: int | None = None,
    tags: list | None = None,
    is_blocked: bool | None = None,
    blocked_note: str | None = None,
) -> str:
    """
    Create a Taiga user story.

    Args:
        project_id: Numeric Taiga project ID.
        subject: Story title (required).
        description: Optional body text.
        status: Optional status NAME (resolved to the project's status id).
        sprint_id: Optional sprint (milestone) id.
        epic_id: Optional epic id to link the new story to.
        assigned_to: Optional numeric user id.
        tags: Optional list of tags.
        is_blocked: Optional blocked flag.
        blocked_note: Optional reason when blocked.
    """
    story = await _get_client().create_story(
        project_id=project_id,
        subject=subject,
        description=description,
        status=status,
        sprint_id=sprint_id,
        epic_id=epic_id,
        assigned_to=assigned_to,
        tags=tags,
        is_blocked=is_blocked,
        blocked_note=blocked_note,
    )
    return _with_link(f"Created #{story.ref} {story.subject} (id: {story.id})", story)


@mcp.tool()
async def update_epic(
    epic_id: int,
    subject: str | None = None,
    description: str | None = None,
    status: str | None = None,
    assigned_to: int | None = None,
    tags: list | None = None,
    is_blocked: bool | None = None,
    blocked_note: str | None = None,
    color: str | None = None,
) -> str:
    """
    Update a Taiga epic. Any argument left as None is unchanged; pass '' to
    clear a text field.

    Args:
        epic_id: Numeric Taiga epic ID.
        subject: New title.
        description: New body text ('' clears it).
        status: New status NAME (resolved to the project's status id).
        assigned_to: Numeric user id.
        tags: List of tags.
        is_blocked: Blocked flag.
        blocked_note: Reason when blocked ('' clears it).
        color: Hex color ('' clears it).
    """
    epic = await _get_client().update_epic(
        epic_id,
        subject=subject,
        description=description,
        status=status,
        assigned_to=assigned_to,
        tags=tags,
        is_blocked=is_blocked,
        blocked_note=blocked_note,
        color=color,
    )
    return _with_link(f"Updated #{epic.ref} {epic.subject} [{epic.status}]", epic)


@mcp.tool()
async def update_story(
    story_id: int,
    subject: str | None = None,
    description: str | None = None,
    status: str | None = None,
    sprint_id: int | None = None,
    assigned_to: int | None = None,
    tags: list | None = None,
    is_blocked: bool | None = None,
    blocked_note: str | None = None,
) -> str:
    """
    Update a Taiga user story. Any argument left as None is unchanged; pass ''
    to clear a text field.

    Args:
        story_id: Numeric Taiga user story ID.
        subject: New title.
        description: New body text ('' clears it).
        status: New status NAME (resolved to the project's status id).
        sprint_id: Sprint (milestone) id.
        assigned_to: Numeric user id.
        tags: List of tags.
        is_blocked: Blocked flag.
        blocked_note: Reason when blocked ('' clears it).
    """
    story = await _get_client().update_story(
        story_id,
        subject=subject,
        description=description,
        status=status,
        sprint_id=sprint_id,
        assigned_to=assigned_to,
        tags=tags,
        is_blocked=is_blocked,
        blocked_note=blocked_note,
    )
    return _with_link(f"Updated #{story.ref} {story.subject} [{story.status}]", story)


@mcp.tool()
async def update_epic_by_ref(
    project_id: int,
    ref: int,
    subject: str | None = None,
    description: str | None = None,
    status: str | None = None,
    assigned_to: int | None = None,
    tags: list | None = None,
    is_blocked: bool | None = None,
    blocked_note: str | None = None,
    color: str | None = None,
) -> str:
    """
    Update a Taiga epic by its per-project #ref (the number shown in the UI).
    Any argument left as None is unchanged; pass '' to clear a text field.

    Args:
        project_id: Numeric Taiga project ID.
        ref: The epic's #ref within that project.
        subject: New title.
        description: New body text ('' clears it).
        status: New status NAME (resolved to the project's status id).
        assigned_to: Numeric user id.
        tags: List of tags.
        is_blocked: Blocked flag.
        blocked_note: Reason when blocked ('' clears it).
        color: Hex color ('' clears it).
    """
    epic = await _get_client().update_epic_by_ref(
        project_id,
        ref,
        subject=subject,
        description=description,
        status=status,
        assigned_to=assigned_to,
        tags=tags,
        is_blocked=is_blocked,
        blocked_note=blocked_note,
        color=color,
    )
    return _with_link(f"Updated #{epic.ref} {epic.subject} [{epic.status}]", epic)


@mcp.tool()
async def update_story_by_ref(
    project_id: int,
    ref: int,
    subject: str | None = None,
    description: str | None = None,
    status: str | None = None,
    sprint_id: int | None = None,
    assigned_to: int | None = None,
    tags: list | None = None,
    is_blocked: bool | None = None,
    blocked_note: str | None = None,
) -> str:
    """
    Update a Taiga user story by its per-project #ref (the number shown in the
    UI). Any argument left as None is unchanged; pass '' to clear a text field.

    Args:
        project_id: Numeric Taiga project ID.
        ref: The story's #ref within that project.
        subject: New title.
        description: New body text ('' clears it).
        status: New status NAME (resolved to the project's status id).
        sprint_id: Sprint (milestone) id.
        assigned_to: Numeric user id.
        tags: List of tags.
        is_blocked: Blocked flag.
        blocked_note: Reason when blocked ('' clears it).
    """
    story = await _get_client().update_story_by_ref(
        project_id,
        ref,
        subject=subject,
        description=description,
        status=status,
        sprint_id=sprint_id,
        assigned_to=assigned_to,
        tags=tags,
        is_blocked=is_blocked,
        blocked_note=blocked_note,
    )
    return _with_link(f"Updated #{story.ref} {story.subject} [{story.status}]", story)


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
    return _format_sprint(sprints[0])


@mcp.tool()
async def list_sprints(project_id: int, closed: bool | None = None) -> str:
    """
    List sprints (milestones) for a Taiga project.

    Args:
        project_id: Numeric Taiga project ID.
        closed: Optional filter — True for closed sprints only, False for open
            ones only. Omit for all sprints.
    """
    sprints = await _get_client().list_sprints(project_id=project_id, closed=closed)
    if not sprints:
        return "No sprints found."
    return "\n".join(
        f"- {s.name} (id: {s.id}) {s.estimated_start} → {s.estimated_finish} "
        f"[{'closed' if s.closed else 'open'}]"
        for s in sprints
    )


@mcp.tool()
async def get_sprint(sprint_id: int) -> str:
    """
    Get a single Taiga sprint (milestone) by its numeric id.

    Args:
        sprint_id: Numeric Taiga sprint (milestone) ID.
    """
    return _format_sprint(await _get_client().get_sprint(sprint_id))


@mcp.tool()
async def create_sprint(
    project_id: int,
    name: str,
    estimated_start: str,
    estimated_finish: str,
) -> str:
    """
    Create a Taiga sprint (milestone).

    Args:
        project_id: Numeric Taiga project ID.
        name: Sprint name (required, and must be unique within the project).
        estimated_start: Start date, YYYY-MM-DD (required).
        estimated_finish: End date, YYYY-MM-DD (required).
    """
    sprint = await _get_client().create_sprint(
        project_id=project_id,
        name=name,
        estimated_start=estimated_start,
        estimated_finish=estimated_finish,
    )
    return _with_link(f"Created sprint {sprint.name} (id: {sprint.id})", sprint)


@mcp.tool()
async def update_sprint(
    sprint_id: int,
    name: str | None = None,
    estimated_start: str | None = None,
    estimated_finish: str | None = None,
    closed: bool | None = None,
) -> str:
    """
    Update a Taiga sprint (milestone). Any argument left as None is unchanged.

    Args:
        sprint_id: Numeric Taiga sprint (milestone) ID.
        name: New name (must be unique within the project).
        estimated_start: New start date, YYYY-MM-DD.
        estimated_finish: New end date, YYYY-MM-DD.
        closed: True to close the sprint, False to reopen it.
    """
    sprint = await _get_client().update_sprint(
        sprint_id,
        name=name,
        estimated_start=estimated_start,
        estimated_finish=estimated_finish,
        closed=closed,
    )
    return _with_link(
        f"Updated sprint {sprint.name} [{'closed' if sprint.closed else 'open'}]",
        sprint,
    )


@mcp.tool()
async def close_sprint(sprint_id: int) -> str:
    """
    Close a Taiga sprint (milestone). Stories stay assigned to it; use
    move_story_to_backlog first for any unfinished work that should carry over.

    Args:
        sprint_id: Numeric Taiga sprint (milestone) ID.
    """
    sprint = await _get_client().update_sprint(sprint_id, closed=True)
    return _with_link(f"Closed sprint {sprint.name} (id: {sprint.id})", sprint)


@mcp.tool()
async def delete_sprint(sprint_id: int) -> str:
    """
    Delete a Taiga sprint (milestone) permanently. This cannot be undone.

    The sprint's user stories are NOT deleted — Taiga detaches them and they
    return to the backlog.

    Args:
        sprint_id: Numeric Taiga sprint (milestone) ID.
    """
    sprint = await _get_client().get_sprint(sprint_id)
    await _get_client().delete_sprint(sprint_id)
    return (
        f"Deleted sprint {sprint.name} (id: {sprint.id}). Any stories it held "
        f"are back in the backlog."
    )


@mcp.tool()
async def move_story_to_backlog(story_id: int) -> str:
    """
    Move a user story out of its sprint and back to the project backlog.

    Args:
        story_id: Numeric Taiga user story ID.
    """
    story = await _get_client().move_story_to_backlog(story_id)
    return _with_link(f"Moved #{story.ref} {story.subject} to the backlog", story)


def main() -> None:
    asyncio.run(init())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
