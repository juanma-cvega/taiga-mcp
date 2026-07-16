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
    slug: str | None = None
    estimated_start: str | None = None
    estimated_finish: str | None = None
    project_extra_info: dict | None = None

    @property
    def project_slug(self) -> str | None:
        if self.project_extra_info:
            return self.project_extra_info.get("slug")
        return None


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
    project_extra_info: dict | None = None
    epics: list | None = None

    @property
    def status(self) -> str:
        if self.status_extra_info:
            return self.status_extra_info.get("name", "unknown")
        return "unknown"

    @property
    def project_slug(self) -> str | None:
        if self.project_extra_info:
            return self.project_extra_info.get("slug")
        return None


class Task(BaseModel):
    id: int
    ref: int
    subject: str
    project: int
    user_story: int | None = None
    status_extra_info: dict | None = None
    project_extra_info: dict | None = None

    @property
    def status(self) -> str:
        if self.status_extra_info:
            return self.status_extra_info.get("name", "unknown")
        return "unknown"

    @property
    def project_slug(self) -> str | None:
        if self.project_extra_info:
            return self.project_extra_info.get("slug")
        return None


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
    project_extra_info: dict | None = None

    @property
    def status(self) -> str:
        if self.status_extra_info:
            return self.status_extra_info.get("name", "unknown")
        return "unknown"

    @property
    def project_slug(self) -> str | None:
        if self.project_extra_info:
            return self.project_extra_info.get("slug")
        return None
