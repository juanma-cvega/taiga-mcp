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
