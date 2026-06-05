# Taiga MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local MCP server in Python that wraps the Taiga REST API, giving Claude Code native tool access to read projects, user stories, tasks, and sprints from a personal Taiga account.

**Architecture:** A stdio MCP server using the official `mcp` Python SDK. Claude Code launches it as a subprocess and communicates over stdin/stdout. The server authenticates with Taiga on startup using credentials from environment variables, caches the auth token in memory for the lifetime of the process, and exposes four read-only tools. No persistence.

**Tech Stack:** Python 3.10+, `uv` (package manager), `mcp[cli]` (Anthropic MCP SDK), `httpx` (async HTTP client), `pydantic` (response models), `python-dotenv` (env vars), `pytest` + `pytest-asyncio` + `respx` (tests)

---

## Background: how MCP works

Three moving parts worth understanding before writing code:

1. **MCP server** — a process that declares *tools* (typed async functions Claude can call). Your Python script is this process.
2. **Transport** — how Claude Code talks to the server. `stdio` means Claude Code launches your script as a subprocess and communicates over stdin/stdout. No port, no network.
3. **Registration** — you run `claude mcp add` once. After that Claude Code launches the server automatically at the start of every session.

The SDK reads each tool's type annotations and docstring to build the JSON schema Claude sees. Good docstrings = Claude knows when and how to call the tool.

---

## File structure

```
taiga-mcp/
├── docs/plans/                     ← this file
├── src/
│   └── taiga_mcp/
│       ├── __init__.py
│       ├── server.py               ← MCP entry point, tool registration
│       ├── auth.py                 ← token fetch from Taiga /auth
│       ├── client.py               ← httpx calls to Taiga REST API
│       └── models.py               ← Pydantic models for API responses
├── tests/
│   ├── conftest.py                 ← shared fixtures
│   ├── test_auth.py
│   ├── test_client.py
│   └── test_tools.py
├── pyproject.toml
└── .env.example
```

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml` (via `uv init`)
- Create: `src/taiga_mcp/__init__.py`
- Create: `.env.example`

- [ ] **Step 1: Initialise with uv**

```bash
cd ~/workspace/taiga-mcp
uv init --name taiga-mcp --python 3.10
```

- [ ] **Step 2: Add dependencies**

```bash
uv add "mcp[cli]" httpx pydantic python-dotenv
uv add --dev pytest pytest-asyncio respx
```

- [ ] **Step 3: Create package and test directories**

```bash
mkdir -p src/taiga_mcp tests
touch src/taiga_mcp/__init__.py tests/__init__.py
```

- [ ] **Step 4: Add pytest config to `pyproject.toml`**

Append to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 5: Create `.env.example`**

```
TAIGA_URL=https://api.taiga.io/api/v1
TAIGA_USERNAME=your_username
TAIGA_PASSWORD=your_password
```

- [ ] **Step 6: Verify setup**

```bash
uv run pytest --collect-only
```

Expected: `no tests ran` — no errors.

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "chore: scaffold project with uv and dependencies"
```

---

## Task 2: Taiga authentication

**Files:**
- Create: `src/taiga_mcp/auth.py`
- Create: `tests/test_auth.py`

Taiga auth works by `POST /auth` with username + password, which returns an `auth_token`. Every subsequent request sends `Authorization: Bearer <token>`. We fetch once at startup and hold it in memory.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth.py`:
```python
import pytest
import respx
import httpx
from taiga_mcp.auth import fetch_token

TAIGA_URL = "https://api.taiga.io/api/v1"


@respx.mock
async def test_fetch_token_returns_auth_token():
    respx.post(f"{TAIGA_URL}/auth").mock(
        return_value=httpx.Response(200, json={"auth_token": "test-token-123"})
    )
    token = await fetch_token(TAIGA_URL, "user", "pass")
    assert token == "test-token-123"


@respx.mock
async def test_fetch_token_raises_on_bad_credentials():
    respx.post(f"{TAIGA_URL}/auth").mock(
        return_value=httpx.Response(400, json={"_error_message": "Invalid credentials"})
    )
    with pytest.raises(RuntimeError, match="Authentication failed"):
        await fetch_token(TAIGA_URL, "user", "wrong")
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_auth.py -v
```

Expected: `ImportError` — `taiga_mcp.auth` does not exist yet.

- [ ] **Step 3: Implement `src/taiga_mcp/auth.py`**

```python
import httpx


