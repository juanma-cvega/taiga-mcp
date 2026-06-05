import pytest

TAIGA_URL = "https://api.taiga.io/api/v1"
TOKEN = "test-token"


@pytest.fixture
def taiga_url():
    return TAIGA_URL


@pytest.fixture
def token():
    return TOKEN
