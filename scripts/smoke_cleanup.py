"""Delete whatever a smoke run left behind in the smoke project.

Run with:  uv run python scripts/smoke_cleanup.py

A successful smoke run tears itself down, so this is a no-op after one. It
exists for the runs that do not finish: an assertion failure, a Taiga outage
mid-run or a cancelled CI job abandons whatever had been created up to that
point, and unattended in CI that debris accumulates silently until someone
looks at the project. smoke.yml runs this with `if: always()` for exactly that
reason.

It uses the same TAIGA_SMOKE_* credentials as the smoke test and only ever
touches items whose subject (or name, for sprints) starts with '[smoke ' --
anything else in the project is left alone. Without TAIGA_SMOKE_PROJECT_SLUG
there is no project to clean and it does nothing, which mirrors the smoke
test's own read-only mode.

Deletion order is load-bearing: stories go first so Taiga cascades their tasks,
and tasks are listed only afterwards, so what remains is the loose ones that
never belonged to a story.
"""

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from smoke_test import _smoke_env

from taiga_mcp.auth import authenticate
from taiga_mcp.client import TaigaClient

PREFIX = "[smoke "


def _label(item: Any) -> str:
    """Name an item for logging: epics, stories, tasks and issues carry a
    subject; sprints carry a name."""
    return str(getattr(item, "subject", None) or getattr(item, "name", "?"))


async def _delete_matching(
    kind: str,
    items: list,
    delete: Callable[[int], Awaitable[None]],
    failures: list[str],
) -> int:
    """Delete the smoke-owned items in `items`, returning how many went.

    A failure on one item is collected rather than raised, so a single
    undeletable leftover cannot strand the rest -- the point of this script is
    to leave the project clean, and it reports at the end whether it managed.
    """
    targets = [item for item in items if _label(item).startswith(PREFIX)]
    for item in targets:
        try:
            await delete(item.id)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            failures.append(f"{kind} {item.id} ({_label(item)}): {exc}")
        else:
            print(f"deleted {kind} {_label(item)} (id: {item.id})")
    return len(targets) - len(failures)


async def main() -> None:
    url = _smoke_env("URL")
    username = _smoke_env("USERNAME")
    password = _smoke_env("PASSWORD")
    timeout = float(os.environ.get("TAIGA_TIMEOUT", "30"))

    slug = os.environ.get("TAIGA_SMOKE_PROJECT_SLUG")
    if not slug:
        print("TAIGA_SMOKE_PROJECT_SLUG not set — nothing to clean.")
        return

    token, user_id = await authenticate(url, username, password, timeout)
    client = TaigaClient(url, token, user_id, timeout=timeout)
    try:
        project = next(
            (p for p in await client.list_projects() if p.slug == slug), None
        )
        if project is None:
            raise SystemExit(
                f"TAIGA_SMOKE_PROJECT_SLUG='{slug}' not found on this account."
            )

        pid = project.id
        failures: list[str] = []
        removed = 0
        # Stories first: Taiga cascades their tasks, so the task pass below
        # sees only what was never under a story.
        removed += await _delete_matching(
            "story", await client.list_user_stories(pid), client.delete_story, failures
        )
        removed += await _delete_matching(
            "task", await client.list_tasks(pid), client.delete_task, failures
        )
        removed += await _delete_matching(
            "epic", await client.list_epics(pid), client.delete_epic, failures
        )
        removed += await _delete_matching(
            "issue", await client.list_issues(pid), client.delete_issue, failures
        )
        removed += await _delete_matching(
            "sprint", await client.list_sprints(pid), client.delete_sprint, failures
        )
    finally:
        await client.aclose()

    if failures:
        print(f"\nFailed to delete {len(failures)} item(s):", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        raise SystemExit(1)

    print(f"\nRemoved {removed} leftover item(s) from '{slug}'.")


if __name__ == "__main__":
    asyncio.run(main())
