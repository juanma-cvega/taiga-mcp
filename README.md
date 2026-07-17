# taiga-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes a
[Taiga](https://taiga.io) account — projects, epics, user stories, tasks, and
sprints — as tools an MCP client (e.g. Claude Code) can call.

## Requirements

- Python >= 3.14
- [uv](https://docs.astral.sh/uv/)
- A Taiga account (Taiga Cloud or self-hosted)

## Setup

With [mise](https://mise.jdx.dev), install the pinned toolchain (Python and
uv) and set up the environment (dependencies and git hooks, via uv):

```bash
mise install
mise run setup
```

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

The create, update, and get tools return a link to the item in the Taiga web
UI so the result can be verified manually, and `list_tasks` includes one per
task. The UI base URL is derived
from `TAIGA_URL` (Taiga Cloud's `api.taiga.io` maps to `tree.taiga.io`;
self-hosted instances drop the `/api/v1` suffix). If the derivation is wrong
for your setup (e.g. a proxy serves the UI elsewhere), set `TAIGA_UI_URL`
explicitly.

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
| `list_sprints` | `project_id`, `closed?` | List sprints for a project, optionally filtered to open or closed ones. |
| `get_current_sprint` | `project_id` | Get the currently open sprint for a project. |
| `get_sprint` | `sprint_id` | Get a single sprint by id. |
| `create_sprint` | `project_id`, `name`, `estimated_start`, `estimated_finish` | Create a sprint. Dates are `YYYY-MM-DD`; the name must be unique within the project. |
| `update_sprint` | `sprint_id`, + optional `name`, `estimated_start`, `estimated_finish`, `closed` | Update a sprint. `None` leaves a field unchanged; `closed=False` reopens a closed sprint. |
| `close_sprint` | `sprint_id` | Close a sprint. |
| `delete_sprint` | `sprint_id` | Delete a sprint permanently. Its stories are **not** deleted — Taiga returns them to the backlog. |
| `move_story_to_backlog` | `story_id` | Move a story out of its sprint and back to the backlog. |
| `create_epic` | `project_id`, `subject`, + optional `description`, `status`, `assigned_to`, `tags`, `is_blocked`, `blocked_note`, `color` | Create an epic. `status` is a status name. |
| `create_story` | `project_id`, `subject`, + optional `description`, `status`, `sprint_id`, `epic_id`, `assigned_to`, `tags`, `is_blocked`, `blocked_note` | Create a story, optionally linked to an epic. |
| `get_epic` | `epic_id` | Get a single epic by id with its full field set. |
| `get_story` | `story_id` | Get a single story by id with its full field set. |
| `get_epic_by_ref` | `project_id`, `ref` | Get a single epic by its per-project `#ref` (the number shown in the Taiga UI). |
| `get_story_by_ref` | `project_id`, `ref` | Get a single story by its per-project `#ref`. |
| `update_epic` | `epic_id`, + any field to change | Update an epic. `None` leaves a field unchanged; `''` clears it. |
| `update_story` | `story_id`, + any field to change | Update a story. `None` leaves a field unchanged; `''` clears it. |
| `update_epic_by_ref` | `project_id`, `ref`, + any field to change | Update an epic by its per-project `#ref`. |
| `update_story_by_ref` | `project_id`, `ref`, + any field to change | Update a story by its per-project `#ref`. |

The list tools show both the `#ref` (the identifier a human sees in the Taiga
UI) and the numeric `id`. The `id` tools (`get_epic`, `update_story`, …) take
the numeric id; the `_by_ref` tools take `(project_id, ref)` since a `#ref` is
only unique within its project.

All list tools follow Taiga's pagination automatically, and `list_projects` is
scoped to the authenticated user (an unfiltered query would return every public
project on the platform).

## Releasing

Releases are automatic. Every push to `main` runs the checks, and
[python-semantic-release](https://python-semantic-release.readthedocs.io)
derives the next version from the [Conventional
Commits](https://www.conventionalcommits.org) since the last tag:

| Commit | Bump |
| --- | --- |
| `feat: …` | minor (1.1.0 → 1.2.0) |
| `fix: …` / `perf: …` | patch (1.1.0 → 1.1.1) |
| any type with a `BREAKING CHANGE:` footer | major (1.1.0 → 2.0.0) |
| `chore:`, `docs:`, `ci:`, `test:`, `style:`, `refactor:` | none — no release |

When there's something to release it bumps the version in `pyproject.toml`,
writes `CHANGELOG.md`, commits as `chore: release X.Y.Z`, tags `vX.Y.Z`, and
publishes a GitHub Release with generated notes. A push with no releasable
commits just runs the checks. (No build artifacts are attached: GitHub creates
releases as immutable, so assets must be sealed in at creation, which the
release tooling's separate upload step can't do — the tag and notes are the
release.)

**Never edit the version by hand** — the commit history is the source of
truth, and a manual edit will be overwritten by the next release. Since the
release commit lands on `main`, `git pull` after a release.

Your commit type is what picks the version, so it's worth getting right.

## Development

Run the test suite:

```bash
uv run pytest
```

Run all pre-commit hooks (lint, format check, tests) without committing:

```bash
mise run check
```

There is also a manual smoke test that hits a real Taiga account. It
authenticates with its **own** credentials, separate from the MCP server's, so
you can point it at a throwaway project on a different account:

- Server: `TAIGA_URL` / `TAIGA_USERNAME` / `TAIGA_PASSWORD`
- Smoke test: `TAIGA_SMOKE_URL` / `TAIGA_SMOKE_USERNAME` / `TAIGA_SMOKE_PASSWORD`
  (required — no fallback to the server's `TAIGA_*` values)

By default it is **read-only** — it lists projects and exercises the read tools
against the first project without mutating anything:

```bash
uv run python scripts/smoke_test.py
```

To exercise the full create/get/update lifecycle without touching real work,
create a dedicated throwaway project in Taiga and point the smoke test at it by
slug (the tool cannot create projects itself). It then creates an epic and a
linked story there, updates them, and reads them back, and finally runs the
sprint lifecycle — create a sprint, move the story in and out of it, close the
sprint and delete it:

```bash
TAIGA_SMOKE_PROJECT_SLUG=your-smoke-project uv run python scripts/smoke_test.py
```

Epics and stories have no delete operation, so each full run leaves a new
(timestamped) epic and story behind in the smoke project. The sprint it creates
is deleted at the end of the run.
