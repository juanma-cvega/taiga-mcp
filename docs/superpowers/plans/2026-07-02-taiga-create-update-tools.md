# Taiga Create/Get/Update Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six MCP tools to the Taiga server — `create_epic`, `create_story`, `get_epic`, `get_story`, `update_epic`, `update_story` — so a harness can create and mutate epics and stories, not just list them.

**Architecture:** Follow the existing three-layer pattern: Pydantic models in `models.py`, HTTP calls in `TaigaClient` (`client.py`), thin `@mcp.tool()` wrappers in `server.py`. Get/update are keyed by numeric id; create takes `project_id`. Writes use Taiga's optimistic locking (GET for `version` → PATCH) and resolve status **names** to per-project status ids.

**Tech Stack:** Python ≥3.10, httpx (async), pydantic v2, mcp[cli] (FastMCP), pytest + pytest-asyncio + respx.

## Global Constraints

- Python `>=3.10`; async throughout (`asyncio_mode = "auto"` in pytest config).
- All HTTP goes through `httpx.AsyncClient` with `self._headers` (Bearer token).
- Partial-update rule: argument `None` → omit field from payload; `''` → clear (send `null`); any other value → set it.
- `status` is always a **name**, resolved to the project's status id; it is never cleared.
- `assigned_to` is a numeric user id.
- `sprint_id` maps to the Taiga `milestone` field.
- Excluded: board-ordering fields (`backlog_order`, `kanban_order`, `epics_order`), `points`, username→id resolution, delete operations.
- Tests mock HTTP with `respx`; tool tests mock the client with `AsyncMock`.
- Commit after each task. Do not push (stay on `main`).

---

### Task 1: Broaden `Epic` and `UserStory` models

**Files:**
- Modify: `src/taiga_mcp/models.py` (the `UserStory` class and the `Epic` class)
- Test: `tests/test_models.py` (create)

**Interfaces:**
- Produces: `Epic` and `UserStory` now expose optional `description: str | None`, `tags: list | None`, `is_blocked: bool | None`, `blocked_note: str | None`, `assigned_to: int | None`, `version: int | None`. `Epic` additionally exposes `color: str | None`. Existing fields and the `status` property are unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
from taiga_mcp.models import Epic, UserStory


def test_epic_parses_detail_fields():
    e = Epic(
        id=1, ref=5, subject="Epic A", project=10,
        description="details", tags=[["urgent", "#f00"]], is_blocked=True,
        blocked_note="waiting", assigned_to=42, color="#123456", version=3,
        status_extra_info={"name": "New"},
    )
    assert e.description == "details"
    assert e.color == "#123456"
    assert e.is_blocked is True
    assert e.version == 3
    assert e.status == "New"


def test_user_story_parses_detail_fields():
    s = UserStory(
        id=2, ref=9, subject="Story A", project=10,
        description="story details", tags=None, is_blocked=False,
        blocked_note=None, assigned_to=None, version=7,
        status_extra_info={"name": "In progress"},
    )
    assert s.description == "story details"
    assert s.version == 7
    assert s.status == "In progress"


def test_models_ignore_unknown_fields():
    # Taiga returns many fields we don't model; parsing must not fail.
    e = Epic(id=1, ref=5, subject="X", project=10, some_unmodeled_field=123)
    assert e.subject == "X"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `Epic`/`UserStory` reject `description`/`color`/`version` (pydantic ignores extras by default, so the assertions on `.description` etc. fail with `AttributeError`).

- [ ] **Step 3: Add the fields**

In `src/taiga_mcp/models.py`, replace the `UserStory` class body's field block (keep the `status` property) so it reads:

```python
class UserStory(BaseModel):
    id: int
    ref: int
    subject: str
    project: int
    milestone: int | None = None
    milestone_name: str | None = None
    description: str | None = None
    tags: list | None = None
    is_blocked: bool | None = None
    blocked_note: str | None = None
    assigned_to: int | None = None
    version: int | None = None
    status_extra_info: dict | None = None

    @property
    def status(self) -> str:
        if self.status_extra_info:
            return self.status_extra_info.get("name", "unknown")
        return "unknown"
```

And replace the `Epic` class similarly:

