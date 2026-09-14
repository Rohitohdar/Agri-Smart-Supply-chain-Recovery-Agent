"""Shared pytest fixtures.

Every test gets a fresh in-memory SQLite database, so nothing here touches the
developer's ``supply_chain.db``.

The rate limiter is disabled for the suite: hundreds of requests all arrive from
one address, so they would collide with each other long before they collided
with anything real. The security tests switch it back on deliberately for their
own checks.

**The developer's ``.env`` is never read.** Local settings must not be able to
change what the suite proves — an ``API_KEY`` there turns every ``/admin/reset``
into a 401, and a ``GROQ_API_KEY`` would send the agent tests to a real, paid
API. Both are exactly what a local ``.env`` holds, so the dotenv source is
switched off for the test process and the defaults apply instead.
"""

import os

# Must precede the app import below: the limiter reads this at construction.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# The system may have DEBUG set to a non-boolean value (e.g. "release" on some
# Windows machines). Override it to a known-good value before pydantic reads it.
os.environ["DEBUG"] = "false"

import pytest  # noqa: E402

from app.config import Settings  # noqa: E402

# Also before the app import: ``get_settings()`` is called at import time by
# ``app.db.session``, and its result is cached for the process.
Settings.model_config["env_file"] = None  # type: ignore[typeddict-item]
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base, import_models  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.ratelimit import limiter  # noqa: E402


def test_the_suite_ignores_the_developers_env_file():
    """A local .env must not be able to change these results."""
    assert get_settings().model_config.get("env_file") is None
    assert get_settings().api_key is None
    assert get_settings().groq_api_key is None


@pytest.fixture(autouse=True)
def rate_limiter_off():
    """Keep the limiter out of the way unless a test asks for it."""
    previous = limiter.enabled
    limiter.enabled = False
    limiter.reset()
    yield
    limiter.enabled = previous
    limiter.reset()


@pytest.fixture()
def session_factory():
    """A sessionmaker bound to a brand new in-memory SQLite database."""
    import_models()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared in-memory connection
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )


@pytest.fixture()
def client(session_factory):
    """Unseeded API client."""

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    # No context manager: the app lifespan is skipped so the real DB is untouched.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_client(client):
    """API client whose database has been reset to the seeded starting state."""
    response = client.post("/admin/reset")
    assert response.status_code == 200, response.text
    return client
