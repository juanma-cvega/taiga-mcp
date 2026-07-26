import json

import httpx
import pytest
import respx

from taiga_mcp.client import TaigaClient, _build_payload
from taiga_mcp.models import Epic, Task

TAIGA_URL = "https://api.taiga.io/api/v1"
TOKEN = "test-token"


@respx.mock
async def test_list_projects():
    respx.get(f"{TAIGA_URL}/projects").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "Example Project",
                    "slug": "example-project",
                    "description": "My project",
                }
            ],
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    projects = await client.list_projects()
    assert len(projects) == 1
    assert projects[0].name == "Example Project"


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
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 10,
                    "name": "Sprint 1",
                    "project": 1,
                    "closed": False,
                    "estimated_start": "2026-06-01",
                    "estimated_finish": "2026-06-14",
                }
            ],
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    sprints = await client.list_sprints(project_id=1)
    assert sprints[0].name == "Sprint 1"
    assert sprints[0].closed is False


@respx.mock
async def test_list_user_stories():
    respx.get(f"{TAIGA_URL}/userstories").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 5,
                    "ref": 3,
                    "subject": "As a user I want to book a slot",
                    "project": 1,
                    "milestone": 10,
                    "milestone_name": "Sprint 1",
                    "status_extra_info": {"name": "In progress"},
                }
            ],
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    stories = await client.list_user_stories(project_id=1)
    assert stories[0].subject == "As a user I want to book a slot"
    assert stories[0].status == "In progress"


@respx.mock
async def test_list_tasks():
    respx.get(f"{TAIGA_URL}/tasks").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 20,
                    "ref": 7,
                    "subject": "Implement endpoint",
                    "project": 1,
                    "user_story": 5,
                    "status_extra_info": {"name": "Done"},
                }
            ],
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    tasks = await client.list_tasks(project_id=1, user_story_id=5)
    assert tasks[0].subject == "Implement endpoint"
    assert tasks[0].status == "Done"


@respx.mock
async def test_list_epics():
    respx.get(f"{TAIGA_URL}/epics").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 30,
                    "ref": 11,
                    "subject": "Create sqs consumer library",
                    "project": 1,
                    "status_extra_info": {"name": "New"},
                }
            ],
        )
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


async def test_client_reuses_single_httpx_client_across_calls():
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    assert isinstance(client._client, httpx.AsyncClient)
    await client.aclose()


def test_client_applies_configured_timeout():
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42, timeout=5.0)
    assert client._client.timeout == httpx.Timeout(5.0)


@respx.mock
async def test_expired_token_is_refreshed_and_request_retried():
    respx.get(f"{TAIGA_URL}/projects").mock(
        side_effect=[
            httpx.Response(401, json={"_error_message": "Token expired"}),
            httpx.Response(
                200,
                json=[{"id": 1, "name": "Example Project", "slug": "example-project"}],
            ),
        ]
    )

    async def refresh_token() -> str:
        return "new-token"

    client = TaigaClient(
        TAIGA_URL, "stale-token", user_id=42, refresh_token=refresh_token
    )
    projects = await client.list_projects()
    assert projects[0].name == "Example Project"
    assert client._client.headers["Authorization"] == "Bearer new-token"


@respx.mock
async def test_refresh_only_retries_once():
    route = respx.get(f"{TAIGA_URL}/projects").mock(
        return_value=httpx.Response(401, json={"_error_message": "Still expired"})
    )

    async def refresh_token() -> str:
        return "another-token"

    client = TaigaClient(
        TAIGA_URL, "stale-token", user_id=42, refresh_token=refresh_token
    )
    with pytest.raises(RuntimeError, match="401"):
        await client.list_projects()
    assert route.call_count == 2


@respx.mock
async def test_no_refresh_callback_raises_on_401():
    respx.get(f"{TAIGA_URL}/projects").mock(
        return_value=httpx.Response(401, json={"_error_message": "Token expired"})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError, match="401"):
        await client.list_projects()


def test_build_payload_omits_none_and_clears_empty_string():
    result = _build_payload(
        {
            "a": None,  # omitted
            "b": "",  # cleared -> None
            "c": "value",  # kept
            "d": 0,  # kept (not treated as empty)
            "e": False,  # kept
            "f": [],  # kept
        }
    )
    assert result == {"b": None, "c": "value", "d": 0, "e": False, "f": []}


@respx.mock
async def test_resolve_status_returns_matching_id():
    respx.get(f"{TAIGA_URL}/userstory-statuses").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "New"},
                {"id": 2, "name": "In progress"},
            ],
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    status_id = await client._resolve_status("/userstory-statuses", 10, "In progress")
    assert status_id == 2


