from urllib.parse import urlsplit, urlunsplit

import httpx
from taiga_mcp.models import Project, Sprint, UserStory, Task, Epic


def _build_payload(fields: dict) -> dict:
    """Build a write payload: drop None (leave unchanged), map '' to None
    (clear the value), keep everything else as-is."""
    payload: dict = {}
    for key, value in fields.items():
        if value is None:
            continue
        payload[key] = None if value == "" else value
    return payload


def _require_field(current: dict, field: str, kind: str, item_id: int) -> object:
    """Fetch a required field from a Taiga response, raising a readable
    RuntimeError instead of a bare KeyError if the response shape doesn't
    match expectations (e.g. an unexpected/partial payload)."""
    try:
        return current[field]
    except KeyError:
        raise RuntimeError(
            f"Taiga response for {kind} {item_id} missing '{field}'"
        ) from None


def _raise_for_taiga_error(response: httpx.Response) -> None:
    """Raise a RuntimeError with the Taiga response body on HTTP failure.

    httpx.HTTPStatusError alone doesn't surface the response body, so an
    agent hitting a 400/404/409 gets no actionable detail (e.g. a
    stale-version 409 or an invalid field). Include the status code and
    body text so callers can recover.
    """
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Taiga API error {response.status_code}: {response.text}"
        ) from exc


class TaigaClient:
    def __init__(
        self, base_url: str, token: str, user_id: int, timeout: float = 30.0
    ) -> None:
        self._base_url = base_url
        self._scheme = urlsplit(base_url).scheme
        self._user_id = user_id
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = httpx.AsyncClient(headers=self._headers, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_projects(self) -> list[Project]:
        # Scope to the authenticated user; an unfiltered /projects returns
        # every public project on the platform.
        data = await self._get("/projects", params={"member": self._user_id})
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

    async def list_epics(self, project_id: int) -> list[Epic]:
        data = await self._get("/epics", params={"project": project_id})
        return [Epic(**item) for item in data]

    async def get_epic(self, epic_id: int) -> Epic:
        return Epic(**await self._get_one(f"/epics/{epic_id}"))

    async def get_story(self, story_id: int) -> UserStory:
        return UserStory(**await self._get_one(f"/userstories/{story_id}"))

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
            try:
                await self._post(
                    f"/epics/{epic_id}/related_userstories",
                    {"epic": epic_id, "user_story": story.id},
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Story #{story.ref} (id {story.id}) created but linking "
                    f"to epic {epic_id} failed: {exc}"
                ) from exc
        return story

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
        payload = {"version": _require_field(current, "version", "epic", epic_id)}
        if status is not None:
            project_id = _require_field(current, "project", "epic", epic_id)
            payload["status"] = await self._resolve_status(
                "/epic-statuses", project_id, status
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
        payload = {"version": _require_field(current, "version", "story", story_id)}
        if status is not None:
            project_id = _require_field(current, "project", "story", story_id)
            payload["status"] = await self._resolve_status(
                "/userstory-statuses", project_id, status
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

    async def _get_one(self, path: str) -> dict:
        response = await self._client.get(f"{self._base_url}{path}")
        _raise_for_taiga_error(response)
        return response.json()

    async def _post(self, path: str, json: dict) -> dict:
        response = await self._client.post(f"{self._base_url}{path}", json=json)
        _raise_for_taiga_error(response)
        return response.json()

    async def _patch(self, path: str, json: dict) -> dict:
        response = await self._client.patch(f"{self._base_url}{path}", json=json)
        _raise_for_taiga_error(response)
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

    async def _get(self, path: str, params: dict | None = None) -> list:
        results: list = []
        url: str | None = f"{self._base_url}{path}"
        seen: set[str] = set()
        while url and url not in seen:
            seen.add(url)
            response = await self._client.get(url, params=params)
            _raise_for_taiga_error(response)
            results.extend(response.json())
            # Taiga returns the full URL of the next page (query params
            # included) in this header, absent on the final page. A
            # TLS-terminating proxy can advertise it over http:// even
            # when the API is https://; following that downgrade 301s and
            # drops the auth header, so pin the scheme to the base URL's.
            next_url = response.headers.get("x-pagination-next")
            if next_url:
                parts = urlsplit(next_url)
                if parts.scheme != self._scheme:
                    next_url = urlunsplit(parts._replace(scheme=self._scheme))
            url = next_url
            params = None
        return results
