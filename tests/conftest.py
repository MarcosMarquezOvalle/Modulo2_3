from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from modulo2_3.app import create_app
from sqlmodel import Session


@pytest.fixture()
def app():
    """Create the FastAPI app using an in-memory SQLite DB for isolation."""
    return create_app("sqlite:///:memory:")


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def session(app):
    engine = app.state._engine
    with Session(engine) as s:
        yield s
