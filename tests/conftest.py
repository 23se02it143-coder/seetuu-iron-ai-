import os

os.environ.update(
    ENVIRONMENT="test", DATABASE_URL="sqlite://", RATE_LIMIT_ENABLED="false", SECRET_KEY="t" * 48,
    BCRYPT_ROUNDS="4", BASE_URL="http://testserver", ADMIN_EMAIL="admin@example.com",
    ADMIN_PASSWORD="Adm1n-Test-Passphrase!", ASSISTANT_PROVIDER="rules", PAYMENTS_PROVIDER="mock",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PASSWORD = "Correct-Horse-Battery-9"


@pytest.fixture(scope="session")
def _client():
    with TestClient(app, base_url="http://testserver") as c:
        yield c


@pytest.fixture()
def client(_client):
    _client.cookies.clear()
    return _client


@pytest.fixture()
def user(client):
    import uuid

    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/register", json={"name": "Test User", "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return {"email": email, "password": PASSWORD}


@pytest.fixture()
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Adm1n-Test-Passphrase!"})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture()
def override_settings(client):
    """get_settings() is @lru_cache'd (real request handling shouldn't re-read the environment on
    every call), so env vars set mid-test-session never take effect. FastAPI's own escape hatch for
    exactly this is dependency_overrides, which this wraps: start from the real cached Settings and
    layer the given fields on top, for every route that depends on get_settings, until the test ends.
    """
    from app.config import get_settings
    from app.main import app

    def _apply(**overrides):
        merged = get_settings().model_copy(update=overrides)
        app.dependency_overrides[get_settings] = lambda: merged
        return merged

    yield _apply
    app.dependency_overrides.pop(get_settings, None)
