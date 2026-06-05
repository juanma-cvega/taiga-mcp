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