@respx.mock
async def test_resolve_status_unknown_name_raises_with_valid_names():
    respx.get(f"{TAIGA_URL}/epic-statuses").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "New"},
                {"id": 2, "name": "Done"},
            ],
        )
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
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "subject": "Story A",
                "project": 10,
                "description": "details",
                "version": 4,
                "status_extra_info": {"name": "In progress"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    story = await client.get_story(2)
    assert story.ref == 9
    assert story.description == "details"
    assert story.status == "In progress"


@respx.mock
async def test_get_story_by_ref_fetches_via_by_ref_endpoint():
    route = respx.get(f"{TAIGA_URL}/userstories/by_ref").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "subject": "Story A",
                "project": 10,
                "status_extra_info": {"name": "In progress"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    story = await client.get_story_by_ref(project_id=10, ref=9)
    assert story.id == 2
    assert story.ref == 9
    params = route.calls.last.request.url.params
    assert params["project"] == "10" and params["ref"] == "9"


@respx.mock
async def test_get_epic_by_ref_fetches_via_by_ref_endpoint():
    route = respx.get(f"{TAIGA_URL}/epics/by_ref").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "subject": "Epic A",
                "project": 10,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    epic = await client.get_epic_by_ref(project_id=10, ref=5)
    assert epic.id == 1
    assert epic.ref == 5
    params = route.calls.last.request.url.params
    assert params["project"] == "10" and params["ref"] == "5"


@respx.mock
async def test_update_story_by_ref_resolves_ref_then_patches():
    # by_ref resolves the ref -> id; update_story then GETs by id for version
    # and PATCHes.
    respx.get(f"{TAIGA_URL}/userstories/by_ref").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "project": 10,
                "version": 6,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "project": 10,
                "version": 6,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    route = respx.patch(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "subject": "Story A",
                "project": 10,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_story_by_ref(project_id=10, ref=9, description="edited")
    body = json.loads(route.calls.last.request.content)
    assert body["version"] == 6
    assert body["description"] == "edited"


@respx.mock
async def test_update_epic_by_ref_resolves_ref_then_patches():
    respx.get(f"{TAIGA_URL}/epics/by_ref").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "project": 10,
                "version": 3,
            },
        )
    )
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "project": 10,
                "version": 3,
            },
        )
    )
    route = respx.patch(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "subject": "Epic A",
                "project": 10,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_epic_by_ref(project_id=10, ref=5, description="edited")
    body = json.loads(route.calls.last.request.content)
    assert body["version"] == 3
    assert body["description"] == "edited"


@respx.mock
async def test_get_epic_fetches_single_object():
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "subject": "Epic A",
                "project": 10,
                "color": "#123456",
                "version": 2,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    epic = await client.get_epic(1)
    assert epic.ref == 5
    assert epic.color == "#123456"
    assert epic.status == "New"


@respx.mock
async def test_create_epic_posts_required_and_optional_fields():
    respx.get(f"{TAIGA_URL}/epic-statuses").mock(
        return_value=httpx.Response(200, json=[{"id": 7, "name": "New"}])
    )
    route = respx.post(f"{TAIGA_URL}/epics").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 50,
                "ref": 11,
                "subject": "New epic",
                "project": 10,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    epic = await client.create_epic(
        project_id=10,
        subject="New epic",
        description="d",
        status="New",
    )
    body = json.loads(route.calls.last.request.content)
    assert body["project"] == 10
    assert body["subject"] == "New epic"
    assert body["description"] == "d"
    assert body["status"] == 7  # name resolved to id
    assert "color" not in body  # None omitted
    assert epic.ref == 11


@respx.mock
async def test_create_epic_omits_status_when_not_given():
    route = respx.post(f"{TAIGA_URL}/epics").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 51,
                "ref": 12,
                "subject": "X",
                "project": 10,
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.create_epic(project_id=10, subject="X")
    body = json.loads(route.calls.last.request.content)
    assert "status" not in body


@respx.mock
async def test_create_story_maps_sprint_to_milestone():
    route = respx.post(f"{TAIGA_URL}/userstories").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 60,
                "ref": 20,
                "subject": "New story",
                "project": 10,
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.create_story(project_id=10, subject="New story", sprint_id=99)
    body = json.loads(route.calls.last.request.content)
    assert body["milestone"] == 99
    assert "epic" not in body


@respx.mock
async def test_create_story_links_epic_when_epic_id_given():
    respx.post(f"{TAIGA_URL}/userstories").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 61,
                "ref": 21,
                "subject": "Linked story",
                "project": 10,
            },
        )
    )
    link = respx.post(f"{TAIGA_URL}/epics/5/related_userstories").mock(
        return_value=httpx.Response(201, json={"epic": 5, "user_story": 61})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    story = await client.create_story(project_id=10, subject="Linked story", epic_id=5)
    assert story.id == 61
    assert link.called
    link_body = json.loads(link.calls.last.request.content)
    assert link_body == {"epic": 5, "user_story": 61}


@respx.mock
async def test_update_epic_sends_version_and_resolves_status():
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "subject": "Epic A",
                "project": 10,
                "version": 4,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    respx.get(f"{TAIGA_URL}/epic-statuses").mock(
        return_value=httpx.Response(200, json=[{"id": 8, "name": "Done"}])
    )
    route = respx.patch(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "subject": "Epic A",
                "project": 10,
                "status_extra_info": {"name": "Done"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    epic = await client.update_epic(1, status="Done")
    body = json.loads(route.calls.last.request.content)
    assert body["version"] == 4
    assert body["status"] == 8
    assert epic.status == "Done"


@respx.mock
async def test_update_epic_clears_field_with_empty_string():
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "subject": "Epic A",
                "project": 10,
                "version": 4,
            },
        )
    )
    route = respx.patch(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "subject": "Epic A",
                "project": 10,
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_epic(1, blocked_note="")
    body = json.loads(route.calls.last.request.content)
    assert body["blocked_note"] is None  # '' -> cleared
    assert "description" not in body  # None -> omitted
    assert "status" not in body  # not requested -> no status GET


@respx.mock
async def test_update_epic_raises_readable_error_on_http_failure():
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "subject": "Epic A",
                "project": 10,
                "version": 4,
            },
        )
    )
    respx.patch(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(409, json={"_error_message": "version mismatch"})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError) as exc:
        await client.update_epic(1, subject="New subject")
    assert "409" in str(exc.value)
    assert "version mismatch" in str(exc.value)


@respx.mock
async def test_update_epic_raises_readable_error_on_missing_version():
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "ref": 5,
                "subject": "Epic A",
                "project": 10,
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError, match="epic 1"):
        await client.update_epic(1, subject="New subject")


