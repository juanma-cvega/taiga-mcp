# taiga-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes read-only access
to a [Taiga](https://taiga.io) account — projects, epics, user stories, tasks,
and sprints — as tools an MCP client (e.g. Claude Code) can call.

## Requirements

- Python >= 3.10
- [uv](https://docs.astral.sh/uv/)
- A Taiga account (Taiga Cloud or self-hosted)

## Setup

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

```dotenv
TAIGA_URL=https://api.taiga.io/api/v1
TAIGA_USERNAME=your_username
TAIGA_PASSWORD=your_password
```

`TAIGA_URL` is the base API URL. For Taiga Cloud use
`https://api.taiga.io/api/v1`; for a self-hosted instance point it at your
server's `/api/v1`.

## Running

```bash
uv run taiga-mcp
```

The server authenticates on startup (exchanging username/password for a token)
and speaks MCP over stdio.

### Registering with Claude Code

```bash
claude mcp add taiga -- uv run --directory /path/to/taiga-mcp taiga-mcp
```

## Tools

| Tool | Arguments | Description |
| --- | --- | --- |
| `list_projects` | — | List all projects accessible to the authenticated user. |
| `list_epics` | `project_id` | List epics for a project. |
| `list_user_stories` | `project_id`, `sprint_id?`, `status?` (`open`/`closed`) | List user stories for a project, optionally filtered by sprint or status. |
| `list_tasks` | `project_id`, `user_story_id?` | List tasks for a project, optionally scoped to a user story. |
| `get_current_sprint` | `project_id` | Get the currently open sprint for a project. |
| `create_epic` | `project_id`, `subject`, + optional `description`, `status`, `assigned_to`, `tags`, `is_blocked`, `blocked_note`, `color` | Create an epic. `status` is a status name. |
| `create_story` | `project_id`, `subject`, + optional `description`, `status`, `sprint_id`, `epic_id`, `assigned_to`, `tags`, `is_blocked`, `blocked_note` | Create a story, optionally linked to an epic. |
| `get_epic` | `epic_id` | Get a single epic by id with its full field set. |
| `get_story` | `story_id` | Get a single story by id with its full field set. |
| `update_epic` | `epic_id`, + any field to change | Update an epic. `None` leaves a field unchanged; `''` clears it. |
| `update_story` | `story_id`, + any field to change | Update a story. `None` leaves a field unchanged; `''` clears it. |

All list tools follow Taiga's pagination automatically, and `list_projects` is
scoped to the authenticated user (an unfiltered query would return every public
project on the platform).

## Development

Run the test suite:

```bash
uv run pytest
```

There is also a manual smoke test that hits a real Taiga account. It
authenticates with its **own** credentials, separate from the MCP server's, so
you can point it at a throwaway project on a different account:

- Server: `TAIGA_URL` / `TAIGA_USERNAME` / `TAIGA_PASSWORD`
- Smoke test: `TAIGA_SMOKE_URL` / `TAIGA_SMOKE_USERNAME` / `TAIGA_SMOKE_PASSWORD`
  (each falls back to the corresponding `TAIGA_*` value if unset)

By default it is **read-only** — it lists projects and exercises the read tools
against the first project without mutating anything:

```bash
uv run python scripts/smoke_test.py
```

To exercise the full create/get/update lifecycle without touching real work,
create a dedicated throwaway project in Taiga and point the smoke test at it by
slug (the tool cannot create projects itself). It then creates an epic and a
linked story there, updates them, and reads them back:

```bash
TAIGA_SMOKE_PROJECT_SLUG=your-smoke-project uv run python scripts/smoke_test.py
```

The client has no delete operation, so each full run leaves a new (timestamped)
epic and story behind in the smoke project.