async def fetch_token(base_url: str, username: str, password: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/auth",
            json={"type": "normal", "username": username, "password": password},
        )
    if response.status_code != 200:
        raise RuntimeError(f"Authentication failed: {response.text}")
    return response.json()["auth_token"]
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest tests/test_auth.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/taiga_mcp/auth.py tests/test_auth.py
git commit -m "feat: taiga auth token fetch"
```

---

## Task 3: Taiga API client

**Files:**
- Create: `src/taiga_mcp/models.py`
- Create: `src/taiga_mcp/client.py`
- Create: `tests/conftest.py`
- Create: `tests/test_client.py`

- [ ] **Step 1: Write `src/taiga_mcp/models.py`**

```python
from pydantic import BaseModel


class Project(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None


class Sprint(BaseModel):
    id: int
    name: str
    project: int
    closed: bool
    estimated_start: str | None = None
    estimated_finish: str | None = None


class UserStory(BaseModel):
    id: int
    ref: int
    subject: str
    project: int
    milestone: int | None = None
    milestone_name: str | None = None
    status_extra_info: dict | None = None

    @property
    def status(self) -> str:
        if self.status_extra_info:
            return self.status_extra_info.get("name", "unknown")
        return "unknown"


class Task(BaseModel):
    id: int
    ref: int
    subject: str
    project: int
    user_story: int | None = None
    status_extra_info: dict | None = None

    @property
    def status(self) -> str:
        if self.status_extra_info:
            return self.status_extra_info.get("name", "unknown")
        return "unknown"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/conftest.py`:
```python
import pytest

TAIGA_URL = "https://api.taiga.io/api/v1"
TOKEN = "test-token"


@pytest.fixture
def taiga_url():
    return TAIGA_URL


@pytest.fixture
def token():
    return TOKEN
```

Create `tests/test_client.py`:
```python
import pytest
import respx
import httpx
from taiga_mcp.client import TaigaClient

TAIGA_URL = "https://api.taiga.io/api/v1"
TOKEN = "test-token"


@respx.mock
async def test_list_projects():
    respx.get(f"{TAIGA_URL}/projects").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "Booking Engine", "slug": "booking-engine", "description": "My project"}
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN)
    projects = await client.list_projects()
    assert len(projects) == 1
    assert projects[0].name == "Booking Engine"