```python
class Epic(BaseModel):
    id: int
    ref: int
    subject: str
    project: int
    description: str | None = None
    tags: list | None = None
    is_blocked: bool | None = None
    blocked_note: str | None = None
    assigned_to: int | None = None
    color: str | None = None
    version: int | None = None
    status_extra_info: dict | None = None

    @property
    def status(self) -> str:
        if self.status_extra_info:
            return self.status_extra_info.get("name", "unknown")
        return "unknown"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `uv run pytest -q`
Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/taiga_mcp/models.py tests/test_models.py
git commit -m "feat: add detail fields to Epic and UserStory models"
```

---

### Task 2: Client write/read primitives and shared helpers

**Files:**
- Modify: `src/taiga_mcp/client.py` (add module-level `_build_payload`; add `_get_one`, `_post`, `_patch`, `_resolve_status` methods to `TaigaClient`, placed just above the existing `_get` method)
- Test: `tests/test_client.py` (append)

**Interfaces:**
- Consumes: `self._base_url`, `self._headers` (already on `TaigaClient`).
- Produces:
  - `_build_payload(fields: dict) -> dict` — module-level. Drops keys whose value is `None`; maps `''` to `None`; keeps everything else.
  - `async _get_one(self, path: str) -> dict` — single-object GET.
  - `async _post(self, path: str, json: dict) -> dict`.
  - `async _patch(self, path: str, json: dict) -> dict`.
  - `async _resolve_status(self, status_endpoint: str, project_id: int, name: str) -> int` — GETs `status_endpoint?project=project_id`, returns the id whose `name` matches, else raises `ValueError` listing valid names. `status_endpoint` is `"/epic-statuses"` or `"/userstory-statuses"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_client.py`:

```python
from taiga_mcp.client import _build_payload


def test_build_payload_omits_none_and_clears_empty_string():
    result = _build_payload({
        "a": None,        # omitted
        "b": "",          # cleared -> None
        "c": "value",     # kept
        "d": 0,           # kept (not treated as empty)
        "e": False,       # kept
        "f": [],          # kept
    })
    assert result == {"b": None, "c": "value", "d": 0, "e": False, "f": []}


@respx.mock
async def test_resolve_status_returns_matching_id():
    respx.get(f"{TAIGA_URL}/userstory-statuses").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "New"}, {"id": 2, "name": "In progress"},
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    status_id = await client._resolve_status("/userstory-statuses", 10, "In progress")
    assert status_id == 2


@respx.mock
async def test_resolve_status_unknown_name_raises_with_valid_names():
    respx.get(f"{TAIGA_URL}/epic-statuses").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "New"}, {"id": 2, "name": "Done"},
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(ValueError) as exc:
        await client._resolve_status("/epic-statuses", 10, "Bogus")
    assert "New" in str(exc.value) and "Done" in str(exc.value)


@respx.mock
async def test_post_returns_json_body():
    respx.post(f"{TAIGA_URL}/epics").mock(
        return_value=httpx.Response(201, json={"id": 99, "ref": 3})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    data = await client._post("/epics", {"subject": "X"})
    assert data == {"id": 99, "ref": 3}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -k "build_payload or resolve_status or post_returns" -v`
Expected: FAIL — `_build_payload` import fails / methods undefined.

- [ ] **Step 3: Implement the helpers**

In `src/taiga_mcp/client.py`, add this module-level function after the imports:

```python
def _build_payload(fields: dict) -> dict:
    """Build a write payload: drop None (leave unchanged), map '' to None
    (clear the value), keep everything else as-is."""
    payload: dict = {}
    for key, value in fields.items():
        if value is None:
            continue
        payload[key] = None if value == "" else value
    return payload
```

Then, inside `TaigaClient`, immediately above the existing `async def _get` method, add:

```python
    async def _get_one(self, path: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}{path}", headers=self._headers
            )
            response.raise_for_status()
            return response.json()

    async def _post(self, path: str, json: dict) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}{path}", headers=self._headers, json=json
            )
            response.raise_for_status()
            return response.json()

    async def _patch(self, path: str, json: dict) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self._base_url}{path}", headers=self._headers, json=json
            )
            response.raise_for_status()
            return response.json()

    async def _resolve_status(
        self, status_endpoint: str, project_id: int, name: str
    ) -> int:
        statuses = await self._get(status_endpoint, params={"project": project_id})
        for status in statuses:
            if status["name"] == name:
                return status["id"]
        valid = ", ".join(s["name"] for s in statuses)
        raise ValueError(f"Unknown status '{name}'. Valid statuses: {valid}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -k "build_payload or resolve_status or post_returns" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/taiga_mcp/client.py tests/test_client.py
git commit -m "feat: add write/read primitives and status resolution to TaigaClient"
```