@respx.mock
async def test_update_story_raises_readable_error_on_missing_version():
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "subject": "Story A",
                "project": 10,
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError, match="story 2"):
        await client.update_story(2, subject="New subject")


@respx.mock
async def test_create_story_epic_link_failure_includes_story_and_epic_context():
    respx.post(f"{TAIGA_URL}/userstories").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 61,
                "ref": 21,
                "subject": "Linked story",
                "project": 10,
            },
        )
    )
    respx.post(f"{TAIGA_URL}/epics/5/related_userstories").mock(
        return_value=httpx.Response(400, json={"_error_message": "epic not found"})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError) as exc:
        await client.create_story(project_id=10, subject="Linked story", epic_id=5)
    assert "#21" in str(exc.value)
    assert "61" in str(exc.value)
    assert "5" in str(exc.value)


@respx.mock
async def test_update_story_maps_sprint_and_sends_version():
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "subject": "Story A",
                "project": 10,
                "version": 6,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    route = respx.patch(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "subject": "Story A",
                "project": 10,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_story(2, sprint_id=99)
    body = json.loads(route.calls.last.request.content)
    assert body["version"] == 6
    assert body["milestone"] == 99
    assert "status" not in body
    assert "epic" not in body


def _mock_story_2(epics: list | None = None) -> None:
    """Mock the GET/PATCH pair update_story makes for story id 2."""
    current = {
        "id": 2,
        "ref": 9,
        "subject": "Story A",
        "project": 10,
        "version": 6,
        "status_extra_info": {"name": "New"},
    }
    if epics is not None:
        current["epics"] = epics
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(200, json=current)
    )
    respx.patch(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(200, json=current)
    )


