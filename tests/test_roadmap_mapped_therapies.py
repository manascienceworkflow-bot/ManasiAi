"""Integration tests for POST /roadmap/mapped-therapies.

Drives the real router through FastAPI's TestClient with `get_mappings` patched to
a fixture MappingBundle (no Excel I/O). Reuses the env-stub + fake-Supabase
bootstrap from test_roadmap_routes.py so importing the router needs no credentials.
"""

import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

# app.db builds a Supabase client at import time -- stub creds + neuter the client.
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_KEY", "test-key")

import supabase as _supabase_pkg  # noqa: E402

_supabase_pkg.create_client = lambda url, key: object()

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.roadmap.routes as routes_mod  # noqa: E402
import app.roadmap.services as services_mod  # noqa: E402
from app.roadmap.mapping_loader import MappingLoadError  # noqa: E402
from app.roadmap.mapping_models import MappingBundle, MappingDataset, ModalityRow  # noqa: E402
from app.roadmap.routes import router  # noqa: E402
from app.roadmap.severity_filter import MAX_DOMAINS  # noqa: E402


# --------------------------------------------------------------------------
# Fixture mapping bundle (stands in for the two workbooks).
# --------------------------------------------------------------------------


def _dataset(source, rows):
    return MappingDataset(
        source=source,
        path=f"/fixture/{source}.xlsx",
        sheet_name="Sheet",
        header_row=4,
        rows=tuple(rows),
    )


def _bundle():
    nd = _dataset("ND", [
        ModalityRow(domain="A. Sensory Processing", track="Spine", modality="MNRI", relevance="Primary", source_row=5),
        ModalityRow(domain=None, track=None, modality="Feldenkrais", relevance="Secondary", source_row=6),
        ModalityRow(domain="B. Communication", track="Complementary", modality="Speech Therapy", relevance="Primary", source_row=7),
    ])
    nt = _dataset("NT", [
        ModalityRow(domain="A. Sensory Processing", track="Spine", modality="OT", relevance="Primary", source_row=5),
    ])
    return MappingBundle(neurodivergent=nd, neurotypical=nt)


@pytest.fixture
def client(monkeypatch):
    """Router mounted on a bare app, with get_mappings -> fixture bundle. Patches
    the name as bound in the services module (where map_roadmap_therapies calls it)."""
    monkeypatch.setattr(services_mod, "get_mappings", lambda *a, **k: _bundle())
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _payload(domain="Sensory Processing", *, severity="High", domain_type="Spine",
             user_id="test001", classification="ND", wrap=False):
    body = {
        "user_id": user_id,
        "Classification": classification,
        "score": [{"domain": domain, "domain_type": domain_type, "Score": 85, "Severity": severity}],
    }
    return [body] if wrap else body


# --------------------------------------------------------------------------
# I1 / I2 -- happy path, bare object and array-wrapped
# --------------------------------------------------------------------------


