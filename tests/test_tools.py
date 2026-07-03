import pytest
from unittest.mock import AsyncMock
from taiga_mcp import server
from taiga_mcp.client import TaigaClient
from taiga_mcp.models import Project, Sprint, UserStory, Task, Epic


@pytest.fixture(autouse=True)
def mock_client(monkeypatch):
    mock = AsyncMock(spec=TaigaClient)
    mock.list_projects.return_value = []
    mock.list_user_stories.return_value = []
    mock.list_tasks.return_value = []
    mock.list_sprints.return_value = []
    mock.list_epics.return_value = []
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


async def test_list_epics_formats_output(mock_client):
    mock_client.list_epics.return_value = [
        Epic(id=30, ref=11, subject="Create sqs consumer library", project=1,
             status_extra_info={"name": "New"})
    ]
    result = await server.list_epics(project_id=1)
    assert "Create sqs consumer library" in result
    assert "New" in result
    # The id must be surfaced so callers can feed it to get_epic/update_epic
    # (which are keyed by id, not the #ref shown to humans).
    assert "id: 30" in result


async def test_list_epics_empty(mock_client):
    result = await server.list_epics(project_id=1)
    assert "No epics found" in result


async def test_list_user_stories_formats_output_with_id(mock_client):
    mock_client.list_user_stories.return_value = [
        UserStory(id=5, ref=3, subject="Book a slot", project=1,
                  status_extra_info={"name": "In progress"})
    ]
    result = await server.list_user_stories(project_id=1)
    assert "Book a slot" in result
    # id enables the list -> get_story/update_story flow (keyed by id, not #ref).
    assert "id: 5" in result


async def test_list_tasks_formats_output_with_id(mock_client):
    mock_client.list_tasks.return_value = [
        Task(id=20, ref=7, subject="Implement endpoint", project=1,
             status_extra_info={"name": "Done"})
    ]
    result = await server.list_tasks(project_id=1)
    assert "Implement endpoint" in result
    assert "id: 20" in result


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


async def test_get_epic_formats_tags(mock_client):
    mock_client.get_epic.return_value = Epic(
        id=1, ref=5, subject="Epic A", project=10,
        tags=[["urgent", "#f00"], ["backend", None]],
        status_extra_info={"name": "New"},
    )
    result = await server.get_epic(epic_id=1)
    assert "urgent" in result
    assert "backend" in result


async def test_get_story_formats_tags_and_epics(mock_client):
    mock_client.get_story.return_value = UserStory(
        id=2, ref=9, subject="Story A", project=10,
        tags=[["urgent", "#f00"]],
        epics=[{"ref": 5, "subject": "Epic A"}],
        status_extra_info={"name": "In progress"},
    )
    result = await server.get_story(story_id=2)
    assert "urgent" in result
    assert "#5" in result
    assert "Epic A" in result


async def test_get_story_formats_epics_defensively_on_missing_keys(mock_client):
    mock_client.get_story.return_value = UserStory(
        id=2, ref=9, subject="Story A", project=10,
        epics=[{"ref": 5}],  # missing 'subject'
        status_extra_info={"name": "In progress"},
    )
    result = await server.get_story(story_id=2)
    assert "#5" in result


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


async def test_update_epic_returns_updated_status(mock_client):
    mock_client.update_epic.return_value = Epic(
        id=1, ref=5, subject="Epic A", project=10,
        status_extra_info={"name": "Done"},
    )
    result = await server.update_epic(epic_id=1, status="Done")
    mock_client.update_epic.assert_called_once()
    assert "#5 Epic A" in result
    assert "Done" in result


async def test_update_story_returns_updated_status(mock_client):
    mock_client.update_story.return_value = UserStory(
        id=2, ref=9, subject="Story A", project=10,
        status_extra_info={"name": "In progress"},
    )
    result = await server.update_story(story_id=2, status="In progress")
    mock_client.update_story.assert_called_once()
    assert "#9 Story A" in result
    assert "In progress" in result