@respx.mock
async def test_update_story_links_epic_when_epic_id_given():
    _mock_story_2()
    link = respx.post(f"{TAIGA_URL}/epics/5/related_userstories").mock(
        return_value=httpx.Response(201, json={"epic": 5, "user_story": 2})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_story(2, epic_id=5)
    assert link.called
    assert json.loads(link.calls.last.request.content) == {
        "epic": 5,
        "user_story": 2,
    }


@respx.mock
async def test_update_story_skips_epic_link_when_already_in_that_epic():
    _mock_story_2(epics=[{"id": 5, "subject": "Epic A"}])
    link = respx.post(f"{TAIGA_URL}/epics/5/related_userstories").mock(
        return_value=httpx.Response(400, json={"_error_message": "already linked"})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_story(2, epic_id=5)
    assert not link.called


@respx.mock
async def test_update_story_links_epic_when_in_a_different_epic():
    _mock_story_2(epics=[{"id": 7, "subject": "Epic B"}])
    link = respx.post(f"{TAIGA_URL}/epics/5/related_userstories").mock(
        return_value=httpx.Response(201, json={"epic": 5, "user_story": 2})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_story(2, epic_id=5)
    assert link.called


@respx.mock
async def test_update_story_epic_link_failure_includes_story_and_epic_context():
    _mock_story_2()
    respx.post(f"{TAIGA_URL}/epics/5/related_userstories").mock(
        return_value=httpx.Response(400, json={"_error_message": "epic not found"})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError) as exc:
        await client.update_story(2, subject="Renamed", epic_id=5)
    assert "#9" in str(exc.value)
    assert "updated" in str(exc.value)
    assert "epic 5" in str(exc.value)


@respx.mock
async def test_update_story_by_ref_forwards_epic_id():
    respx.get(f"{TAIGA_URL}/userstories/by_ref").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "project": 10,
                "version": 6,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    _mock_story_2()
    link = respx.post(f"{TAIGA_URL}/epics/5/related_userstories").mock(
        return_value=httpx.Response(201, json={"epic": 5, "user_story": 2})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_story_by_ref(project_id=10, ref=9, epic_id=5)
    assert link.called


SPRINT_JSON = {
    "id": 10,
    "name": "Sprint 1",
    "slug": "sprint-1",
    "project": 1,
    "closed": False,
    "estimated_start": "2026-06-01",
    "estimated_finish": "2026-06-14",
    "project_extra_info": {"slug": "my-project"},
}


@respx.mock
async def test_list_sprints_filters_by_closed():
    route = respx.get(f"{TAIGA_URL}/milestones").mock(
        return_value=httpx.Response(200, json=[SPRINT_JSON])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.list_sprints(project_id=1, closed=True)
    assert route.calls.last.request.url.params["closed"] == "true"


@respx.mock
async def test_get_sprint_fetches_single_object():
    respx.get(f"{TAIGA_URL}/milestones/10").mock(
        return_value=httpx.Response(200, json=SPRINT_JSON)
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    sprint = await client.get_sprint(10)
    assert sprint.name == "Sprint 1"
    assert sprint.slug == "sprint-1"
    assert sprint.project_slug == "my-project"


@respx.mock
async def test_create_sprint_posts_project_name_and_dates():
    route = respx.post(f"{TAIGA_URL}/milestones").mock(
        return_value=httpx.Response(201, json=SPRINT_JSON)
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    sprint = await client.create_sprint(
        project_id=1,
        name="Sprint 1",
        estimated_start="2026-06-01",
        estimated_finish="2026-06-14",
    )
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "project": 1,
        "name": "Sprint 1",
        "estimated_start": "2026-06-01",
        "estimated_finish": "2026-06-14",
    }
    assert sprint.id == 10


@respx.mock
async def test_update_sprint_patches_only_given_fields_without_version():
    route = respx.patch(f"{TAIGA_URL}/milestones/10").mock(
        return_value=httpx.Response(200, json={**SPRINT_JSON, "name": "Renamed"})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    sprint = await client.update_sprint(10, name="Renamed")
    body = json.loads(route.calls.last.request.content)
    # Milestones are not version-checked by Taiga, so no GET-then-PATCH round
    # trip is needed and no version must be sent.
    assert body == {"name": "Renamed"}
    assert sprint.name == "Renamed"


@respx.mock
async def test_update_sprint_sends_closed_false_to_reopen():
    route = respx.patch(f"{TAIGA_URL}/milestones/10").mock(
        return_value=httpx.Response(200, json=SPRINT_JSON)
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_sprint(10, closed=False)
    # closed=False must reach Taiga, not be dropped as an unset field.
    assert json.loads(route.calls.last.request.content) == {"closed": False}


@respx.mock
async def test_update_sprint_closes_sprint():
    route = respx.patch(f"{TAIGA_URL}/milestones/10").mock(
        return_value=httpx.Response(200, json={**SPRINT_JSON, "closed": True})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    sprint = await client.update_sprint(10, closed=True)
    assert json.loads(route.calls.last.request.content) == {"closed": True}
    assert sprint.closed is True


@respx.mock
async def test_delete_sprint_issues_delete():
    route = respx.delete(f"{TAIGA_URL}/milestones/10").mock(
        return_value=httpx.Response(204)
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.delete_sprint(10)
    assert route.called


@respx.mock
async def test_delete_sprint_raises_readable_error_on_http_failure():
    respx.delete(f"{TAIGA_URL}/milestones/10").mock(
        return_value=httpx.Response(404, json={"_error_message": "Not found."})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError) as exc:
        await client.delete_sprint(10)
    assert "404" in str(exc.value)
    assert "Not found." in str(exc.value)


@respx.mock
async def test_move_story_to_backlog_nulls_milestone_with_version():
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "subject": "Story A",
                "project": 10,
                "milestone": 10,
                "version": 6,
            },
        )
    )
    route = respx.patch(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "subject": "Story A",
                "project": 10,
                "milestone": None,
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    story = await client.move_story_to_backlog(2)
    body = json.loads(route.calls.last.request.content)
    assert body == {"version": 6, "milestone": None}
    assert story.milestone is None


@respx.mock
async def test_move_story_to_backlog_raises_readable_error_on_missing_version():
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200, json={"id": 2, "ref": 9, "subject": "Story A", "project": 10}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError) as exc:
        await client.move_story_to_backlog(2)
    assert "version" in str(exc.value)


@respx.mock
async def test_reorder_backlog_posts_project_and_ordered_ids():
    route = respx.post(f"{TAIGA_URL}/userstories/bulk_update_backlog_order").mock(
        return_value=httpx.Response(200, json={"3": 1, "1": 2, "2": 3})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    result = await client.reorder_backlog(project_id=10, story_ids=[3, 1, 2])
    body = json.loads(route.calls.last.request.content)
    assert body == {"project_id": 10, "bulk_userstories": [3, 1, 2]}
    # No anchor keys travel when none is requested.
    assert "after_userstory_id" not in body
    assert "before_userstory_id" not in body
    assert result == {"3": 1, "1": 2, "2": 3}


@respx.mock
async def test_reorder_backlog_sends_after_anchor():
    route = respx.post(f"{TAIGA_URL}/userstories/bulk_update_backlog_order").mock(
        return_value=httpx.Response(200, json={})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.reorder_backlog(project_id=10, story_ids=[3], after_story_id=7)
    body = json.loads(route.calls.last.request.content)
    assert body["after_userstory_id"] == 7
    assert "before_userstory_id" not in body


@respx.mock
async def test_reorder_backlog_sends_before_anchor():
    route = respx.post(f"{TAIGA_URL}/userstories/bulk_update_backlog_order").mock(
        return_value=httpx.Response(200, json={})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.reorder_backlog(project_id=10, story_ids=[3], before_story_id=7)
    body = json.loads(route.calls.last.request.content)
    assert body["before_userstory_id"] == 7
    assert "after_userstory_id" not in body


@respx.mock
async def test_reorder_backlog_rejects_both_anchors_without_calling_taiga():
    route = respx.post(f"{TAIGA_URL}/userstories/bulk_update_backlog_order")
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(ValueError):
        await client.reorder_backlog(
            project_id=10, story_ids=[3], after_story_id=7, before_story_id=8
        )
    assert not route.called


@respx.mock
async def test_reorder_backlog_rejects_empty_ids_without_calling_taiga():
    route = respx.post(f"{TAIGA_URL}/userstories/bulk_update_backlog_order")
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(ValueError):
        await client.reorder_backlog(project_id=10, story_ids=[])
    assert not route.called


@respx.mock
async def test_reorder_backlog_raises_readable_error_on_http_failure():
    respx.post(f"{TAIGA_URL}/userstories/bulk_update_backlog_order").mock(
        return_value=httpx.Response(400, json={"_error_message": "not in project"})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError) as exc:
        await client.reorder_backlog(project_id=10, story_ids=[3])
    assert "400" in str(exc.value)
    assert "not in project" in str(exc.value)


@respx.mock
async def test_add_comment_patches_only_the_comment_with_version():
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "subject": "Story A",
                "project": 10,
                "description": "original",
                "version": 6,
            },
        )
    )
    route = respx.patch(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 2,
                "ref": 9,
                "subject": "Story A",
                "project": 10,
                "description": "original",
                "status_extra_info": {"name": "New"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    story = await client.add_comment("story", 2, "Looks good to me")
    body = json.loads(route.calls.last.request.content)
    # Only the comment travels: a comment must not overwrite any other field.
    assert body == {"version": 6, "comment": "Looks good to me"}
    assert story.subject == "Story A"


@respx.mock
async def test_add_comment_on_epic_uses_epic_endpoint():
    respx.get(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200,
            json={"id": 1, "ref": 5, "subject": "Epic A", "project": 10, "version": 3},
        )
    )
    route = respx.patch(f"{TAIGA_URL}/epics/1").mock(
        return_value=httpx.Response(
            200, json={"id": 1, "ref": 5, "subject": "Epic A", "project": 10}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    epic = await client.add_comment("epic", 1, "Scoped for Q3")
    assert json.loads(route.calls.last.request.content)["comment"] == "Scoped for Q3"
    assert isinstance(epic, Epic)


@respx.mock
async def test_add_comment_on_task_uses_task_endpoint():
    respx.get(f"{TAIGA_URL}/tasks/20").mock(
        return_value=httpx.Response(
            200,
            json={"id": 20, "ref": 7, "subject": "Task A", "project": 10, "version": 2},
        )
    )
    route = respx.patch(f"{TAIGA_URL}/tasks/20").mock(
        return_value=httpx.Response(
            200, json={"id": 20, "ref": 7, "subject": "Task A", "project": 10}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    task = await client.add_comment("task", 20, "Blocked on infra")
    assert json.loads(route.calls.last.request.content)["version"] == 2
    assert isinstance(task, Task)


@respx.mock
async def test_add_comment_rejects_unknown_item_type():
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(ValueError) as exc:
        await client.add_comment("sprint", 10, "Nope")
    assert "story" in str(exc.value)


@respx.mock
async def test_add_comment_rejects_empty_comment_without_calling_taiga():
    route = respx.patch(f"{TAIGA_URL}/userstories/2")
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(ValueError):
        await client.add_comment("story", 2, "   ")
    assert not route.called


@respx.mock
async def test_add_comment_raises_readable_error_on_missing_version():
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200, json={"id": 2, "ref": 9, "subject": "Story A", "project": 10}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError) as exc:
        await client.add_comment("story", 2, "Hello")
    assert "version" in str(exc.value)


@respx.mock
async def test_add_comment_by_ref_resolves_ref_then_comments():
    respx.get(f"{TAIGA_URL}/userstories/by_ref").mock(
        return_value=httpx.Response(
            200,
            json={"id": 2, "ref": 9, "subject": "Story A", "project": 10, "version": 6},
        )
    )
    respx.get(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200,
            json={"id": 2, "ref": 9, "subject": "Story A", "project": 10, "version": 6},
        )
    )
    route = respx.patch(f"{TAIGA_URL}/userstories/2").mock(
        return_value=httpx.Response(
            200, json={"id": 2, "ref": 9, "subject": "Story A", "project": 10}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.add_comment_by_ref("story", project_id=10, ref=9, comment="Done")
    assert json.loads(route.calls.last.request.content) == {
        "version": 6,
        "comment": "Done",
    }


def _history_comment(uid, text, created_at, **extra):
    return {
        "id": uid,
        "comment": text,
        "created_at": created_at,
        "user": {"pk": 1, "name": "Jane Doe", "username": "jane"},
        **extra,
    }


@respx.mock
async def test_list_comments_keeps_only_comment_entries():
    respx.get(f"{TAIGA_URL}/history/userstory/2").mock(
        return_value=httpx.Response(
            200,
            json=[
                _history_comment("a", "Second", "2026-07-02T10:00:00Z"),
                # A plain field change carries no comment text.
                {
                    "id": "b",
                    "comment": "",
                    "created_at": "2026-07-01T12:00:00Z",
                    "values_diff": {"status": ["New", "In progress"]},
                },
                _history_comment("c", "First", "2026-07-01T09:00:00Z"),
            ],
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    comments = await client.list_comments("story", 2)
    # Oldest first, field changes dropped.
    assert [c.comment for c in comments] == ["First", "Second"]
    assert comments[0].author == "Jane Doe"


@respx.mock
async def test_list_comments_drops_deleted_comments():
    respx.get(f"{TAIGA_URL}/history/userstory/2").mock(
        return_value=httpx.Response(
            200,
            json=[
                _history_comment("a", "Kept", "2026-07-01T09:00:00Z"),
                # Taiga keeps the text of a deleted comment and stamps it; it
                # must not resurface here.
                _history_comment(
                    "b",
                    "Deleted in the UI",
                    "2026-07-02T09:00:00Z",
                    delete_comment_date="2026-07-03T09:00:00Z",
                ),
            ],
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    comments = await client.list_comments("story", 2)
    assert [c.comment for c in comments] == ["Kept"]


@respx.mock
async def test_list_comments_uses_singular_history_path_per_type():
    for item_type, path in (
        ("story", "userstory"),
        ("epic", "epic"),
        ("task", "task"),
    ):
        route = respx.get(f"{TAIGA_URL}/history/{path}/3").mock(
            return_value=httpx.Response(200, json=[])
        )
        client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
        assert await client.list_comments(item_type, 3) == []
        assert route.called


@respx.mock
async def test_list_comments_rejects_unknown_item_type():
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(ValueError) as exc:
        await client.list_comments("sprint", 10)
    assert "story" in str(exc.value)


@respx.mock
async def test_list_comments_by_ref_resolves_ref_then_reads_history():
    respx.get(f"{TAIGA_URL}/epics/by_ref").mock(
        return_value=httpx.Response(
            200, json={"id": 1, "ref": 5, "subject": "Epic A", "project": 10}
        )
    )
    route = respx.get(f"{TAIGA_URL}/history/epic/1").mock(
        return_value=httpx.Response(
            200, json=[_history_comment("a", "Scoped", "2026-07-01T09:00:00Z")]
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    comments = await client.list_comments_by_ref("epic", project_id=10, ref=5)
    assert route.called
    assert [c.comment for c in comments] == ["Scoped"]


@respx.mock
async def test_list_issues_passes_filters_to_taiga():
    route = respx.get(f"{TAIGA_URL}/issues").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.list_issues(project_id=10, sprint_id=7, status="open", assigned_to=42)
    params = route.calls.last.request.url.params
    assert params["project"] == "10"
    assert params["milestone"] == "7"
    assert params["status__is_closed"] == "false"
    assert params["assigned_to"] == "42"


@respx.mock
async def test_list_issues_closed_filter_inverts_is_closed():
    route = respx.get(f"{TAIGA_URL}/issues").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.list_issues(project_id=10, status="closed")
    assert route.calls.last.request.url.params["status__is_closed"] == "true"


@respx.mock
async def test_get_issue_by_ref_queries_by_ref_endpoint():
    route = respx.get(f"{TAIGA_URL}/issues/by_ref").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 3,
                "ref": 12,
                "subject": "Login times out",
                "project": 10,
                "status_extra_info": {"name": "New"},
            },
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    issue = await client.get_issue_by_ref(10, 12)
    params = route.calls.last.request.url.params
    assert (params["project"], params["ref"]) == ("10", "12")
    assert issue.id == 3


@respx.mock
async def test_create_issue_resolves_every_catalogue_name_to_an_id():
    respx.get(f"{TAIGA_URL}/issue-statuses").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "New"}])
    )
    respx.get(f"{TAIGA_URL}/issue-types").mock(
        return_value=httpx.Response(200, json=[{"id": 2, "name": "Bug"}])
    )
    respx.get(f"{TAIGA_URL}/priorities").mock(
        return_value=httpx.Response(200, json=[{"id": 3, "name": "High"}])
    )
    respx.get(f"{TAIGA_URL}/severities").mock(
        return_value=httpx.Response(200, json=[{"id": 4, "name": "Normal"}])
    )
    route = respx.post(f"{TAIGA_URL}/issues").mock(
        return_value=httpx.Response(
            201,
            json={"id": 3, "ref": 12, "subject": "Login times out", "project": 10},
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.create_issue(
        project_id=10,
        subject="Login times out",
        status="New",
        issue_type="Bug",
        priority="High",
        severity="Normal",
        sprint_id=7,
    )
    body = json.loads(route.calls.last.request.content)
    assert body["project"] == 10
    assert body["subject"] == "Login times out"
    # Names resolved to this project's ids; `issue_type` writes Taiga's `type`.
    assert (body["status"], body["type"]) == (1, 2)
    assert (body["priority"], body["severity"]) == (3, 4)
    assert body["milestone"] == 7  # sprint_id maps to milestone
    assert "description" not in body  # None omitted


@respx.mock
async def test_create_issue_skips_catalogue_lookups_when_names_absent():
    statuses = respx.get(f"{TAIGA_URL}/issue-statuses").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "New"}])
    )
    types = respx.get(f"{TAIGA_URL}/issue-types").mock(
        return_value=httpx.Response(200, json=[{"id": 2, "name": "Bug"}])
    )
    route = respx.post(f"{TAIGA_URL}/issues").mock(
        return_value=httpx.Response(
            201, json={"id": 3, "ref": 12, "subject": "X", "project": 10}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.create_issue(project_id=10, subject="X")
    body = json.loads(route.calls.last.request.content)
    # Each catalogue costs a request; none is fetched when nothing needs it.
    assert not statuses.called and not types.called
    assert "status" not in body and "type" not in body


@respx.mock
async def test_create_issue_unknown_type_lists_the_projects_types():
    respx.get(f"{TAIGA_URL}/issue-types").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1, "name": "Bug"}, {"id": 2, "name": "Question"}]
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(ValueError) as exc:
        await client.create_issue(project_id=10, subject="X", issue_type="Nope")
    message = str(exc.value)
    # Names the field that was wrong, not "status", and shows the real values.
    assert "type" in message and "Bug" in message and "Question" in message


@respx.mock
async def test_update_issue_sends_version_and_only_given_fields():
    respx.get(f"{TAIGA_URL}/issues/3").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "X", "project": 10, "version": 9}
        )
    )
    route = respx.patch(f"{TAIGA_URL}/issues/3").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "Y", "project": 10}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_issue(3, subject="Y")
    body = json.loads(route.calls.last.request.content)
    assert body == {"version": 9, "subject": "Y"}


@respx.mock
async def test_update_issue_reads_project_only_to_resolve_a_catalogue():
    respx.get(f"{TAIGA_URL}/issues/3").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "X", "project": 10, "version": 9}
        )
    )
    severities = respx.get(f"{TAIGA_URL}/severities").mock(
        return_value=httpx.Response(200, json=[{"id": 5, "name": "Critical"}])
    )
    route = respx.patch(f"{TAIGA_URL}/issues/3").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "X", "project": 10}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_issue(3, severity="Critical")
    assert severities.called
    body = json.loads(route.calls.last.request.content)
    assert body["severity"] == 5


@respx.mock
async def test_update_issue_by_ref_resolves_ref_then_patches_by_id():
    respx.get(f"{TAIGA_URL}/issues/by_ref").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "X", "project": 10, "version": 9}
        )
    )
    respx.get(f"{TAIGA_URL}/issues/3").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "X", "project": 10, "version": 9}
        )
    )
    route = respx.patch(f"{TAIGA_URL}/issues/3").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "Y", "project": 10}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    issue = await client.update_issue_by_ref(10, 12, subject="Y")
    assert route.called
    assert issue.subject == "Y"