---

### Task 3: `get_epic` / `get_story`

**Files:**
- Modify: `src/taiga_mcp/client.py` (add `get_epic`, `get_story` methods)
- Modify: `src/taiga_mcp/server.py` (add two `@mcp.tool()` functions + a shared `_format_detail` helper)
- Test: `tests/test_client.py`, `tests/test_tools.py` (append)

**Interfaces:**
- Consumes: `_get_one` (Task 2), `Epic`/`UserStory` models (Task 1).
- Produces:
  - `async get_epic(self, epic_id: int) -> Epic`
  - `async get_story(self, story_id: int) -> UserStory`
  - Server tools `get_epic(epic_id: int) -> str`, `get_story(story_id: int) -> str`.

- [ ] **Step 1: Write the failing client tests**

Append to `tests/test_client.py`:

```python
@respx.mock
async def test_get_story_fetches_single_object():
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(200, json={
            "id": 2, "ref": 9, "subject": "Story A", "project": 10,
            "description": "details", "version": 4,
            "status_extra_info": {"name": "In progress"},
        })
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    story = await client.get_story(2)
    assert story.ref == 9
    assert story.description == "details"
    assert story.status == "In progress"


@respx.mock
async def test_get_epic_fetches_single_object():
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(200, json={
            "id": 1, "ref": 5, "subject": "Epic A", "project": 10,
            "color": "#123456", "version": 2,
            "status_extra_info": {"name": "New"},
        })
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    epic = await client.get_epic(1)
    assert epic.ref == 5
    assert epic.color == "#123456"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_client.py -k "get_story_fetches or get_epic_fetches" -v`
Expected: FAIL — `get_story`/`get_epic` undefined.

- [ ] **Step 3: Implement client methods**

In `src/taiga_mcp/client.py`, add after `list_epics`:

```python
    async def get_epic(self, epic_id: int) -> Epic:
        return Epic(**await self._get_one(f"/epics/{epic_id}"))

    async def get_story(self, story_id: int) -> UserStory:
        return UserStory(**await self._get_one(f"/userstories/{story_id}"))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_client.py -k "get_story_fetches or get_epic_fetches" -v`
Expected: PASS.

- [ ] **Step 5: Write the failing tool tests**

Append to `tests/test_tools.py` (add `mock_client.get_epic`/`get_story` are `AsyncMock` attributes automatically):

```python
async def test_get_story_formats_detail(mock_client):
    mock_client.get_story.return_value = UserStory(
        id=2, ref=9, subject="Story A", project=10,
        milestone_name="Sprint 1", description="the details",
        is_blocked=True, blocked_note="waiting", assigned_to=42,
        status_extra_info={"name": "In progress"},
    )
    result = await server.get_story(story_id=2)
    assert "#9 Story A" in result
    assert "In progress" in result
    assert "the details" in result
    assert "Sprint 1" in result
    assert "waiting" in result


async def test_get_epic_formats_detail(mock_client):
    mock_client.get_epic.return_value = Epic(
        id=1, ref=5, subject="Epic A", project=10,
        description="epic details", color="#123456",
        status_extra_info={"name": "New"},
    )
    result = await server.get_epic(epic_id=1)
    assert "#5 Epic A" in result
    assert "New" in result
    assert "epic details" in result
```

Also update the imports at the top of `tests/test_tools.py` if needed — `Epic` and `UserStory` are already imported.

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_tools.py -k "get_story_formats or get_epic_formats" -v`
Expected: FAIL — `server.get_story`/`get_epic` undefined.

- [ ] **Step 7: Implement server tools**

In `src/taiga_mcp/server.py`, add a shared formatting helper (module level, after `_get_client`) and two tools. Insert the tools after `list_epics`:

```python
def _format_detail(item) -> str:
    lines = [f"#{item.ref} {item.subject} [{item.status}]"]
    if getattr(item, "milestone_name", None):
        lines.append(f"Sprint: {item.milestone_name}")
    if item.assigned_to is not None:
        lines.append(f"Assigned to: {item.assigned_to}")
    blocked = f"Blocked: {bool(item.is_blocked)}"
    if item.blocked_note:
        blocked += f" ({item.blocked_note})"
    lines.append(blocked)
    lines.append(f"Description:\n{item.description or '—'}")
    return "\n".join(lines)