def test_happy_path_returns_mapped_therapies(client):
    resp = client.post("/roadmap/mapped-therapies", json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "test001"
    assert body["classification"] == "ND"
    assert len(body["mapped_domains"]) == 1

    d = body["mapped_domains"][0]
    assert d["domain"] == "Sensory Processing"
    assert d["domain_type"] == "Spine"
    assert d["score"] == 85
    assert d["severity"] == "High"
    assert d["therapies"] == [
        {"therapy": "MNRI", "relevance": "Primary"},
        {"therapy": "Feldenkrais", "relevance": "Secondary"},
    ]

    # Therapy-centric view: one object per therapy, no duplicate names.
    agg = body["aggregated_therapies"]
    assert [a["therapy"] for a in agg] == ["MNRI", "Feldenkrais"]
    names = [a["therapy"] for a in agg]
    assert len(names) == len(set(names))
    assert agg[0]["domains"] == ["Sensory Processing"]
    assert agg[0]["relevance"] == ["Primary"]


def test_array_wrapped_payload_is_equivalent(client):
    bare = client.post("/roadmap/mapped-therapies", json=_payload()).json()
    wrapped = client.post("/roadmap/mapped-therapies", json=_payload(wrap=True)).json()
    assert bare == wrapped


# --------------------------------------------------------------------------
# I3-I9 -- validation + bad-body error mapping
# --------------------------------------------------------------------------


def test_multi_element_array_is_422(client):
    resp = client.post("/roadmap/mapped-therapies", json=[_payload(), _payload()])
    assert resp.status_code == 422


def test_missing_user_id_is_422_with_field(client):
    body = _payload()
    del body["user_id"]
    resp = client.post("/roadmap/mapped-therapies", json=body)
    assert resp.status_code == 422
    error = resp.json()["detail"]["error"]
    assert error["code"] == "missing_field"
    assert error["field"] == "user_id"


def test_invalid_classification_is_422(client):
    resp = client.post("/roadmap/mapped-therapies", json=_payload(classification="maybe"))
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"]["code"] == "invalid_classification"


def test_empty_score_list_is_422(client):
    body = _payload()
    body["score"] = []
    resp = client.post("/roadmap/mapped-therapies", json=body)
    assert resp.status_code == 422


def test_boolean_score_is_422(client):
    body = _payload()
    body["score"][0]["Score"] = True
    resp = client.post("/roadmap/mapped-therapies", json=body)
    assert resp.status_code == 422


def test_oversized_payload_is_413(client):
    body = _payload()
    body["score"] = [
        {"domain": f"d{i}", "Score": 50, "Severity": "High"} for i in range(MAX_DOMAINS + 1)
    ]
    resp = client.post("/roadmap/mapped-therapies", json=body)
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"]["code"] == "payload_too_large"


def test_non_json_body_is_400(client):
    resp = client.post(
        "/roadmap/mapped-therapies",
        content=b"{ not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# I10 / I11 -- empty actionable set and unmatched domain are 200, not errors
# --------------------------------------------------------------------------


def test_all_low_severity_is_200_with_empty_mapped_domains(client):
    resp = client.post("/roadmap/mapped-therapies", json=_payload(severity="Low"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["mapped_domains"] == []
    assert body["aggregated_therapies"] == []


def test_unmatched_domain_is_200_and_absent_from_mapped_domains(client):
    resp = client.post("/roadmap/mapped-therapies", json=_payload(domain="Nonexistent Domain"))
    assert resp.status_code == 200
    assert resp.json()["mapped_domains"] == []


def test_nt_classification_selects_nt_dataset(client):
    resp = client.post("/roadmap/mapped-therapies", json=_payload(classification="NT"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["classification"] == "NT"
    assert [t["therapy"] for t in body["mapped_domains"][0]["therapies"]] == ["OT"]


# --------------------------------------------------------------------------
# I12 -- mapping data unavailable is 500
# --------------------------------------------------------------------------


def test_mapping_data_unavailable_is_500(monkeypatch):
    def _raise(*a, **k):
        raise MappingLoadError("missing_workbook", "no file")

    monkeypatch.setattr(services_mod, "get_mappings", _raise)
    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).post("/roadmap/mapped-therapies", json=_payload())
    assert resp.status_code == 500
    assert resp.json()["detail"]["error"]["code"] == "mapping_data_unavailable"


# --------------------------------------------------------------------------
# I15 / I16 -- contract-only keys and idempotency
# --------------------------------------------------------------------------


def test_response_exposes_only_contract_keys(client):
    body = client.post("/roadmap/mapped-therapies", json=_payload()).json()
    assert set(body) == {"user_id", "classification", "mapped_domains", "aggregated_therapies"}
    d = body["mapped_domains"][0]
    assert set(d) == {"domain", "domain_type", "score", "severity", "therapies"}
    assert set(d["therapies"][0]) == {"therapy", "relevance"}
    a = body["aggregated_therapies"][0]
    assert set(a) == {"therapy", "domains", "relevance"}
    for leaked in ("source_row", "matched_domain", "diagnostics", "unmapped"):
        assert leaked not in str(body)


def test_idempotent_same_body_twice(client):
    first = client.post("/roadmap/mapped-therapies", json=_payload()).json()
    second = client.post("/roadmap/mapped-therapies", json=_payload()).json()
    assert first == second


# --------------------------------------------------------------------------
# I17 -- the new route does not disturb POST /roadmap/submit
# --------------------------------------------------------------------------


def test_submit_route_still_works(monkeypatch):
    class _FakeSupabase:
        def table(self, name):
            return self

        def upsert(self, row):
            return self

        def execute(self):
            class _R:
                data = []
            return _R()

    routes_mod.supabase = _FakeSupabase()
    monkeypatch.setattr(services_mod, "get_mappings", lambda *a, **k: _bundle())
    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).post(
        "/roadmap/submit",
        json=[{"user_id": "u", "Classification": "ND",
               "score": [{"domain": "communication", "Score": "72%", "Severity": "moderate"}]}],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
