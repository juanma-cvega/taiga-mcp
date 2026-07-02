from taiga_mcp.models import Epic, UserStory


def test_epic_parses_detail_fields():
    e = Epic(
        id=1, ref=5, subject="Epic A", project=10,
        description="details", tags=[["urgent", "#f00"]], is_blocked=True,
        blocked_note="waiting", assigned_to=42, color="#123456", version=3,
        status_extra_info={"name": "New"},
    )
    assert e.description == "details"
    assert e.color == "#123456"
    assert e.is_blocked is True
    assert e.version == 3
    assert e.status == "New"


def test_user_story_parses_detail_fields():
    s = UserStory(
        id=2, ref=9, subject="Story A", project=10,
        description="story details", tags=None, is_blocked=False,
        blocked_note=None, assigned_to=None, version=7,
        status_extra_info={"name": "In progress"},
    )
    assert s.description == "story details"
    assert s.version == 7
    assert s.status == "In progress"


def test_models_ignore_unknown_fields():
    # Taiga returns many fields we don't model; parsing must not fail.
    e = Epic(id=1, ref=5, subject="X", project=10, some_unmodeled_field=123)
    assert e.subject == "X"
