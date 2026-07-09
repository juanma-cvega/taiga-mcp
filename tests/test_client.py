import json
import pytest
import respx
import httpx
from taiga_mcp.client import TaigaClient, _build_payload

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
                    "name": "Booking Engine",
                    "slug": "booking-engine",
                    "description": "My project",
                }
            ],
        )
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
                json=[{"id": 1, "name": "Booking Engine", "slug": "booking-engine"}],
            ),
        ]
    )

    async def refresh_token() -> str:
        return "new-token"

    client = TaigaClient(
        TAIGA_URL, "stale-token", user_id=42, refresh_token=refresh_token
    )
    projects = await client.list_projects()
    assert projects[0].name == "Booking Engine"
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
