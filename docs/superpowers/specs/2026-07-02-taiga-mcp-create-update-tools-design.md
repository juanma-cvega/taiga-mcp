# Taiga MCP: create, get, and update tools for epics & stories

**Date:** 2026-07-02
**Status:** Approved design, pending implementation plan

## Motivation

The Taiga MCP server is currently read-and-list only (`list_projects`,
`list_epics`, `list_user_stories`, `list_tasks`, `get_current_sprint`). To
drive work forward from a harness we need to *create* epics and stories, fetch
a *single* one by id, and *update* existing ones — including moving a ticket's
status forward through the project workflow.

## Scope

Six new tools, mirroring the existing `list_*` layering
(model → `TaigaClient` method → `@mcp.tool()` → tests):

| Tool | Verb | Identifier |
| --- | --- | --- |
| `create_epic` | `POST /epics` | `project_id` (new object) |
| `create_story` | `POST /userstories` | `project_id` (new object) |
| `get_epic` | `GET /epics/{id}` | `epic_id` |
| `get_story` | `GET /userstories/{id}` | `story_id` |
| `update_epic` | `PATCH /epics/{id}` | `epic_id` |
| `update_story` | `PATCH /userstories/{id}` | `story_id` |

Identifier strategy:

- **create** takes `project_id` because the object does not exist yet.
- **get / update** are keyed by the object's numeric **id** only. A single
  story/epic is fetched directly (`GET .../{id}`) rather than via a filtered
  list, and the fetched object carries its own `project`, `version`, and
  `status`, so no `project_id` or `ref` argument is needed on those tools.

## Taiga API facts this design relies on

1. **Statuses are per-project, customizable, and flat-ordered.** Epic statuses
   live at `/epic-statuses?project=X`, user-story statuses at
   `/userstory-statuses?project=X`. Each has `id`, `name`, `is_closed`, and an
   `order`. There is no branching workflow — statuses are the kanban columns in
   `order`. Callers set status **by name**; the tool resolves the name to that
   project's status id.
2. **Writes use optimistic locking.** `PATCH` requires the object's current
   `version`. Every update therefore does a `GET` first to read `id`, `version`,
   `project`, and current `status`.
3. **Epic ↔ story links are a separate relation.** A story is attached to an
   epic via `POST /epics/{epic_id}/related_userstories` with
   `{epic, user_story}`, not through a field on the story create payload.

## Tool specifications

### Partial-update semantics (shared by both `update_*` tools)

- Every field is optional and defaults to `None`.
- `None` → **leave unchanged** (field is omitted from the PATCH payload).
- `''` (empty string) → **clear** the value (sent as `null`/empty). Applies to
  nullable text fields: `description`, `blocked_note`, `color`.
- `status` is a **name**; it is resolved to the project's status id. `status`
  cannot be cleared (Taiga requires a status). To move a ticket forward the
  caller passes the target status name explicitly — the harness reads the
  current status via `get_story`/`get_epic` (or a prior list) and decides the
  target. There is no auto-advance in the tool.

### `create_epic`

```
create_epic(project_id, subject, description=None, status=None,
            assigned_to=None, tags=None, is_blocked=None,
            blocked_note=None, color=None)
```

- `POST /epics` with `{project, subject}` plus any non-`None` optional fields.
- `status` name resolved against `/epic-statuses?project=project_id`; omitted →
  Taiga applies the project default.
- Returns the created epic's `#ref` and id.

### `create_story`

```
create_story(project_id, subject, description=None, status=None,
             sprint_id=None, epic_id=None, assigned_to=None,
             tags=None, is_blocked=None, blocked_note=None)
```

- `POST /userstories` with `{project, subject}` plus non-`None` optionals.
- `sprint_id` maps to the `milestone` field (consistent with
  `list_user_stories`).
- `status` name resolved against `/userstory-statuses?project=project_id`.
- `epic_id` is optional (stories may live outside an epic). When given, a
  second call `POST /epics/{epic_id}/related_userstories` links the new story.
- Returns the created story's `#ref` and id.

### `get_epic` / `get_story`

```
get_epic(epic_id)
get_story(story_id)
```

- `GET /epics/{id}` / `GET /userstories/{id}`.
- Return the full, human-readable field set (ref, subject, status, description,
  tags, assigned_to, is_blocked/blocked_note, project, and — for stories —
  milestone/epic linkage).

### `update_epic` / `update_story`

```
update_epic(epic_id, subject=None, description=None, status=None,
            assigned_to=None, tags=None, is_blocked=None,
            blocked_note=None, color=None)

update_story(story_id, subject=None, description=None, status=None,
             sprint_id=None, assigned_to=None, tags=None,
             is_blocked=None, blocked_note=None)
```

Mechanics:

1. `GET /{type}/{id}` → `project`, `version`, current `status`.
2. If `status` was passed, `GET /{type}-statuses?project=<project>` and resolve
   the name to an id.
3. Build the PATCH payload: `version` + every field whose argument is not
   `None` (`''` becomes an explicit clear). `sprint_id` maps to `milestone`.
4. `PATCH /{type}/{id}`.
5. Return the updated `#ref` and its resulting status.

## Models

Extend `models.py`. `Epic` already exists; broaden it (and `UserStory`) to
carry the additional readable fields returned by the single-object GET
(`description`, `tags`, `is_blocked`, `blocked_note`, `assigned_to`, `color`
for epics, `milestone`/`milestone_name` already present for stories). Keep the
existing `status` property deriving from `status_extra_info`. New fields are
optional with defaults so existing list parsing is unaffected.

## Client methods

Add to `TaigaClient`:

- `create_epic(...)`, `create_story(...)` — build payload, `POST`, return model.
- `get_epic(epic_id)`, `get_story(story_id)` — `GET` single object.
- `update_epic(...)`, `update_story(...)` — GET-for-version, optional status
  resolution, `PATCH`.
- Private helpers: `_epic_statuses(project)` / `_story_statuses(project)` for
  name→id resolution, and a shared payload builder honoring the
  `None`=omit / `''`=clear rule.

Writes use `self._headers`; unlike `_get`, POST/PATCH hit a single URL (no
pagination). Reuse the existing `httpx.AsyncClient` pattern.

## Error handling

- Unknown status name → raise a clear error listing the project's valid status
  names.
- `GET` of a missing id → surface Taiga's 404 as a readable "not found" message.
- `PATCH` 400/409 (stale version) → surface Taiga's error text so the caller can
  re-fetch and retry.

## Out of scope (deliberately excluded)

- Internal board-ordering fields (`backlog_order`, `kanban_order`,
  `epics_order`) and estimation `points`.
- `assigned_to` accepts a **numeric user id** only; username→id resolution is
  not included.
- No auto-advance / next-status helper — the caller always passes `None` or an
  explicit target.
- Delete operations.

## Testing

Mirror the existing `respx`-mocked suites:

- **Client tests:** create payload shape (required + optionals, `None` omitted),
  status name→id resolution, `get_*` single-object parse, update round-trip
  (GET-version → PATCH), `''`-clears vs `None`-omits, `sprint_id`→`milestone`
  mapping, `epic_id` link call on `create_story`, unknown-status error.
- **Tool tests:** output formatting and argument pass-through for all six tools,
  using an `AsyncMock` client (as in `tests/test_tools.py`).

All tests must pass (`uv run pytest`) before the work is considered complete.
