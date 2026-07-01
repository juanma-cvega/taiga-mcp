from urllib.parse import urlsplit, urlunsplit

import httpx
from taiga_mcp.models import Project, Sprint, UserStory, Task


class TaigaClient:
    def __init__(self, base_url: str, token: str, user_id: int) -> None:
        self._base_url = base_url
        self._scheme = urlsplit(base_url).scheme
        self._user_id = user_id
        self._headers = {"Authorization": f"Bearer {token}"}

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

    async def _get(self, path: str, params: dict | None = None) -> list:
        results: list = []
        url: str | None = f"{self._base_url}{path}"
        seen: set[str] = set()
        async with httpx.AsyncClient() as client:
            while url and url not in seen:
                seen.add(url)
                response = await client.get(
                    url, headers=self._headers, params=params
                )
                response.raise_for_status()
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
