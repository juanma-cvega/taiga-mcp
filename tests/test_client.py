import pytest
import respx
import httpx
from taiga_mcp.client import TaigaClient, _build_payload

TAIGA_URL = "https://api.taiga.io/api/v1"
TOKEN = "test-token"


@respx.mock
async def test_list_projects():
    route = respx.get(f"{TAIGA_URL}/projects").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "Booking Engine", "slug": "booking-engine", "description": "My project"}
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    projects = await client.list_projects()
    assert len(projects) == 1
    assert projects[0].name == "Booking Engine"


@respx.mock
async def test_list_projects_scopes_to_authenticated_member():
    # Without ?member the endpoint returns every public project on the
    # platform (~180k). It MUST be scoped to the authenticated user.
    route = respx.get(f"{TAIGA_URL}/projects").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.list_projects()
    assert route.calls.last.request.url.params["member"] == "42"


@respx.mock
async def test_list_sprints():
    respx.get(f"{TAIGA_URL}/milestones").mock(
        return_value=httpx.Response(200, json=[
            {"id": 10, "name": "Sprint 1", "project": 1, "closed": False,
             "estimated_start": "2026-06-01", "estimated_finish": "2026-06-14"}
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
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
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
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
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    tasks = await client.list_tasks(project_id=1, user_story_id=5)
    assert tasks[0].subject == "Implement endpoint"
    assert tasks[0].status == "Done"


@respx.mock
async def test_list_epics():
    respx.get(f"{TAIGA_URL}/epics").mock(
        return_value=httpx.Response(200, json=[
            {"id": 30, "ref": 11, "subject": "Create sqs consumer library", "project": 1,
             "status_extra_info": {"name": "New"}}
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    epics = await client.list_epics(project_id=1)
    assert epics[0].subject == "Create sqs consumer library"
    assert epics[0].status == "New"


@respx.mock
async def test_list_epics_scopes_to_project():
    route = respx.get(f"{TAIGA_URL}/epics").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.list_epics(project_id=7)
    assert route.calls.last.request.url.params["project"] == "7"


@respx.mock
async def test_list_follows_pagination_across_pages():
    page1 = httpx.Response(
        200,
        json=[{"id": 1, "ref": 1, "subject": "T1", "project": 1}],
        headers={"x-pagination-next": f"{TAIGA_URL}/tasks?project=1&page=2"},
    )
    page2 = httpx.Response(
        200,
        json=[{"id": 2, "ref": 2, "subject": "T2", "project": 1}],
    )
    route = respx.get(f"{TAIGA_URL}/tasks").mock(side_effect=[page1, page2])
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    tasks = await client.list_tasks(project_id=1)
    assert [t.ref for t in tasks] == [1, 2]
    assert route.call_count == 2


@respx.mock
async def test_pagination_next_scheme_normalized_to_base_url():
    # Taiga behind a TLS-terminating proxy advertises the next page over
    # http:// even though the API is served over https://. Following that
    # literally 301-redirects and drops the auth header, so the client must
    # rewrite the scheme to match the base URL.
    page1 = httpx.Response(
        200,
        json=[{"id": 1, "ref": 1, "subject": "T1", "project": 1}],
        headers={"x-pagination-next": "http://api.taiga.io/api/v1/tasks?page=2"},
    )
    page2 = httpx.Response(
        200,
        json=[{"id": 2, "ref": 2, "subject": "T2", "project": 1}],
    )
    https_route = respx.get(f"{TAIGA_URL}/tasks").mock(side_effect=[page1, page2])
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    tasks = await client.list_tasks(project_id=1)
    assert [t.ref for t in tasks] == [1, 2]
    assert https_route.call_count == 2


@respx.mock
async def test_pagination_stops_on_repeated_next_url():
    # Defense in depth: if the API keeps advertising the same next page, the
    # client must not loop forever.
    looping = httpx.Response(
        200,
        json=[{"id": 1, "ref": 1, "subject": "T1", "project": 1}],
        headers={"x-pagination-next": f"{TAIGA_URL}/tasks?page=2"},
    )
    route = respx.get(f"{TAIGA_URL}/tasks").mock(return_value=looping)
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    tasks = await client.list_tasks(project_id=1)
    # First request + one follow to page=2, then page=2's next repeats and stops.
    assert route.call_count == 2
    assert len(tasks) == 2


def test_build_payload_omits_none_and_clears_empty_string():
    result = _build_payload({
        "a": None,        # omitted
        "b": "",          # cleared -> None
        "c": "value",     # kept
        "d": 0,           # kept (not treated as empty)
        "e": False,       # kept
        "f": [],          # kept
    })
    assert result == {"b": None, "c": "value", "d": 0, "e": False, "f": []}


@respx.mock
async def test_resolve_status_returns_matching_id():
    respx.get(f"{TAIGA_URL}/userstory-statuses").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "New"}, {"id": 2, "name": "In progress"},
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    status_id = await client._resolve_status("/userstory-statuses", 10, "In progress")
    assert status_id == 2


@respx.mock
async def test_resolve_status_unknown_name_raises_with_valid_names():
    respx.get(f"{TAIGA_URL}/epic-statuses").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "name": "New"}, {"id": 2, "name": "Done"},
        ])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(ValueError) as exc:
        await client._resolve_status("/epic-statuses", 10, "Bogus")
    assert "New" in str(exc.value) and "Done" in str(exc.value)


@respx.mock
async def test_post_returns_json_body():
    respx.post(f"{TAIGA_URL}/epics").mock(
        return_value=httpx.Response(201, json={"id": 99, "ref": 3})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    data = await client._post("/epics", {"subject": "X"})
    assert data == {"id": 99, "ref": 3}


@respx.mock
async def test_get_story_fetches_single_object():
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(200, json={
            "id": 2, "ref": 9, "subject": "Story A", "project": 10,
            "description": "details", "version": 4,
            "status_extra_info": {"name": "In progress"},
        })
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    story = await client.get_story(2)
    assert story.ref == 9
    assert story.description == "details"
    assert story.status == "In progress"


@respx.mock
async def test_get_epic_fetches_single_object():
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(200, json={
            "id": 1, "ref": 5, "subject": "Epic A", "project": 10,
            "color": "#123456", "version": 2,
            "status_extra_info": {"name": "New"},
        })
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    epic = await client.get_epic(1)
    assert epic.ref == 5
    assert epic.color == "#123456"
