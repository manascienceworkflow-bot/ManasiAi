import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.roadmap.roadmap_loader import RoadmapValidationError  # noqa: E402
from app.roadmap.services import (  # noqa: E402
    ROADMAP_TABLE,
    get_roadmap_context_text,
    submit_roadmap,
)


class _Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """Chainable stand-in for a supabase query builder. Records the upserted row
    and replays a scripted select result -- no network, mirroring the hand-rolled
    fakes used elsewhere in this test suite (e.g. FakeLLM in test_safety_node)."""

    def __init__(self, table):
        self.table = table

    def upsert(self, row):
        self.table.upserted.append(row)
        return self

    def select(self, *args):
        return self

    def eq(self, *args):
        self.table.eq_args = args
        return self

    def execute(self):
        if self.table.raise_on_execute:
            raise RuntimeError("supabase down")
        return _Result(self.table.select_data)


class FakeTable:
    def __init__(self, select_data=None, raise_on_execute=False):
        self.select_data = select_data or []
        self.raise_on_execute = raise_on_execute
        self.upserted = []
        self.eq_args = None


class FakeSupabase:
    def __init__(self, select_data=None, raise_on_execute=False):
        self._table = FakeTable(select_data, raise_on_execute)
        self.table_names = []

    def table(self, name):
        self.table_names.append(name)
        return FakeQuery(self._table)

    @property
    def upserted(self):
        return self._table.upserted


def _payload():
    return [
        {
            "user_id": "u_demo",
            "Classification": "neurodivergent",
            "score": [{"domain": "communication", "Score": "72%", "Severity": "moderate"}],
        }
    ]


def test_submit_persists_and_acks():
    fake = FakeSupabase()
    ack = submit_roadmap(_payload(), fake)

    assert ack == {
        "status": "accepted",
        "user_id": "u_demo",
        "classification": "ND",
        "domains_received": 1,
        "context_ready": True,
    }
    assert fake.table_names == [ROADMAP_TABLE]
    row = fake.upserted[0]
    assert row["user_id"] == "u_demo"
    assert row["classification"] == "ND"
    # Score preserved verbatim in the stored raw payload.
    assert row["raw"]["score"][0]["Score"] == "72%"


def test_submit_rejects_bad_payload_without_persisting():
    fake = FakeSupabase()
    with pytest.raises(RoadmapValidationError):
        submit_roadmap([{"user_id": "u", "Classification": "x", "score": []}], fake)
    assert fake.upserted == []


def test_submit_propagates_persistence_error():
    fake = FakeSupabase(raise_on_execute=True)
    with pytest.raises(RuntimeError):
        submit_roadmap(_payload(), fake)


def test_get_context_renders_stored_roadmap():
    # A stored row shaped like the services.submit_roadmap dump (result.model_dump()
    # carries `raw`, which is what the loader re-validates).
    stored = {"result": {"raw": _payload()[0]}}
    fake = FakeSupabase(select_data=[stored])
    text = get_roadmap_context_text("u_demo", fake)
    assert "communication: 72%" in text
    assert "do not recommend therapies" in text.lower()


def test_get_context_empty_when_no_row():
    fake = FakeSupabase(select_data=[])
    assert get_roadmap_context_text("nobody", fake) == ""


def test_get_context_fails_safe_on_supabase_error():
    fake = FakeSupabase(raise_on_execute=True)
    # Must NOT raise -- a chat turn can never be broken by roadmap lookup.
    assert get_roadmap_context_text("u_demo", fake) == ""


def test_get_context_fails_safe_on_malformed_row():
    fake = FakeSupabase(select_data=[{"result": {"raw": {"garbage": True}}}])
    assert get_roadmap_context_text("u_demo", fake) == ""