```

```python
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
```

- [ ] **Step 8: Run to verify pass + full suite**

Run: `uv run pytest tests/test_tools.py -k "get_story_formats or get_epic_formats" -v`
Expected: PASS.
Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/taiga_mcp/client.py src/taiga_mcp/server.py tests/test_client.py tests/test_tools.py
git commit -m "feat: add get_epic and get_story tools"
```

---

### Task 4: `create_epic`

**Files:**
- Modify: `src/taiga_mcp/client.py` (add `create_epic`)
- Modify: `src/taiga_mcp/server.py` (add `create_epic` tool)
- Test: `tests/test_client.py`, `tests/test_tools.py` (append)

**Interfaces:**
- Consumes: `_post`, `_resolve_status`, `_build_payload` (Task 2), `Epic` (Task 1).
- Produces:
  - `async create_epic(self, project_id, subject, description=None, status=None, assigned_to=None, tags=None, is_blocked=None, blocked_note=None, color=None) -> Epic`
  - Server tool `create_epic(...) -> str` returning `"Created #<ref> <subject> (id: <id>)"`.

- [ ] **Step 1: Write the failing client tests**

Append to `tests/test_client.py`:

```python
@respx.mock
async def test_create_epic_posts_required_and_optional_fields():
    respx.get(f"{TAIGA_URL}/epic-statuses").mock(
        return_value=httpx.Response(200, json=[{"id": 7, "name": "New"}])
    )
    route = respx.post(f"{TAIGA_URL}/epics").mock(
        return_value=httpx.Response(201, json={
            "id": 50, "ref": 11, "subject": "New epic", "project": 10,
            "status_extra_info": {"name": "New"},
        })
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    epic = await client.create_epic(
        project_id=10, subject="New epic", description="d", status="New",
    )
    body = json.loads(route.calls.last.request.content)
    assert body["project"] == 10
    assert body["subject"] == "New epic"
    assert body["description"] == "d"
    assert body["status"] == 7          # name resolved to id
    assert "color" not in body          # None omitted
    assert epic.ref == 11


@respx.mock
async def test_create_epic_omits_status_when_not_given():
    route = respx.post(f"{TAIGA_URL}/epics").mock(
        return_value=httpx.Response(201, json={
            "id": 51, "ref": 12, "subject": "X", "project": 10,
        })
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.create_epic(project_id=10, subject="X")
    body = json.loads(route.calls.last.request.content)
    assert "status" not in body
```

Add `import json` at the top of `tests/test_client.py` if not present.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_client.py -k "create_epic" -v`
Expected: FAIL — `create_epic` undefined.

- [ ] **Step 3: Implement client method**

In `src/taiga_mcp/client.py`, add after `get_story`:

```python
    async def create_epic(
        self,
        project_id: int,
        subject: str,
        description: str | None = None,
        status: str | None = None,
        assigned_to: int | None = None,
        tags: list | None = None,
        is_blocked: bool | None = None,
        blocked_note: str | None = None,
        color: str | None = None,
    ) -> Epic:
        payload = {"project": project_id, "subject": subject}
        if status is not None:
            payload["status"] = await self._resolve_status(
                "/epic-statuses", project_id, status
            )
        payload.update(_build_payload({
            "description": description,
            "assigned_to": assigned_to,
            "tags": tags,
            "is_blocked": is_blocked,
            "blocked_note": blocked_note,
            "color": color,
        }))
        return Epic(**await self._post("/epics", payload))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_client.py -k "create_epic" -v`
Expected: PASS.

- [ ] **Step 5: Write the failing tool test**

Append to `tests/test_tools.py`:

```python
async def test_create_epic_returns_created_ref(mock_client):
    mock_client.create_epic.return_value = Epic(
        id=50, ref=11, subject="New epic", project=10,
        status_extra_info={"name": "New"},
    )
    result = await server.create_epic(project_id=10, subject="New epic")
    mock_client.create_epic.assert_called_once()
    assert "#11" in result
    assert "New epic" in result
    assert "50" in result
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_tools.py -k "create_epic_returns" -v`
Expected: FAIL — `server.create_epic` undefined.

- [ ] **Step 7: Implement server tool**

In `src/taiga_mcp/server.py`, add after the `get_story` tool:

```python
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
        project_id=project_id, subject=subject, description=description,
        status=status, assigned_to=assigned_to, tags=tags,
        is_blocked=is_blocked, blocked_note=blocked_note, color=color,
    )
    return f"Created #{epic.ref} {epic.subject} (id: {epic.id})"