@respx.mock
async def test_list_sprints():
    respx.get(f"{TAIGA_URL}/milestones").mock(
        return_value=httpx.Response(200, json=[
            {"id": 10, "name": "Sprint 1", "project": 1, "closed": False,
             "estimated_start": "2026-06-01", "estimated_finish": "2026-06-14"}
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN)
    sprints = await client.list_sprints(project_id=1)
    assert sprints[0].name == "Sprint 1"
    assert sprints[0].closed is False


@respx.mock
async def test_list_user_stories():
    respx.get(f"{TAIGA_URL}/userstories").mock(
        return_value=httpx.Response(200, json=[
            {"id": 5, "ref": 3, "subject": "As a user I want to book a slot", "project": 1,
             "milestone": 10, "milestone_name": "Sprint 1",
             "status_extra_info": {"name": "In progress"}}
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN)
    stories = await client.list_user_stories(project_id=1)
    assert stories[0].subject == "As a user I want to book a slot"
    assert stories[0].status == "In progress"


@respx.mock
async def test_list_tasks():
    respx.get(f"{TAIGA_URL}/tasks").mock(
        return_value=httpx.Response(200, json=[
            {"id": 20, "ref": 7, "subject": "Implement endpoint", "project": 1,
             "user_story": 5, "status_extra_info": {"name": "Done"}}
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN)
    tasks = await client.list_tasks(project_id=1, user_story_id=5)
    assert tasks[0].subject == "Implement endpoint"
    assert tasks[0].status == "Done"
```

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest tests/test_client.py -v
```

Expected: `ImportError` — `taiga_mcp.client` does not exist yet.

- [ ] **Step 4: Implement `src/taiga_mcp/client.py`**

```python
import httpx
from taiga_mcp.models import Project, Sprint, UserStory, Task


class TaigaClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url
        self._headers = {"Authorization": f"Bearer {token}"}

    async def list_projects(self) -> list[Project]:
        data = await self._get("/projects")
        return [Project(**item) for item in data]

    async def list_sprints(self, project_id: int, closed: bool | None = None) -> list[Sprint]:
        params: dict = {"project": project_id}
        if closed is not None:
            params["closed"] = str(closed).lower()
        data = await self._get("/milestones", params=params)
        return [Sprint(**item) for item in data]

    async def list_user_stories(
        self,
        project_id: int,
        sprint_id: int | None = None,
        status: str | None = None,
    ) -> list[UserStory]:
        params: dict = {"project": project_id}
        if sprint_id is not None:
            params["milestone"] = sprint_id
        if status is not None:
            params["status__is_closed"] = "false" if status == "open" else "true"
        data = await self._get("/userstories", params=params)
        return [UserStory(**item) for item in data]

    async def list_tasks(
        self,
        project_id: int,
        user_story_id: int | None = None,
    ) -> list[Task]:
        params: dict = {"project": project_id}
        if user_story_id is not None:
            params["user_story"] = user_story_id
        data = await self._get("/tasks", params=params)
        return [Task(**item) for item in data]

    async def _get(self, path: str, params: dict | None = None) -> list:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}{path}",
                headers=self._headers,
                params=params,
            )
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest tests/test_client.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/taiga_mcp/models.py src/taiga_mcp/client.py tests/conftest.py tests/test_client.py
git commit -m "feat: taiga API client with pydantic models"
```

---

## Task 4: MCP server and tools

**Files:**
- Create: `src/taiga_mcp/server.py`
- Create: `tests/test_tools.py`

Each tool is an async function decorated with `@mcp.tool()`. The SDK generates the JSON schema Claude sees from the type annotations and docstring — write clear docstrings, they directly affect how well Claude decides to use each tool.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools.py`:
```python
import pytest
from unittest.mock import AsyncMock
from taiga_mcp import server
from taiga_mcp.models import Project, Sprint, UserStory, Task


@pytest.fixture(autouse=True)
def mock_client(monkeypatch):
    mock = AsyncMock()
    mock.list_projects.return_value = []
    mock.list_user_stories.return_value = []
    mock.list_tasks.return_value = []
    mock.list_sprints.return_value = []
    monkeypatch.setattr(server, "_client", mock)
    return mock


async def test_list_projects_formats_output(mock_client):
    mock_client.list_projects.return_value = [
        Project(id=1, name="Booking Engine", slug="booking-engine", description="My project")
    ]
    result = await server.list_projects()
    assert "Booking Engine" in result
    assert "booking-engine" in result


async def test_list_projects_empty(mock_client):
    result = await server.list_projects()
    assert "No projects found" in result


async def test_list_user_stories_passes_filters(mock_client):
    await server.list_user_stories(project_id=1, sprint_id=10, status="open")
    mock_client.list_user_stories.assert_called_once_with(
        project_id=1, sprint_id=10, status="open"
    )


async def test_list_tasks_passes_user_story_filter(mock_client):
    await server.list_tasks(project_id=1, user_story_id=5)
    mock_client.list_tasks.assert_called_once_with(project_id=1, user_story_id=5)


async def test_get_current_sprint_formats_output(mock_client):
    mock_client.list_sprints.return_value = [
        Sprint(id=10, name="Sprint 1", project=1, closed=False,
               estimated_start="2026-06-01", estimated_finish="2026-06-14")
    ]
    result = await server.get_current_sprint(project_id=1)
    assert "Sprint 1" in result
    assert "2026-06-14" in result


async def test_get_current_sprint_no_open_sprint(mock_client):
    result = await server.get_current_sprint(project_id=1)
    assert "No open sprint" in result
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_tools.py -v
```

Expected: `ImportError` — `taiga_mcp.server` does not exist yet.

- [ ] **Step 3: Implement `src/taiga_mcp/server.py`**

```python
import asyncio
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from taiga_mcp.auth import fetch_token
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
    token = await fetch_token(base_url, username, password)
    _client = TaigaClient(base_url, token)


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
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest tests/test_tools.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Run all tests**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/taiga_mcp/server.py tests/test_tools.py
git commit -m "feat: MCP server with list_projects, list_user_stories, list_tasks, get_current_sprint"
```

---

## Task 5: Entry point and Claude Code registration

**Files:**
- Modify: `pyproject.toml` — add `[project.scripts]`

- [ ] **Step 1: Add the script entry point**

Add to `pyproject.toml`:
```toml
[project.scripts]
taiga-mcp = "taiga_mcp.server:main"
```

- [ ] **Step 2: Install the package in development mode**

```bash
uv pip install -e .
```

- [ ] **Step 3: Create your `.env` from the template and fill in credentials**

```bash
cp .env.example .env
# open .env and add your Taiga username and password
```

- [ ] **Step 4: Register the server with Claude Code**

```bash
claude mcp add taiga -- uv run --directory ~/workspace/taiga-mcp taiga-mcp
```

`--directory` ensures `.env` is found relative to the project root regardless of where Claude Code is launched from.

- [ ] **Step 5: Verify registration**

```bash
claude mcp list
```

Expected: `taiga` appears in the list with status `✓ Connected`.

- [ ] **Step 6: Smoke test**

Start a new Claude Code session and ask:

> "List my Taiga projects"

Expected: Claude calls `list_projects` and returns your project names.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add entry point and Claude Code registration"
```
