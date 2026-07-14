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
from app.roadmap.severity_filter import MAX_DOMAINS  # noqa: E402


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


# --------------------------------------------------------------------------
# Step 2 -- severity filtering, end to end through the route
# --------------------------------------------------------------------------


def _severity_payload(*severities, user_id="u_demo"):
    return [
        {
            "user_id": user_id,
            "Classification": "neurodivergent",
            "score": [
                {"domain": f"domain_{i}", "Score": 50, "Severity": sev}
                for i, sev in enumerate(severities)
            ],
        }
    ]


def test_submit_reports_actionable_and_filtered_counts():
    resp = _client(FakeSupabase()).post(
        "/roadmap/submit", json=_severity_payload("High", "Low", "Moderate")
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["domains_received"] == 3
    assert body["domains_actionable"] == 2
    assert body["domains_filtered_out"] == 1
    assert body["filter_warnings"] == []


def test_submit_with_no_actionable_domains_is_200_not_an_error():
    """Everything scored Low is a legitimate, successful outcome -- the user is
    functioning adequately across every assessed domain."""
    fake = FakeSupabase()
    resp = _client(fake).post("/roadmap/submit", json=_severity_payload("Low", "Low"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["domains_actionable"] == 0
    assert body["context_ready"] is True
    assert fake.upserted  # still persisted


def test_submit_with_null_severity_warns_but_succeeds():
    resp = _client(FakeSupabase()).post(
        "/roadmap/submit",
        json=[
            {
                "user_id": "u_demo",
                "Classification": "ND",
                "score": [
                    {"domain": "attention", "Score": 72, "Severity": "High"},
                    {"domain": "memory", "Score": 40, "Severity": None},
                ],
            }
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["domains_actionable"] == 1
    assert len(body["filter_warnings"]) == 1
    assert "memory" in body["filter_warnings"][0]


def test_submit_with_unknown_severity_warns_but_succeeds():
    resp = _client(FakeSupabase()).post(
        "/roadmap/submit", json=_severity_payload("High", "Severe")
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["domains_actionable"] == 1
    assert "Severe" in body["filter_warnings"][0]


def test_submit_severity_is_case_and_whitespace_insensitive():
    resp = _client(FakeSupabase()).post(
        "/roadmap/submit", json=_severity_payload("  HIGH  ", "moderate", "LOW")
    )
    assert resp.status_code == 200
    assert resp.json()["domains_actionable"] == 2


def test_submit_oversized_payload_is_413_and_persists_nothing():
    fake = FakeSupabase()
    resp = _client(fake).post(
        "/roadmap/submit", json=_severity_payload(*(["High"] * (MAX_DOMAINS + 1)))
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"]["code"] == "payload_too_large"
    assert fake.upserted == []


def test_submit_duplicate_domains_keep_the_higher_severity():
    resp = _client(FakeSupabase()).post(
        "/roadmap/submit",
        json=[
            {
                "user_id": "u_demo",
                "Classification": "ND",
                "score": [
                    {"domain": "attention", "Score": 40, "Severity": "Low"},
                    {"domain": "attention", "Score": 72, "Severity": "High"},
                ],
            }
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["domains_actionable"] == 1
    assert body["domains_filtered_out"] == 1


def test_step1_failure_modes_are_unchanged_by_step2():
    """Non-regression: every pre-existing rejection still returns the same code."""
    client = _client(FakeSupabase())
    cases = [
        ([{"Classification": "ND", "score": [{"domain": "d", "Score": 1}]}], "missing_field"),
        ([{"user_id": "u", "Classification": "maybe", "score": [{"domain": "d", "Score": 1}]}],
         "invalid_classification"),
        ([{"user_id": "u", "Classification": "ND", "score": []}], "empty_scores"),
        ([{"user_id": "u", "Classification": "ND", "score": ["High"]}], "invalid_score_entry"),
    ]
    for payload, code in cases:
        resp = client.post("/roadmap/submit", json=payload)
        assert resp.status_code == 422, payload
        assert resp.json()["detail"]["error"]["code"] == code


def test_extra_fields_cannot_influence_the_filter():
    clean = _client(FakeSupabase()).post(
        "/roadmap/submit", json=_severity_payload("High", "Low")
    ).json()

    noisy_payload = _severity_payload("High", "Low")
    noisy_payload[0]["unexpected_top_level"] = "ignored"
    for entry in noisy_payload[0]["score"]:
        entry["confidence"] = 0.9
    noisy = _client(FakeSupabase()).post("/roadmap/submit", json=noisy_payload).json()

    assert noisy["domains_actionable"] == clean["domains_actionable"]
    assert noisy["domains_filtered_out"] == clean["domains_filtered_out"]
