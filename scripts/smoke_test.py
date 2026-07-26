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
epic and a linked story in that project, updates them, and reads them back. It
then runs the issue lifecycle (create, update, comment, promote and delete an
issue, exercising the per-project type/priority/severity catalogues), the
sprint lifecycle (create a sprint, move the story in and out of it, close the
sprint and delete it), and the deletion lifecycle: create and update tasks,
promote one to a story, then delete the task, story and epics.

    TAIGA_SMOKE_PROJECT_SLUG=your-smoke-project uv run python scripts/smoke_test.py

A full run leaves nothing behind — everything it creates it deletes, which is
also how it verifies what Taiga takes down with each delete (tasks cascade
from their story; an epic's stories survive it). A run that does NOT finish
does leave debris, since the teardown is inline: scripts/smoke_cleanup.py
removes it, and CI runs that after every smoke run whatever the outcome.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

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
    print(
        f"list_projects succeeded after forced 401 ({len(projects)} project(s)) "
        "— token was refreshed transparently."
    )


async def read_only_checks(pid: int) -> None:
    """Exercise the non-mutating tools against project `pid`."""
    print(f"\n== get_current_sprint (project {pid}) ==")
    print(await server.get_current_sprint(project_id=pid))

    print(f"\n== list_epics (project {pid}) ==")
    print(await server.list_epics(project_id=pid))

    print(f"\n== list_user_stories (project {pid}) ==")
    print(await server.list_user_stories(project_id=pid))

    print(f"\n== list_tasks (project {pid}) ==")
    result = await server.list_tasks(project_id=pid)
    print(result)
    if "No tasks found" not in result:
        assert "/task/" in result, "list_tasks output is missing task UI links"


async def write_lifecycle(pid: int) -> None:
    """Exercise create/get/update for epics and stories in the smoke project.

    Uses the client directly to capture the created objects' ids, then drives
    the MCP tools (server.*) for get/update so both layers are exercised. The
    epics and story created here are torn down by deletion_lifecycle at the
    end, so a full run leaves the project as it found it.
    """
    client = server._get_client()
    stamp = datetime.now(UTC).isoformat(timespec="seconds")

    print(f"\n== create_epic (project {pid}) ==")
    epic = await client.create_epic(
        project_id=pid,
        subject=f"[smoke {stamp}] epic",
        description="Created by smoke_test.py",
    )
    print(f"created epic #{epic.ref} (id {epic.id})")
    assert epic.project_slug, "create_epic response is missing project_extra_info"

    print("\n== get_epic ==")
    result = await server.get_epic(epic_id=epic.id)
    print(result)
    assert "Link:" in result, "get_epic output is missing the UI link"

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
    result = await server.get_story(story_id=story.id)
    print(result)
    assert "Link:" in result, "get_story output is missing the UI link"

    story_statuses = await client._get("/userstory-statuses", params={"project": pid})
    story_status = story_statuses[-1]["name"] if story_statuses else None

    print("\n== update_story ==")
    result = await server.update_story(
        story_id=story.id,
        description="Updated by smoke_test.py",
        status=story_status,
    )
    print(result)
    assert "Link:" in result, "update_story output is missing the UI link"

    print("\n== update_story: attach the story to a second epic ==")
    other_epic = await client.create_epic(
        project_id=pid,
        subject=f"[smoke {stamp}] epic (attach target)",
    )
    print(await server.update_story(story_id=story.id, epic_id=other_epic.id))
    # Attaching twice must be a no-op: Taiga 400s on a duplicate link, and only
    # the real API proves the story's `epics` field is shaped as the skip reads
    # it — and that attaching adds to the epics a story is in, never replaces.
    print(await server.update_story(story_id=story.id, epic_id=other_epic.id))
    linked = {item["id"] for item in (await client.get_story(story.id)).epics or []}
    assert linked == {epic.id, other_epic.id}, (
        f"story is in epics {linked}, expected both {epic.id} and {other_epic.id}"
    )

    print("\n== add_comment (story, by id) ==")
    result = await server.add_comment(
        item_type="story", item_id=story.id, comment="Commented by smoke_test.py"
    )
    print(result)
    # Only the real API proves a `comment` PATCH is accepted and does not
    # clobber the rest of the item.
    assert "Link:" in result, "add_comment output is missing the UI link"
    unchanged = await client.get_story(story.id)
    assert unchanged.description == "Updated by smoke_test.py", (
        "add_comment overwrote the story description"
    )

    print("\n== list_comments (story) ==")
    result = await server.list_comments(item_type="story", item_id=story.id)
    print(result)
    # Proves the history feed really carries the comment we just wrote, and
    # that the field names this parses (comment, created_at, user) are real.
    assert "Commented by smoke_test.py" in result, (
        "list_comments did not return the comment just added"
    )

    print("\n== add_comment_by_ref (epic) ==")
    print(
        await server.add_comment_by_ref(
            item_type="epic",
            project_id=pid,
            ref=epic.ref,
            comment="Commented by ref from smoke_test.py",
        )
    )

    print("\n== list_comments_by_ref (epic) ==")
    result = await server.list_comments_by_ref(
        item_type="epic", project_id=pid, ref=epic.ref
    )
    print(result)
    assert "Commented by ref from smoke_test.py" in result, (
        "list_comments_by_ref did not return the comment just added"
    )

    print("\n== reorder_backlog_stories (move story to the top of the backlog) ==")
    # The story is still in the backlog here, so reordering it is valid. Only
    # the real API proves the bulk_update_backlog_order payload shape is right.
    result = await server.reorder_backlog_stories(project_id=pid, story_ids=[story.id])
    print(result)

    await issue_lifecycle(pid, stamp)
    await sprint_lifecycle(pid, story.id, stamp)
    await deletion_lifecycle(pid, story.id, [epic.id, other_epic.id], stamp)


async def _create_task(pid: int, story_id: int, subject: str) -> int:
    """Create a task on a story via the tool, returning its id.

    The tool returns a formatted string, so the id is read back off the story's
    task list — which doubles as proof that a task created with user_story set
    really does land under that story.
    """
    client = server._get_client()
    print(
        await server.create_task(
            project_id=pid, subject=subject, user_story_id=story_id
        )
    )
    tasks = await client.list_tasks(project_id=pid, user_story_id=story_id)
    task = next(t for t in tasks if t.subject == subject)
    return task.id


async def deletion_lifecycle(
    pid: int, story_id: int, epic_ids: list[int], stamp: str
) -> None:
    """Exercise task promotion and the story/epic/task deletes, tearing down
    everything the epic/story lifecycle created.

    Each delete tool promises something about what it takes with it, and those
    promises are Taiga's referential-integrity rules rather than anything this
    code does: tasks cascade from their story, epics only lose the links to
    theirs, and a promoted task is deleted. Mocked tests cannot prove any of
    it — this can, and it leaves the smoke project clean besides.
    """
    client = server._get_client()

    print("\n== create_task + update_task ==")
    task_id = await _create_task(pid, story_id, f"[smoke {stamp}] task (to delete)")
    # Tasks carry their own status catalogue, separate from the story one the
    # epic/story lifecycle resolved against — only the real API proves
    # /task-statuses is the right endpoint and that its ids are accepted here.
    task_statuses = await client._get("/task-statuses", params={"project": pid})
    result = await server.update_task(
        task_id=task_id,
        description="Updated by smoke_test.py",
        status=task_statuses[-1]["name"] if task_statuses else None,
    )
    print(result)
    assert "Link:" in result, "update_task output is missing the UI link"
    updated = await client.get_task(task_id)
    assert updated.description == "Updated by smoke_test.py", "task was not updated"
    assert updated.version is not None, (
        "task response has no version; update_task cannot version-check its PATCH"
    )

    print("\n== get_task ==")
    result = await server.get_task(task_id=task_id)
    print(result)
    assert "Link:" in result, "get_task output is missing the UI link"

    print("\n== get_task_by_ref + update_task_by_ref ==")
    # /tasks/by_ref is absent from Taiga's published API reference, so this is
    # the only check that the endpoint exists at all for tasks (it does for
    # stories, epics and issues) — the by_ref tools are unusable if it doesn't.
    result = await server.get_task_by_ref(project_id=pid, ref=updated.ref)
    print(result)
    assert f"#{updated.ref}" in result, "get_task_by_ref returned the wrong task"
    print(
        await server.update_task_by_ref(
            project_id=pid,
            ref=updated.ref,
            description="Updated by ref from smoke_test.py",
        )
    )
    assert (await client.get_task(task_id)).description == (
        "Updated by ref from smoke_test.py"
    ), "update_task_by_ref did not reach the task"

    print("\n== delete_task ==")
    print(await server.delete_task(task_id=task_id))
    tasks = await client.list_tasks(project_id=pid, user_story_id=story_id)
    assert not any(t.id == task_id for t in tasks), "task was not deleted"
    assert (await client.get_story(story_id)).id == story_id, (
        "deleting a task deleted its user story"
    )

    print("\n== promote_task_to_story ==")
    task_id = await _create_task(pid, story_id, f"[smoke {stamp}] task (to promote)")
    result = await server.promote_task_to_story(task_id=task_id)
    print(result)
    promoted = next(
        s
        for s in await client.list_user_stories(project_id=pid)
        if s.subject == f"[smoke {stamp}] task (to promote)"
    )
    # The half of promotion that differs from an issue's, and the reason the
    # tool is flagged destructive: Taiga deletes the task it promoted.
    tasks = await client.list_tasks(project_id=pid, user_story_id=story_id)
    assert not any(t.id == task_id for t in tasks), (
        "promoted task still exists; Taiga is expected to delete it"
    )
    print(await server.delete_story(story_id=promoted.id))

    print("\n== delete_epic (its stories must survive) ==")
    print(await server.delete_epic(epic_id=epic_ids[-1]))
    survivor = await client.get_story(story_id)
    linked = {item["id"] for item in survivor.epics or []}
    assert epic_ids[-1] not in linked, "story still links to the deleted epic"

    print("\n== delete_story (its tasks must go with it) ==")
    task_id = await _create_task(pid, story_id, f"[smoke {stamp}] task (cascade)")
    print(await server.delete_story(story_id=story_id))
    remaining = await client.list_user_stories(project_id=pid)
    assert not any(s.id == story_id for s in remaining), "story was not deleted"
    # Task.user_story is on_delete=CASCADE, so the task must be gone too.
    tasks = await client.list_tasks(project_id=pid)
    assert not any(t.id == task_id for t in tasks), (
        "task outlived the story it belonged to"
    )

    print("\n== delete_epic (the last one, leaving nothing behind) ==")
    print(await server.delete_epic(epic_id=epic_ids[0]))
    epics = await client.list_epics(project_id=pid)
    assert not any(e.id in epic_ids for e in epics), "an epic was not deleted"


async def issue_lifecycle(pid: int, stamp: str) -> None:
    """Exercise create/get/update/comment/promote/delete for issues.

    Leaves nothing behind: the issue, and the story it is promoted into, are
    both deleted at the end.

    The point of running this against the real API is the four per-project
    catalogues (status, type, priority, severity). Mocked tests can only prove
    we send whatever id a fake /issue-types returned; only Taiga proves those
    endpoints exist, that they are the ones scoped by ?project, and that the
    ids they hand back are accepted on a POST /issues.
    """
    client = server._get_client()

    # Resolve real names from this project rather than guessing: a project's
    # catalogues are editable, so "Bug"/"High"/"Normal" are conventions, not
    # guarantees, and a fixed guess would fail on a customised project.
    types = await client._get("/issue-types", params={"project": pid})
    priorities = await client._get("/priorities", params={"project": pid})
    severities = await client._get("/severities", params={"project": pid})
    assert types and priorities and severities, (
        "project has an empty issue catalogue; issues cannot be created"
    )

    print(f"\n== create_issue (project {pid}) ==")
    issue = await client.create_issue(
        project_id=pid,
        subject=f"[smoke {stamp}] issue",
        description="Created by smoke_test.py",
        issue_type=types[0]["name"],
        priority=priorities[0]["name"],
        severity=severities[0]["name"],
    )
    print(f"created issue #{issue.ref} (id {issue.id})")
    assert issue.project_slug, "create_issue response is missing project_extra_info"
    # Names really were resolved to this project's ids and accepted.
    assert issue.type == types[0]["id"], "issue type was not applied"
    assert issue.priority == priorities[0]["id"], "issue priority was not applied"
    assert issue.severity == severities[0]["id"], "issue severity was not applied"

    print("\n== get_issue ==")
    result = await server.get_issue(issue_id=issue.id)
    print(result)
    # The UI addresses issues under /issue/<ref>; a wrong kind here 404s for a
    # human following the link, which no mocked test would notice.
    assert f"/issue/{issue.ref}" in result, "get_issue link is not an issue URL"

    print("\n== get_issue_by_ref ==")
    print(await server.get_issue_by_ref(project_id=pid, ref=issue.ref))

    print("\n== update_issue (severity + description) ==")
    result = await server.update_issue(
        issue_id=issue.id,
        description="Updated by smoke_test.py",
        severity=severities[-1]["name"],
    )
    print(result)
    updated = await client.get_issue(issue.id)
    assert updated.severity == severities[-1]["id"], "issue severity was not updated"

    print("\n== update_issue: unknown severity is rejected with the real values ==")
    # Proves the error an agent gets back names this project's severities.
    try:
        await server.update_issue(issue_id=issue.id, severity="Definitely Not A Sev")
    except ValueError as exc:
        assert severities[0]["name"] in str(exc), (
            f"unknown-severity error does not list the project's severities: {exc}"
        )
        print(f"rejected as expected: {exc}")
    else:
        raise AssertionError("an unknown severity was accepted")

    print("\n== add_comment (issue) ==")
    result = await server.add_comment(
        item_type="issue", item_id=issue.id, comment="Commented by smoke_test.py"
    )
    print(result)
    unchanged = await client.get_issue(issue.id)
    assert unchanged.description == "Updated by smoke_test.py", (
        "add_comment overwrote the issue description"
    )

    print("\n== list_comments (issue) ==")
    result = await server.list_comments(item_type="issue", item_id=issue.id)
    print(result)
    # Proves /history/issue/<id> is the right feed name for issues.
    assert "Commented by smoke_test.py" in result, (
        "list_comments did not return the comment just added to the issue"
    )

    print("\n== list_issues (should include the new issue) ==")
    listed = await client.list_issues(project_id=pid)
    assert any(i.id == issue.id for i in listed), (
        "new issue is missing from list_issues"
    )

    print("\n== promote_issue_to_story ==")
    # promote_to_user_story is undocumented in Taiga's API reference, so the
    # real API is the only thing that proves the endpoint exists, that it
    # wants project_id in the body, and that it answers with a list of #refs
    # rather than a story object.
    result = await server.promote_issue_to_story(issue_id=issue.id)
    print(result)
    assert "Link:" in result, "promote_issue_to_story output is missing the UI link"
    promoted = next(
        s
        for s in await client.list_user_stories(project_id=pid)
        if s.subject == f"[smoke {stamp}] issue"
    )
    # An issue survives its own promotion — only a promoted task is deleted.
    surviving = await client.get_issue(issue.id)
    assert surviving.id == issue.id, "promoting the issue deleted it"

    print("\n== delete_story (the story the issue was promoted into) ==")
    print(await server.delete_story(story_id=promoted.id))

    print("\n== delete_issue ==")
    print(await server.delete_issue(issue_id=issue.id))
    remaining = await client.list_issues(project_id=pid)
    assert not any(i.id == issue.id for i in remaining), "issue was not deleted"


async def sprint_lifecycle(pid: int, story_id: int, stamp: str) -> None:
    """Exercise the full sprint lifecycle, ending in a delete.

    Unlike the epic/story lifecycle this leaves nothing behind: the sprint is
    deleted at the end, which also verifies Taiga's documented behaviour of
    detaching (not deleting) the sprint's stories.
    """
    client = server._get_client()
    # Not date.today(): that reads the runner's local timezone, so a smoke test
    # run late in the evening west of UTC would date the sprint a day behind
    # the stamps above, which are UTC.
    today = datetime.now(UTC).date()

    print(f"\n== create_sprint (project {pid}) ==")
    result = await server.create_sprint(
        project_id=pid,
        name=f"[smoke {stamp}] sprint",
        estimated_start=today.isoformat(),
        estimated_finish=(today + timedelta(days=14)).isoformat(),
    )
    print(result)
    # The taskboard link depends on the real API returning slug +
    # project_extra_info on a create — mocked tests can't prove that.
    assert "Link:" in result, "create_sprint output is missing the UI link"

    sprints = await client.list_sprints(project_id=pid, closed=False)
    sprint = next(s for s in sprints if s.name == f"[smoke {stamp}] sprint")
    print(f"created sprint {sprint.name} (id {sprint.id})")

    print("\n== update_sprint (rename + move the end date) ==")
    print(
        await server.update_sprint(
            sprint_id=sprint.id,
            name=f"[smoke {stamp}] sprint (renamed)",
            estimated_finish=(today + timedelta(days=21)).isoformat(),
        )
    )

    print(f"\n== update_story: move story {story_id} into the sprint ==")
    print(await server.update_story(story_id=story_id, sprint_id=sprint.id))
    in_sprint = await client.list_user_stories(project_id=pid, sprint_id=sprint.id)
    assert any(s.id == story_id for s in in_sprint), "story was not added to the sprint"

    print("\n== move_story_to_backlog ==")
    result = await server.move_story_to_backlog(story_id=story_id)
    print(result)
    story = await client.get_story(story_id)
    assert story.milestone is None, "story still has a sprint after the backlog move"

    # Put the story back so the delete below is exercised on a NON-empty
    # sprint — that's the case where detach-vs-cascade actually matters.
    await server.update_story(story_id=story_id, sprint_id=sprint.id)

    print("\n== close_sprint ==")
    print(await server.close_sprint(sprint_id=sprint.id))
    assert (await client.get_sprint(sprint.id)).closed is True, "sprint did not close"

    print("\n== get_sprint (closed) ==")
    print(await server.get_sprint(sprint_id=sprint.id))

    print("\n== delete_sprint (with the story still in it) ==")
    print(await server.delete_sprint(sprint_id=sprint.id))
    remaining = await client.list_sprints(project_id=pid)
    assert not any(s.id == sprint.id for s in remaining), "sprint was not deleted"
    # Taiga's UserStory.milestone is on_delete=SET_NULL, so deleting a sprint
    # must return its stories to the backlog rather than delete them. The
    # delete_sprint tool tells users this — verify it against the real API.
    survivor = await client.get_story(story_id)
    assert survivor.milestone is None, (
        "story kept a milestone pointing at the deleted sprint"
    )


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
        print(
            f"\nUsing smoke project '{smoke.name}' (slug: {smoke.slug}, "
            f"id: {smoke.id}) — FULL lifecycle (writes enabled)."
        )
        await read_only_checks(smoke.id)
        await write_lifecycle(smoke.id)
    else:
        pid = projects[0].id
        print(
            f"\nTAIGA_SMOKE_PROJECT_SLUG not set — READ-ONLY run against "
            f"project {pid}. Set it to a throwaway project to test writes."
        )
        await read_only_checks(pid)


if __name__ == "__main__":
    asyncio.run(main())
