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
