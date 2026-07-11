import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

# app.db builds a Supabase client at import time and requires these env vars.
# Set dummy values and neuter create_client so importing the router never needs
# real credentials or a network (the client is replaced by a fake per-test).
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_KEY", "test-key")

import supabase as _supabase_pkg  # noqa: E402

_supabase_pkg.create_client = lambda url, key: object()

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.roadmap.routes as routes_mod  # noqa: E402
from app.roadmap.routes import router  # noqa: E402


class _Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table):
        self.table = table

    def upsert(self, row):
        self.table.upserted.append(row)
        return self

    def execute(self):
        if self.table.raise_on_execute:
            raise RuntimeError("supabase down")
        return _Result([])


class FakeTable:
    def __init__(self, raise_on_execute=False):
        self.upserted = []
        self.raise_on_execute = raise_on_execute


class FakeSupabase:
    def __init__(self, raise_on_execute=False):
        self._table = FakeTable(raise_on_execute)

    def table(self, name):
        return FakeQuery(self._table)

    @property
    def upserted(self):
        return self._table.upserted


def _client(fake):
    routes_mod.supabase = fake
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _payload():
    return [
        {
            "user_id": "u_demo",
            "Classification": "neurodivergent",
            "score": [{"domain": "communication", "Score": "72%", "Severity": "moderate"}],
        }
    ]


def test_submit_success():
    fake = FakeSupabase()
    resp = _client(fake).post("/roadmap/submit", json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["classification"] == "ND"
    assert body["domains_received"] == 1
    assert body["context_ready"] is True
    assert fake.upserted[0]["user_id"] == "u_demo"


def test_submit_validation_error_is_422_with_code_and_field():
    fake = FakeSupabase()
    bad = [{"Classification": "ND", "score": [{"domain": "d", "Score": 1}]}]
    resp = _client(fake).post("/roadmap/submit", json=bad)
    assert resp.status_code == 422
    error = resp.json()["detail"]["error"]
    assert error["code"] == "missing_field"
    assert error["field"] == "user_id"
    assert fake.upserted == []


def test_submit_invalid_classification_is_422():
    resp = _client(FakeSupabase()).post(
        "/roadmap/submit",
        json=[{"user_id": "u", "Classification": "maybe", "score": [{"domain": "d", "Score": 1}]}],
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"]["code"] == "invalid_classification"


def test_submit_persistence_failure_is_503():
    resp = _client(FakeSupabase(raise_on_execute=True)).post("/roadmap/submit", json=_payload())
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"]["code"] == "persistence_unavailable"