```

- [ ] **Step 8: Run to verify pass + full suite**

Run: `uv run pytest tests/test_tools.py -k "create_epic_returns" -v`
Expected: PASS.
Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/taiga_mcp/client.py src/taiga_mcp/server.py tests/test_client.py tests/test_tools.py
git commit -m "feat: add create_epic tool"
```

---

### Task 5: `create_story` (with optional epic link)

**Files:**
- Modify: `src/taiga_mcp/client.py` (add `create_story`)
- Modify: `src/taiga_mcp/server.py` (add `create_story` tool)
- Test: `tests/test_client.py`, `tests/test_tools.py` (append)

**Interfaces:**
- Consumes: `_post`, `_resolve_status`, `_build_payload` (Task 2), `UserStory` (Task 1).
- Produces:
  - `async create_story(self, project_id, subject, description=None, status=None, sprint_id=None, epic_id=None, assigned_to=None, tags=None, is_blocked=None, blocked_note=None) -> UserStory`
  - Server tool `create_story(...) -> str` returning `"Created #<ref> <subject> (id: <id>)"`.

- [ ] **Step 1: Write the failing client tests**

Append to `tests/test_client.py`:

```python
@respx.mock
async def test_create_story_maps_sprint_to_milestone():
    route = respx.post(f"{TAIGA_URL}/userstories").mock(
        return_value=httpx.Response(201, json={
            "id": 60, "ref": 20, "subject": "New story", "project": 10,
        })
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.create_story(project_id=10, subject="New story", sprint_id=99)
    body = json.loads(route.calls.last.request.content)
    assert body["milestone"] == 99
    assert "epic" not in body


@respx.mock
async def test_create_story_links_epic_when_epic_id_given():
    respx.post(f"{TAIGA_URL}/userstories").mock(
        return_value=httpx.Response(201, json={
            "id": 61, "ref": 21, "subject": "Linked story", "project": 10,
        })
    )
    link = respx.post(f"{TAIGA_URL}/epics/5/related_userstories").mock(
        return_value=httpx.Response(201, json={"epic": 5, "user_story": 61})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    story = await client.create_story(project_id=10, subject="Linked story", epic_id=5)
    assert story.id == 61
    assert link.called
    link_body = json.loads(link.calls.last.request.content)
    assert link_body == {"epic": 5, "user_story": 61}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_client.py -k "create_story" -v`
Expected: FAIL — `create_story` undefined.

- [ ] **Step 3: Implement client method**

In `src/taiga_mcp/client.py`, add after `create_epic`:

```python
    async def create_story(
        self,
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
    ) -> UserStory:
        payload = {"project": project_id, "subject": subject}
        if status is not None:
            payload["status"] = await self._resolve_status(
                "/userstory-statuses", project_id, status
            )
        payload.update(_build_payload({
            "description": description,
            "milestone": sprint_id,
            "assigned_to": assigned_to,
            "tags": tags,
            "is_blocked": is_blocked,
            "blocked_note": blocked_note,
        }))
        story = UserStory(**await self._post("/userstories", payload))
        if epic_id is not None:
            await self._post(
                f"/epics/{epic_id}/related_userstories",
                {"epic": epic_id, "user_story": story.id},
            )
        return story
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_client.py -k "create_story" -v`
Expected: PASS.

- [ ] **Step 5: Write the failing tool test**

Append to `tests/test_tools.py`:

```python
async def test_create_story_returns_created_ref(mock_client):
    mock_client.create_story.return_value = UserStory(
        id=60, ref=20, subject="New story", project=10,
        status_extra_info={"name": "New"},
    )
    result = await server.create_story(project_id=10, subject="New story", epic_id=5)
    mock_client.create_story.assert_called_once_with(
        project_id=10, subject="New story", description=None, status=None,
        sprint_id=None, epic_id=5, assigned_to=None, tags=None,
        is_blocked=None, blocked_note=None,
    )
    assert "#20" in result
    assert "New story" in result
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_tools.py -k "create_story_returns" -v`
Expected: FAIL — `server.create_story` undefined.

- [ ] **Step 7: Implement server tool**

In `src/taiga_mcp/server.py`, add after the `create_epic` tool:

```python
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
        project_id=project_id, subject=subject, description=description,
        status=status, sprint_id=sprint_id, epic_id=epic_id,
        assigned_to=assigned_to, tags=tags, is_blocked=is_blocked,
        blocked_note=blocked_note,
    )
    return f"Created #{story.ref} {story.subject} (id: {story.id})"
```

- [ ] **Step 8: Run to verify pass + full suite**

Run: `uv run pytest tests/test_tools.py -k "create_story_returns" -v`
Expected: PASS.
Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/taiga_mcp/client.py src/taiga_mcp/server.py tests/test_client.py tests/test_tools.py
git commit -m "feat: add create_story tool with optional epic linking"
```

---

### Task 6: `update_epic`

**Files:**
- Modify: `src/taiga_mcp/client.py` (add `update_epic`)
- Modify: `src/taiga_mcp/server.py` (add `update_epic` tool)
- Test: `tests/test_client.py`, `tests/test_tools.py` (append)

**Interfaces:**
- Consumes: `_get_one`, `_patch`, `_resolve_status`, `_build_payload` (Task 2), `Epic` (Task 1).
- Produces:
  - `async update_epic(self, epic_id, subject=None, description=None, status=None, assigned_to=None, tags=None, is_blocked=None, blocked_note=None, color=None) -> Epic`
  - Server tool `update_epic(...) -> str` returning `"Updated #<ref> <subject> [<status>]"`.

- [ ] **Step 1: Write the failing client tests**

Append to `tests/test_client.py`:

```python
@respx.mock
async def test_update_epic_sends_version_and_resolves_status():
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(200, json={
            "id": 1, "ref": 5, "subject": "Epic A", "project": 10, "version": 4,
            "status_extra_info": {"name": "New"},
        })
    )
    respx.get(f"{TAIGA_URL}/epic-statuses").mock(
        return_value=httpx.Response(200, json=[{"id": 8, "name": "Done"}])
    )
    route = respx.patch(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(200, json={
            "id": 1, "ref": 5, "subject": "Epic A", "project": 10,
            "status_extra_info": {"name": "Done"},
        })
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    epic = await client.update_epic(1, status="Done")
    body = json.loads(route.calls.last.request.content)
    assert body["version"] == 4
    assert body["status"] == 8
    assert epic.status == "Done"


@respx.mock
async def test_update_epic_clears_field_with_empty_string():
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(200, json={
            "id": 1, "ref": 5, "subject": "Epic A", "project": 10, "version": 4,
        })
    )
    route = respx.patch(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(200, json={
            "id": 1, "ref": 5, "subject": "Epic A", "project": 10,
        })
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_epic(1, blocked_note="")
    body = json.loads(route.calls.last.request.content)
    assert body["blocked_note"] is None      # '' -> cleared
    assert "description" not in body          # None -> omitted
    assert "status" not in body               # not requested -> no status GET
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_client.py -k "update_epic" -v`
Expected: FAIL — `update_epic` undefined.

- [ ] **Step 3: Implement client method**

In `src/taiga_mcp/client.py`, add after `create_story`:

```python
    async def update_epic(
        self,
        epic_id: int,
        subject: str | None = None,
        description: str | None = None,
        status: str | None = None,
        assigned_to: int | None = None,
        tags: list | None = None,
        is_blocked: bool | None = None,
        blocked_note: str | None = None,
        color: str | None = None,
    ) -> Epic:
        current = await self._get_one(f"/epics/{epic_id}")
        payload = {"version": current["version"]}
        if status is not None:
            payload["status"] = await self._resolve_status(
                "/epic-statuses", current["project"], status
            )
        payload.update(_build_payload({
            "subject": subject,
            "description": description,
            "assigned_to": assigned_to,
            "tags": tags,
            "is_blocked": is_blocked,
            "blocked_note": blocked_note,
            "color": color,
        }))
        return Epic(**await self._patch(f"/epics/{epic_id}", payload))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_client.py -k "update_epic" -v`
Expected: PASS.

- [ ] **Step 5: Write the failing tool test**

Append to `tests/test_tools.py`:

```python
async def test_update_epic_returns_updated_status(mock_client):
    mock_client.update_epic.return_value = Epic(
        id=1, ref=5, subject="Epic A", project=10,
        status_extra_info={"name": "Done"},
    )
    result = await server.update_epic(epic_id=1, status="Done")
    mock_client.update_epic.assert_called_once()
    assert "#5 Epic A" in result
    assert "Done" in result
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_tools.py -k "update_epic_returns" -v`
Expected: FAIL — `server.update_epic` undefined.

- [ ] **Step 7: Implement server tool**

In `src/taiga_mcp/server.py`, add after the `create_story` tool:

```python
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
        epic_id, subject=subject, description=description, status=status,
        assigned_to=assigned_to, tags=tags, is_blocked=is_blocked,
        blocked_note=blocked_note, color=color,
    )
    return f"Updated #{epic.ref} {epic.subject} [{epic.status}]"