@respx.mock
async def test_add_comment_accepts_issues():
    respx.get(f"{TAIGA_URL}/issues/3").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "X", "project": 10, "version": 9}
        )
    )
    route = respx.patch(f"{TAIGA_URL}/issues/3").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "X", "project": 10}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.add_comment("issue", 3, "Reproduced on staging")
    body = json.loads(route.calls.last.request.content)
    assert body == {"version": 9, "comment": "Reproduced on staging"}


@respx.mock
async def test_list_comments_reads_the_issue_history_feed():
    route = respx.get(f"{TAIGA_URL}/history/issue/3").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"comment": "second", "created_at": "2026-01-02", "id": "b"},
                {"comment": "first", "created_at": "2026-01-01", "id": "a"},
            ],
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    comments = await client.list_comments("issue", 3)
    assert route.called
    assert [c.comment for c in comments] == ["first", "second"]


@respx.mock
async def test_delete_issue_calls_the_issue_endpoint():
    route = respx.delete(f"{TAIGA_URL}/issues/3").mock(return_value=httpx.Response(204))
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.delete_issue(3)
    assert route.called


@respx.mock
async def test_delete_story_calls_the_userstory_endpoint():
    route = respx.delete(f"{TAIGA_URL}/userstories/5").mock(
        return_value=httpx.Response(204)
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.delete_story(5)
    assert route.called


@respx.mock
async def test_delete_epic_calls_the_epic_endpoint():
    route = respx.delete(f"{TAIGA_URL}/epics/7").mock(return_value=httpx.Response(204))
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.delete_epic(7)
    assert route.called


@respx.mock
async def test_delete_task_calls_the_task_endpoint():
    route = respx.delete(f"{TAIGA_URL}/tasks/9").mock(return_value=httpx.Response(204))
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.delete_task(9)
    assert route.called


@respx.mock
async def test_delete_raises_readable_error_on_http_failure():
    respx.delete(f"{TAIGA_URL}/userstories/5").mock(
        return_value=httpx.Response(404, text="Not found")
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError, match="404"):
        await client.delete_story(5)


@respx.mock
async def test_get_task_reads_a_single_task():
    respx.get(f"{TAIGA_URL}/tasks/9").mock(
        return_value=httpx.Response(
            200, json={"id": 9, "ref": 31, "subject": "Wire the form", "project": 1}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    task = await client.get_task(9)
    assert task.ref == 31
    assert task.subject == "Wire the form"


@respx.mock
async def test_promote_issue_posts_to_the_promote_endpoint():
    respx.get(f"{TAIGA_URL}/issues/3").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "Login fails", "project": 1}
        )
    )
    promote = respx.post(f"{TAIGA_URL}/issues/3/promote_to_user_story").mock(
        return_value=httpx.Response(200, json=[44])
    )
    respx.get(f"{TAIGA_URL}/userstories/by_ref").mock(
        return_value=httpx.Response(
            200, json={"id": 88, "ref": 44, "subject": "Login fails", "project": 1}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    stories = await client.promote_to_story("issue", 3)
    assert json.loads(promote.calls.last.request.content) == {"project_id": 1}
    assert [s.ref for s in stories] == [44]
    assert stories[0].id == 88


@respx.mock
async def test_promote_task_uses_the_task_endpoint():
    respx.get(f"{TAIGA_URL}/tasks/9").mock(
        return_value=httpx.Response(
            200, json={"id": 9, "ref": 31, "subject": "Wire the form", "project": 2}
        )
    )
    promote = respx.post(f"{TAIGA_URL}/tasks/9/promote_to_user_story").mock(
        return_value=httpx.Response(200, json=[45])
    )
    by_ref = respx.get(f"{TAIGA_URL}/userstories/by_ref").mock(
        return_value=httpx.Response(
            200, json={"id": 90, "ref": 45, "subject": "Wire the form", "project": 2}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    stories = await client.promote_to_story("task", 9)
    # The project is read off the task, never asked of the caller.
    assert json.loads(promote.calls.last.request.content) == {"project_id": 2}
    assert by_ref.calls.last.request.url.params["project"] == "2"
    assert [s.ref for s in stories] == [45]


@respx.mock
async def test_promote_reads_back_every_ref_taiga_returns():
    respx.get(f"{TAIGA_URL}/issues/3").mock(
        return_value=httpx.Response(
            200, json={"id": 3, "ref": 12, "subject": "Login fails", "project": 1}
        )
    )
    respx.post(f"{TAIGA_URL}/issues/3/promote_to_user_story").mock(
        return_value=httpx.Response(200, json=[44, 45])
    )
    respx.get(f"{TAIGA_URL}/userstories/by_ref").mock(
        side_effect=[
            httpx.Response(
                200, json={"id": 88, "ref": 44, "subject": "A", "project": 1}
            ),
            httpx.Response(
                200, json={"id": 89, "ref": 45, "subject": "B", "project": 1}
            ),
        ]
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    stories = await client.promote_to_story("issue", 3)
    assert [s.ref for s in stories] == [44, 45]


async def test_promote_rejects_a_type_taiga_cannot_promote():
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    # Taiga has no story -> issue conversion, so 'story' must fail loudly
    # rather than POST to an endpoint that does not exist.
    with pytest.raises(ValueError, match="issue, task"):
        await client.promote_to_story("story", 5)


@respx.mock
async def test_create_task_posts_the_full_payload():
    route = respx.post(f"{TAIGA_URL}/tasks").mock(
        return_value=httpx.Response(
            201,
            json={"id": 9, "ref": 31, "subject": "Wire the form", "project": 1},
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    task = await client.create_task(
        project_id=1,
        subject="Wire the form",
        description="the details",
        user_story_id=5,
        sprint_id=10,
        assigned_to=42,
        tags=["frontend"],
    )
    sent = json.loads(route.calls.last.request.content)
    assert sent == {
        "project": 1,
        "subject": "Wire the form",
        "description": "the details",
        # Taiga names these `user_story` and `milestone`; the tool argument
        # names are friendlier and must be translated on the way out.
        "user_story": 5,
        "milestone": 10,
        "assigned_to": 42,
        "tags": ["frontend"],
    }
    assert task.id == 9


@respx.mock
async def test_create_task_resolves_status_against_task_statuses():
    # Tasks have their own status catalogue: resolving against
    # /userstory-statuses would find the wrong id, or none at all.
    statuses = respx.get(f"{TAIGA_URL}/task-statuses").mock(
        return_value=httpx.Response(200, json=[{"id": 77, "name": "In progress"}])
    )
    route = respx.post(f"{TAIGA_URL}/tasks").mock(
        return_value=httpx.Response(
            201, json={"id": 9, "ref": 31, "subject": "T", "project": 1}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.create_task(project_id=1, subject="T", status="In progress")
    assert statuses.calls.last.request.url.params["project"] == "1"
    assert json.loads(route.calls.last.request.content)["status"] == 77


@respx.mock
async def test_create_task_rejects_an_unknown_status_with_the_real_names():
    respx.get(f"{TAIGA_URL}/task-statuses").mock(
        return_value=httpx.Response(200, json=[{"id": 77, "name": "In progress"}])
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(ValueError, match="In progress"):
        await client.create_task(project_id=1, subject="T", status="Nonexistent")


@respx.mock
async def test_update_task_sends_the_current_version():
    # Tasks are version-checked like stories and epics: a PATCH without the
    # version Taiga currently holds is rejected as a conflict.
    respx.get(f"{TAIGA_URL}/tasks/9").mock(
        return_value=httpx.Response(
            200,
            json={"id": 9, "ref": 31, "subject": "T", "project": 1, "version": 4},
        )
    )
    route = respx.patch(f"{TAIGA_URL}/tasks/9").mock(
        return_value=httpx.Response(
            200, json={"id": 9, "ref": 31, "subject": "Renamed", "project": 1}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    task = await client.update_task(9, subject="Renamed")
    assert json.loads(route.calls.last.request.content) == {
        "version": 4,
        "subject": "Renamed",
    }
    assert task.subject == "Renamed"


@respx.mock
async def test_update_task_moves_it_under_another_story():
    respx.get(f"{TAIGA_URL}/tasks/9").mock(
        return_value=httpx.Response(
            200,
            json={"id": 9, "ref": 31, "subject": "T", "project": 1, "version": 4},
        )
    )
    route = respx.patch(f"{TAIGA_URL}/tasks/9").mock(
        return_value=httpx.Response(
            200, json={"id": 9, "ref": 31, "subject": "T", "project": 1}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_task(9, user_story_id=6)
    assert json.loads(route.calls.last.request.content)["user_story"] == 6


@respx.mock
async def test_update_task_clears_a_field_with_an_empty_string():
    respx.get(f"{TAIGA_URL}/tasks/9").mock(
        return_value=httpx.Response(
            200,
            json={"id": 9, "ref": 31, "subject": "T", "project": 1, "version": 4},
        )
    )
    route = respx.patch(f"{TAIGA_URL}/tasks/9").mock(
        return_value=httpx.Response(
            200, json={"id": 9, "ref": 31, "subject": "T", "project": 1}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    await client.update_task(9, description="")
    assert json.loads(route.calls.last.request.content)["description"] is None


@respx.mock
async def test_get_task_by_ref_queries_project_and_ref():
    route = respx.get(f"{TAIGA_URL}/tasks/by_ref").mock(
        return_value=httpx.Response(
            200, json={"id": 9, "ref": 31, "subject": "Wire the form", "project": 1}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    task = await client.get_task_by_ref(1, 31)
    params = route.calls.last.request.url.params
    assert params["project"] == "1"
    assert params["ref"] == "31"
    assert task.id == 9


@respx.mock
async def test_update_task_by_ref_resolves_the_ref_then_patches_by_id():
    # A #ref is only unique within its project, so the write itself must go to
    # the id endpoint — never to /tasks/by_ref.
    by_ref = respx.get(f"{TAIGA_URL}/tasks/by_ref").mock(
        return_value=httpx.Response(
            200, json={"id": 9, "ref": 31, "subject": "T", "project": 1, "version": 4}
        )
    )
    respx.get(f"{TAIGA_URL}/tasks/9").mock(
        return_value=httpx.Response(
            200, json={"id": 9, "ref": 31, "subject": "T", "project": 1, "version": 4}
        )
    )
    route = respx.patch(f"{TAIGA_URL}/tasks/9").mock(
        return_value=httpx.Response(
            200, json={"id": 9, "ref": 31, "subject": "Renamed", "project": 1}
        )
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    task = await client.update_task_by_ref(1, 31, subject="Renamed")
    assert by_ref.called
    assert json.loads(route.calls.last.request.content) == {
        "version": 4,
        "subject": "Renamed",
    }
    assert task.subject == "Renamed"


@respx.mock
async def test_update_task_by_ref_reports_a_missing_id_readably():
    respx.get(f"{TAIGA_URL}/tasks/by_ref").mock(
        return_value=httpx.Response(200, json={"ref": 31, "subject": "T"})
    )
    client = TaigaClient(TAIGA_URL, TOKEN, user_id=42)
    with pytest.raises(RuntimeError, match="missing 'id'"):
        await client.update_task_by_ref(1, 31, subject="Renamed")
