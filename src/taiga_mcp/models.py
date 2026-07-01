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


class Epic(BaseModel):
    id: int
    ref: int
    subject: str
    project: int
    status_extra_info: dict | None = None

    @property
    def status(self) -> str:
        if self.status_extra_info:
            return self.status_extra_info.get("name", "unknown")
        return "unknown"