```

- [ ] **Step 8: Run to verify pass + full suite**

Run: `uv run pytest tests/test_tools.py -k "update_epic_returns" -v`
Expected: PASS.
Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/taiga_mcp/client.py src/taiga_mcp/server.py tests/test_client.py tests/test_tools.py
git commit -m "feat: add update_epic tool"
```

---

### Task 7: `update_story`

**Files:**
- Modify: `src/taiga_mcp/client.py` (add `update_story`)
- Modify: `src/taiga_mcp/server.py` (add `update_story` tool)
- Test: `tests/test_client.py`, `tests/test_tools.py` (append)

**Interfaces:**
- Consumes: `_get_one`, `_patch`, `_resolve_status`, `_build_payload` (Task 2), `UserStory` (Task 1).
- Produces:
  - `async update_story(self, story_id, subject=None, description=None, status=None, sprint_id=None, assigned_to=None, tags=None, is_blocked=None, blocked_note=None) -> UserStory`
  - Server tool `update_story(...) -> str` returning `"Updated #<ref> <subject> [<status>]"`.

- [ ] **Step 1: Write the failing client tests**

Append to `tests/test_client.py`:

```python
@respx.mock
async def test_update_story_maps_sprint_and_sends_version():
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(200, json={
            "id": 2, "ref": 9, "subject": "Story A", "project": 10, "version": 6,
            "status_extra_info": {"name": "New"},
        })
    )
    route = respx.patch(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(200, json={
            "id": 2, "ref": 9, "subject": "Story A", "project": 10,
            "status_extra_info": {"name": "New"},
        })
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_story(2, sprint_id=99)
    body = json.loads(route.calls.last.request.content)
    assert body["version"] == 6
    assert body["milestone"] == 99
    assert "status" not in body
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_client.py -k "update_story_maps" -v`
Expected: FAIL — `update_story` undefined.

- [ ] **Step 3: Implement client method**

In `src/taiga_mcp/client.py`, add after `update_epic`:

```python
    async def update_story(
        self,
        story_id: int,
        subject: str | None = None,
        description: str | None = None,
        status: str | None = None,
        sprint_id: int | None = None,
        assigned_to: int | None = None,
        tags: list | None = None,
        is_blocked: bool | None = None,
        blocked_note: str | None = None,
    ) -> UserStory:
        current = await self._get_one(f"/userstories/{story_id}")
        payload = {"version": current["version"]}
        if status is not None:
            payload["status"] = await self._resolve_status(
                "/userstory-statuses", current["project"], status
            )
        payload.update(_build_payload({
            "subject": subject,
            "description": description,
            "milestone": sprint_id,
            "assigned_to": assigned_to,
            "tags": tags,
            "is_blocked": is_blocked,
            "blocked_note": blocked_note,
        }))
        return UserStory(**await self._patch(f"/userstories/{story_id}", payload))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_client.py -k "update_story_maps" -v`
