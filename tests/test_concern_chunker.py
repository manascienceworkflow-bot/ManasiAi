import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.knowledge.concern_chunker import (  # noqa: E402
    CONTENT_TYPE,
    MATCHER_SECTION,
    SUMMARY_SECTION,
    chunk_concern,
    compute_chunk_id,
    deserialize_list,
    serialize_list,
    source_id_for,
)
from app.knowledge.concern_loader import get_concern_by_id, load_concern_data  # noqa: E402
from tests.test_concern_loader import build_concern_text, write_corpus  # noqa: E402


def load_record(tmp_path, **kwargs):
    base = write_corpus(tmp_path, {"communication/sample_concern.md": build_concern_text(**kwargs)})
    result = load_concern_data(base_dir=base)
    assert result.files_loaded == 1, result.issues
    return result.records[0]


# ---------------------------------------------------------------------------
# List serialization (Chroma metadata only accepts scalars)
# ---------------------------------------------------------------------------


def test_serialize_list_round_trips():
    values = ["speech_language", "communication"]
    assert serialize_list(values) == "|speech_language|communication|"
    assert deserialize_list(serialize_list(values)) == values


def test_serialize_empty_list_is_empty_string():
    assert serialize_list([]) == ""
    assert deserialize_list("") == []
    assert deserialize_list(None) == []


def test_pipe_wrapping_prevents_prefix_collisions():
    serialized = serialize_list(["sleep", "sleep_disorder"])
    assert "|sleep|" in serialized
    assert "|feed|" not in serialize_list(["feeding"])


# ---------------------------------------------------------------------------
# Chunk shape
# ---------------------------------------------------------------------------


def test_emits_matcher_summary_and_prose_chunks(tmp_path):
    chunks = chunk_concern(load_record(tmp_path))
    sections = [chunk.section for chunk in chunks]
    assert sections[0] == MATCHER_SECTION
    assert sections[1] == SUMMARY_SECTION
    assert "possible_explanations" in sections
    assert "professional_boundary" in sections


def test_phrasing_sections_are_folded_into_the_matcher_only(tmp_path):
    chunks = chunk_concern(load_record(tmp_path))
    sections = {chunk.section for chunk in chunks}
    assert "typical_user_questions" not in sections
    assert "alternative_user_phrasings" not in sections
    matcher = next(chunk for chunk in chunks if chunk.section == MATCHER_SECTION)
    assert "Sample question number 1?" in matcher.text
    assert "Sample phrasing 1." in matcher.text
    assert "my child is not speaking" in matcher.text  # a search_term
    assert "alpha" in matcher.text  # a keyword


def test_references_are_not_embedded(tmp_path):
    record = get_concern_by_id("speech_delay")
    assert "references" in record.sections
    assert "references" not in {chunk.section for chunk in chunk_concern(record)}


def test_every_chunk_carries_the_retrieval_header(tmp_path):
    for chunk in chunk_concern(load_record(tmp_path)):
        assert chunk.text.startswith("Sample Concern — ")


def test_metadata_envelope_is_complete(tmp_path):
    record = load_record(tmp_path)
    chunk = chunk_concern(record)[0]
    metadata = chunk.metadata
    assert metadata["content_type"] == CONTENT_TYPE
    assert metadata["concern_id"] == "sample_concern"
    assert metadata["concern_uid"] == "concerns/communication/sample_concern"
    assert metadata["category"] == "communication"
    assert metadata["source_id"] == "data/knowledge/concerns/communication/sample_concern.md"
    assert metadata["development_domains"] == "|speech_language|"
    assert metadata["escalation_sensitive"] is False
    assert metadata["last_updated"] == "2026-07-28"
    assert metadata["chunk_index"] == 0


def test_source_id_is_derived_from_uid_not_disk_layout(tmp_path):
    record = load_record(tmp_path)
    assert source_id_for(record) == f"data/knowledge/{record.concern_uid}.md"


def test_not_applicable_sections_are_not_chunked(tmp_path):
    record = load_record(tmp_path, sections={"Everyday Support Ideas": "- Not applicable for this concern."})
    assert "everyday_support_ideas" not in {chunk.section for chunk in chunk_concern(record)}


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------


def test_oversized_sections_split_on_bullet_boundaries(tmp_path):
    long_bullets = "\n".join(
        f"- Some children may show behaviour number {i} in ways that families notice across "
        f"many ordinary days at home and elsewhere." for i in range(1, 13)
    )
    record = load_record(tmp_path, sections={"Possible Explanations": long_bullets})
    parts = [chunk for chunk in chunk_concern(record, max_chunk_chars=400) if chunk.section == "possible_explanations"]
    assert len(parts) > 1
    for chunk in parts:
        body = chunk.text.split("\n\n", 1)[1]
        for line in body.splitlines():
            # Never cut mid-sentence: every line is a whole bullet.
            assert line.startswith("- ")
            assert line.rstrip().endswith(".")


def test_split_parts_are_numbered_and_counted(tmp_path):
    long_bullets = "\n".join(
        f"- Some children may show behaviour number {i} in ways that families notice across "
        f"many ordinary days at home and elsewhere." for i in range(1, 13)
    )
    record = load_record(tmp_path, sections={"Possible Explanations": long_bullets})
    parts = [chunk for chunk in chunk_concern(record, max_chunk_chars=400) if chunk.section == "possible_explanations"]
    assert [chunk.metadata["section_part"] for chunk in parts] == list(range(len(parts)))
    assert all(chunk.metadata["section_part_count"] == len(parts) for chunk in parts)


def test_matcher_chunk_is_never_split(tmp_path):
    record = load_record(tmp_path)
    matchers = [chunk for chunk in chunk_concern(record, max_chunk_chars=100) if chunk.section == MATCHER_SECTION]
    assert len(matchers) == 1


# ---------------------------------------------------------------------------
# Chunk IDs -- the property that makes re-ingestion idempotent
# ---------------------------------------------------------------------------


def test_chunk_id_is_section_keyed_not_index_keyed():
    assert compute_chunk_id("concerns/a/b", "summary") == compute_chunk_id("concerns/a/b", "summary")
    assert compute_chunk_id("concerns/a/b", "summary") != compute_chunk_id("concerns/a/b", "possible_explanations")
    assert compute_chunk_id("concerns/a/b", "summary", 0) != compute_chunk_id("concerns/a/b", "summary", 1)


def test_editing_one_section_leaves_other_chunk_ids_untouched(tmp_path):
    before = {chunk.section: chunk.chunk_id for chunk in chunk_concern(load_record(tmp_path))}
    edited = load_record(
        tmp_path,
        sections={"Things to Observe": "\n".join(f"- Whether the child now does new thing {i} at home." for i in range(1, 8))},
    )
    after = {chunk.section: chunk.chunk_id for chunk in chunk_concern(edited)}
    assert after["things_to_observe"] == before["things_to_observe"]  # id is stable...
    assert after["professional_boundary"] == before["professional_boundary"]  # ...and so are its neighbours
    assert len(after) == len(before)


def test_chunk_ids_are_unique_within_a_concern(tmp_path):
    chunks = chunk_concern(load_record(tmp_path))
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_real_corpus_chunk_ids_are_globally_unique():
    seen = set()
    for record in load_concern_data().records:
        for chunk in chunk_concern(record):
            assert chunk.chunk_id not in seen, f"duplicate chunk_id in {record.concern_id}"
            seen.add(chunk.chunk_id)
    assert len(seen) > 50