Expected: PASS.

- [ ] **Step 5: Write the failing tool test**

Append to `tests/test_tools.py`:

```python
async def test_update_story_returns_updated_status(mock_client):
    mock_client.update_story.return_value = UserStory(
        id=2, ref=9, subject="Story A", project=10,
        status_extra_info={"name": "In progress"},
    )
    result = await server.update_story(story_id=2, status="In progress")
    mock_client.update_story.assert_called_once()
    assert "#9 Story A" in result
    assert "In progress" in result
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_tools.py -k "update_story_returns" -v`
Expected: FAIL — `server.update_story` undefined.

- [ ] **Step 7: Implement server tool**

In `src/taiga_mcp/server.py`, add after the `update_epic` tool:

```python
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
        story_id, subject=subject, description=description, status=status,
        sprint_id=sprint_id, assigned_to=assigned_to, tags=tags,
        is_blocked=is_blocked, blocked_note=blocked_note,
    )
    return f"Updated #{story.ref} {story.subject} [{story.status}]"
```

- [ ] **Step 8: Run to verify pass + full suite**

Run: `uv run pytest tests/test_tools.py -k "update_story_returns" -v`
Expected: PASS.
Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/taiga_mcp/client.py src/taiga_mcp/server.py tests/test_client.py tests/test_tools.py
git commit -m "feat: add update_story tool"
```

---

### Task 8: Update the README tool table

**Files:**
- Modify: `README.md` (the Tools table)

**Interfaces:**
- Consumes: nothing. Documentation only.

- [ ] **Step 1: Add the new tools to the table**

In `README.md`, under the `## Tools` table, add these rows after the existing ones:

```markdown
| `create_epic` | `project_id`, `subject`, + optional `description`, `status`, `assigned_to`, `tags`, `is_blocked`, `blocked_note`, `color` | Create an epic. `status` is a status name. |
| `create_story` | `project_id`, `subject`, + optional `description`, `status`, `sprint_id`, `epic_id`, `assigned_to`, `tags`, `is_blocked`, `blocked_note` | Create a story, optionally linked to an epic. |
| `get_epic` | `epic_id` | Get a single epic by id with its full field set. |
| `get_story` | `story_id` | Get a single story by id with its full field set. |
| `update_epic` | `epic_id`, + any field to change | Update an epic. `None` leaves a field unchanged; `''` clears it. |
| `update_story` | `story_id`, + any field to change | Update a story. `None` leaves a field unchanged; `''` clears it. |
```

- [ ] **Step 2: Verify the suite is green**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document create/get/update epic & story tools"
```

---

## Self-Review

**Spec coverage:**
- create_epic → Task 4 ✓; create_story (+ epic link) → Task 5 ✓; get_epic/get_story → Task 3 ✓; update_epic → Task 6 ✓; update_story → Task 7 ✓.
- Partial-update semantics (`None`=omit, `''`=clear) → `_build_payload` (Task 2), verified in Task 6 clear test ✓.
- Status name→id resolution → `_resolve_status` (Task 2), verified in Tasks 4 & 6 ✓.
- Optimistic locking (GET version → PATCH) → Tasks 6 & 7 ✓.
- id-based get/update, project-based create → signatures throughout ✓.
- `sprint_id`→`milestone` mapping → Tasks 5 & 7 ✓.
- Models carry detail fields for get formatting → Task 1 ✓.
- Excluded fields (ordering, points, username resolution) → not added anywhere ✓.
- Error handling: unknown status name raises with valid names → Task 2 test ✓. (404/409 surface via `raise_for_status`, no extra code needed.)

**Placeholder scan:** No TBD/TODO; every code step shows full code; no "similar to Task N" references. ✓

**Type consistency:** `_build_payload`, `_get_one`, `_post`, `_patch`, `_resolve_status` signatures are defined in Task 2 and consumed with matching names/args in Tasks 3–7. `_resolve_status` always called with a leading-slash endpoint (`"/epic-statuses"`, `"/userstory-statuses"`). Model field names (`description`, `color`, `version`, `milestone_name`, `is_blocked`, `blocked_note`, `assigned_to`) match between Task 1 definitions and later usage. Client method names match server call sites. ✓
