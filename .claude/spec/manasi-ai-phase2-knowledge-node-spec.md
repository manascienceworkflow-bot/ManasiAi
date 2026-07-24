# Manasi AI — Phase 2 Technical Specification
## Knowledge Node

**Project:** Manasi AI
**Organization:** ManaScience
**Phase:** 2 of N — Knowledge Node
**Status:** Draft for implementation
**Audience:** Python + FastAPI + LangGraph engineer
**Depends on:** Phase 1 — Understanding Node (`manasi-ai-phase1-understanding-node-spec.md`)

---

## 1. Executive Summary

Phase 1 (the Understanding Node) converts a raw user message into a structured object — `intent`, `topic`, `search_query`, `emotional_state` — and performs no retrieval or answering. This document specifies **Phase 2 only: the Knowledge Node**, the second node in the Manasi AI LangGraph pipeline.

The Knowledge Node's sole responsibility is to take the Understanding Node's output and retrieve relevant reference material from ManaScience's own knowledge base — courses, blogs, research articles, FAQs, practitioner information, therapy information, website content, neuroplasticity content, and PDF documents — stored and searched via **ChromaDB** with **OpenAI embeddings** through a **LangChain retriever**. It then decides whether enough relevant ManaScience material was found to ground an answer (`source = "rag"`) or whether downstream nodes must fall back to the LLM's general knowledge (`source = "llm"`).

The Knowledge Node performs **no answer generation, no empathy transformation, no disclaimer logic, and no user-facing text production of any kind**. It returns only structured context: a source decision, a confidence score, and a ranked list of retrieved chunks. Retrieved chunks are reference material for later phases (Understand → Simplify → Explain → Humanize), never a response in themselves.

ManaScience's own knowledge is always the highest-priority source. The Knowledge Node exists to enforce that priority mechanically — by retrieving from ManaScience content first and only signaling an LLM fallback when ManaScience genuinely has nothing relevant — rather than leaving that judgment to a later, harder-to-audit generation step.

---

## 2. Business Objective

Manasi's credibility depends on answers being grounded in ManaScience's own clinical, scientific, and platform content whenever that content exists — a generic LLM answer about neuroplasticity is not wrong, but it is not *ManaScience's* answer, and it cannot reflect ManaScience's specific therapies, courses, practitioners, or positioning. Users (parents, caregivers, practitioners, learners) need to trust that when Manasi speaks about ManaScience-specific topics, it is speaking from ManaScience's actual material, not improvising.

The Knowledge Node exists to make that trust mechanical and auditable rather than implicit:

* **Priority enforcement.** ManaScience content is always searched first and preferred; general LLM knowledge is a fallback, never a default.
* **Separation of retrieval from generation.** By deciding `source` and confidence *before* any answer is written, later phases (response generation, empathy transformation) inherit a clean, already-validated decision instead of having to judge document relevance themselves while also trying to write a good answer.
* **Debuggability.** If Manasi gives a bad or ungrounded answer, engineers can inspect the Knowledge Node's output independently: was `source` wrong? Was `confidence` miscalibrated? Were the retrieved chunks actually irrelevant? This isolates the fault to retrieval, separate from generation quality.
* **Scalability of content.** As ManaScience adds courses, blogs, research, and practitioner profiles, the Knowledge Node's contract (structured retrieval + source decision) does not change — only the underlying ChromaDB collection grows.

---

## 3. Functional Requirements

### FR-1: Structured Input Consumption
The node SHALL accept the Phase 1 Understanding output (`intent`, `topic`, `search_query`, `emotional_state`) as input and SHALL NOT require or depend on the raw user message directly — `search_query` is the only field used to drive retrieval.

### FR-2: Retrieval Skip Logic
The node SHALL skip vector search entirely when `intent == "general_chat"` (where `search_query` is always `""` per the Phase 1 contract), returning immediately with `source = "llm"`, `confidence = 0.0`, `retrieved_docs = []`, and `retrieval_skipped = true`. This avoids wasted embedding/search calls for messages with nothing to retrieve.

### FR-3: Vector Search
For all other intents, the node SHALL embed `search_query` using the configured OpenAI embedding model and SHALL execute a similarity search against the ManaScience ChromaDB collection.

### FR-4: Metadata-Aware Filtering
The node SHALL apply an intent-to-content-type metadata filter (Section 6.2) to bias retrieval toward the most relevant content types for the given intent, and SHALL retry once without the filter if the filtered search returns fewer than `RAG_MIN_RELEVANT_CHUNKS` qualifying chunks, so that a narrow filter never silently starves retrieval.

### FR-5: Top-K Retrieval and Ranking
The node SHALL retrieve up to `KNOWLEDGE_TOP_K` candidate chunks per search, score each by similarity, and rank them in descending order of relevance.

### FR-6: Relevance Thresholding
The node SHALL discard candidate chunks whose similarity score falls below `RAG_SIMILARITY_THRESHOLD` before they are considered for the output, since a low-similarity chunk is noise, not reference material.

### FR-7: Source Decision
The node SHALL set `source = "rag"` if and only if at least `RAG_MIN_RELEVANT_CHUNKS` chunks survive the relevance threshold (Section 7.3). Otherwise it SHALL set `source = "llm"`.

### FR-8: Context Aggregation
When `source = "rag"`, the node SHALL aggregate the surviving chunks into `retrieved_docs`, deduplicated by `chunk_id`, capped at `KNOWLEDGE_MAX_RETURNED_CHUNKS` chunks and `KNOWLEDGE_MAX_CONTEXT_CHARS` total characters, dropping lowest-ranked chunks first if the cap is exceeded.

### FR-9: Structured Output Only
The node SHALL emit a single JSON-serializable object conforming to the schema in Section 8. The node SHALL NOT emit prose, markdown narrative, explanations, summaries, or any text intended to be shown directly to the user.

### FR-10: No Document Dumping
Retrieved chunk `content` fields are raw reference material only. The node SHALL NOT rewrite, summarize, simplify, or "humanize" chunk content — that responsibility belongs entirely to future nodes (Understand → Simplify → Explain → Humanize, Phase 3+).

### FR-11: Graceful Degradation on Infrastructure Failure
If the ChromaDB client or embedding call fails (timeout, connection error, API error), the node SHALL NOT raise an unhandled exception. It SHALL catch the failure, log it, and return `source = "llm"`, `confidence = 0.0`, `retrieved_docs = []`, with `error` populated (Section 8.6), so the graph can continue safely.

### FR-12: Determinism Within Tolerance
Given the same `search_query` and an unchanged collection, repeated invocations SHOULD return the same `source` decision and the same top-ranked chunks. Similarity scores are deterministic functions of the embedding model and stored vectors, so this holds as long as the embedding model version is pinned (Section 5.5).

---

## 4. Non-Functional Requirements

### 4.1 General NFRs

| Category | Requirement |
|---|---|
| **Latency** | The Knowledge Node SHOULD complete in under 800ms p95 (embedding call + vector search + ranking), since it sits between Understanding and Response Generation in the user-facing latency budget. |
| **Reliability** | The node MUST always return a valid, schema-conforming output (Section 8), even on vector store or embedding failure (FR-11). It MUST NOT raise an unhandled exception under any input. |
| **Statelessness** | The node SHALL be a pure function of (`understanding`) → JSON. It SHALL NOT mutate Phase 1's `understanding` object, persist conversation state, or call any generation LLM. |
| **Testability** | The node MUST be unit-testable in isolation using a fixture ChromaDB collection, independent of Phases 1 and 3. |
| **Observability** | Every invocation SHOULD be logged with `search_query`, `intent`, `source`, `confidence`, chunk count, and latency, to support threshold tuning over time. |
| **Cost** | The node SHOULD use the smallest embedding model that meets relevance-accuracy targets (`text-embedding-3-small` by default) and SHALL NOT call a chat/completion LLM for retrieval or scoring — similarity scoring is vector math, not an LLM call. |
| **Extensibility** | Adding a new content type (e.g., a new "webinar" type) SHALL require only a metadata convention and ingestion update, not a structural rewrite of the node. |
| **Privacy** | Practitioner information chunks MUST NOT include unpublished personal contact details beyond what ManaScience has approved for public/platform display; the node performs no additional PII inference. |

### 4.2 Performance Targets

| Metric | Target | Notes |
|---|---|---|
| Embedding call latency (query) | p95 < 300ms | Single short string embedded per call; no batching needed at query time. |
| Vector search latency | p95 < 100ms | For a ManaScience-scale collection (low hundreds of thousands of chunks); re-evaluate if collection exceeds ~1M chunks. |
| End-to-end node latency | p95 < 800ms | Embedding + search + ranking + aggregation, excluding network to the API layer. |
| Max returned chunks | 4 (`KNOWLEDGE_MAX_RETURNED_CHUNKS`) | Bounds what downstream generation must read; tunable per deployment. |
| Max aggregated context size | 6,000 characters (`KNOWLEDGE_MAX_CONTEXT_CHARS`) | Approx. 1,500 tokens; keeps Phase 3's prompt budget predictable regardless of how verbose source documents are. |
| Candidate pool size (pre-filter) | 8 (`KNOWLEDGE_TOP_K`) | Wider than the returned-chunk cap so thresholding/dedup has room to discard noise without under-filling. |
| Cost per retrieval | ~1 embedding call (≈10–50 tokens) | No chat-completion cost; cost scales with query volume, not response length. |
| Scalability | Linear collection growth | Single collection with metadata filtering scales to ManaScience's expected content volume (courses + blogs + research + FAQs + practitioner + therapy + website + neuroplasticity + PDFs in the thousands of chunks); see Section 13 for sharding considerations beyond that. |

---

## 5. ChromaDB Architecture

### 5.1 Collection Structure

Manasi AI uses **a single ChromaDB collection**, `manascience_knowledge`, holding chunks from all nine content types, distinguished by a `content_type` metadata field rather than separate collections per type.

**Rationale:** a single collection allows cross-type relevance ranking (e.g., a query about "neuroplasticity in children" may best be answered by a blog chunk, not necessarily a `neuroplasticity_content` chunk) without having to fan out queries across many collections and merge results. Metadata filtering (Section 6.2) still lets retrieval bias toward the content types most relevant to a given `intent` without losing the option to fall through to the full collection. If a single content type grows large enough to dominate or pollute results for other types, splitting it into its own collection is a future consideration (Section 13), not a Phase 2 requirement.

```python
import chromadb

client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
collection = client.get_or_create_collection(
    name=settings.chroma_collection_name,
    metadata={"hnsw:space": "cosine"},
)
```

Using `hnsw:space = "cosine"` makes Chroma's returned distance directly convertible to an interpretable similarity score (Section 7.4), rather than raw squared L2 distance.

### 5.2 Metadata Design

Every chunk stored in the collection carries a common metadata envelope, plus content-type-specific fields. Chroma metadata values must be flat scalars (str/int/float/bool) — no nested objects — so type-specific fields are flattened with predictable, optional keys (absent when not applicable).

**Common fields (required on every chunk):**

| Field | Type | Description |
|---|---|---|
| `chunk_id` | str | Deterministic ID: `sha256(source_id + ":" + chunk_index)`. Used as the Chroma document ID so re-ingestion upserts instead of duplicating. |
| `content_type` | str (enum) | One of: `course`, `blog`, `research_article`, `faq`, `practitioner_info`, `therapy_info`, `website_content`, `neuroplasticity_content`, `pdf_document`. |
| `source_id` | str | Stable identifier of the parent document (filename, CMS slug, or PDF identifier). |
| `source_title` | str | Human-readable title of the parent document. |
| `source_url` | str \| None | Public URL if the content is web-accessible; `None` for internal-only content (e.g., some practitioner records). |
| `chunk_index` | int | Position of this chunk within its parent document, for ordering/debugging. |
| `ingested_at` | str (ISO 8601) | Timestamp of last ingestion/upsert, for staleness auditing. |

**Content-type-specific fields (present only when relevant):**

| Content Type | Extra Metadata Fields |
|---|---|
| `course` | `course_id`, `course_level`, `course_duration` |
| `blog` | `author`, `published_date`, `tags` (comma-joined string; Chroma metadata has no native list type) |
| `research_article` | `authors`, `publication_year`, `doi_or_source` |
| `faq` | `faq_category` |
| `practitioner_info` | `practitioner_name`, `specialty`, `location` |
| `therapy_info` | `therapy_name`, `age_group`, `conditions_addressed` |
| `website_content` | `page_section` |
| `neuroplasticity_content` | `concept_tags` (comma-joined string) |
| `pdf_document` | `page_number`, `document_title` |

### 5.3 Content-Type-Specific Storage and Chunking

| Content Type | Typical Source Format | Loader | Chunking Approach | Why |
|---|---|---|---|---|
| Courses | Markdown / CMS export | `TextLoader` or CMS connector | One chunk per logical section (overview, outcomes, curriculum); `chunk_size≈600`, `overlap≈80` | Course sections are short and self-contained; over-splitting fragments the value proposition. |
| Blogs | Markdown / HTML | `TextLoader` / `BSHTMLLoader` | `RecursiveCharacterTextSplitter`, `chunk_size=800`, `overlap=120`, split on headers first | Matches the existing Phase 0 prototype's proven separator strategy (`["\n## ", "\n### ", "\n---\n", "\n\n", "\n", " ", ""]`). |
| Research Articles | PDF / Markdown summaries | `PyPDFLoader` / `TextLoader` | `chunk_size=900`, `overlap=150`, preserve section headers (Abstract/Methods/Results) where present | Slightly larger chunks preserve scientific context that short chunks would sever mid-finding. |
| FAQs | Markdown / structured Q&A | Custom FAQ parser (one Q&A pair per chunk) | **No further splitting** — one chunk = one question + its full answer | Splitting an FAQ answer mid-sentence produces an incoherent retrieved chunk; atomic Q&A pairs retrieve cleanly. |
| Practitioner Information | Markdown / CMS / DB export | Custom loader | One chunk per practitioner profile (bio + specialty + approach) | Profiles are retrieved as a unit; partial-profile chunks are not useful reference material. |
| Therapy Information | Markdown | `TextLoader` | `chunk_size=700`, `overlap=100`, split on therapy sub-sections | Mirrors the existing `manascience_therapies.md` structure already in `data/`. |
| Website Content | HTML / Markdown | `BSHTMLLoader` / `TextLoader` | `chunk_size=800`, `overlap=100` | Standard prose chunking; website pages are typically short. |
| Neuroplasticity Content | Markdown / long-form articles | `TextLoader` | `chunk_size=800`, `overlap=120` | Standard prose chunking for educational/explainer material. |
| PDF Documents | PDF | `PyPDFLoader` | `chunk_size=900`, `overlap=150`, retain `page_number` per chunk | Page-level metadata lets future nodes cite "page 4" rather than just a document title. |

### 5.4 Embedding Strategy

* **Model:** `text-embedding-3-small` (1536 dimensions) by default, configured via `KNOWLEDGE_EMBEDDING_MODEL`, independent of (but defaulting to the same value as) Phase 0's `OPENAI_EMBEDDING_MODEL` so the two systems can diverge later without coupling.
* **Ingestion-time embedding:** batched (batch size 100) when building/rebuilding the collection, to minimize API round-trips.
* **Query-time embedding:** a single `search_query` string embedded per Knowledge Node invocation — no batching needed.
* **Model pinning:** the embedding model used for ingestion and the model used for query-time embedding MUST match. If the model is changed, the entire collection MUST be re-embedded and re-ingested (Section 5.6) — mixed-model vectors in one collection produce meaningless similarity scores.

### 5.5 Retrieval Strategy

Retrieval is **similarity search with optional metadata pre-filtering**, not full LangChain `RetrievalQA`/generation chains — the Knowledge Node only retrieves, it never generates. The LangChain `Chroma` vector store wrapper is used purely for its retriever interface:

```python
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

vectorstore = Chroma(
    client=chroma_client,
    collection_name=settings.chroma_collection_name,
    embedding_function=OpenAIEmbeddings(model=settings.knowledge_embedding_model),
)

candidates = vectorstore.similarity_search_with_relevance_scores(
    query=search_query,
    k=settings.knowledge_top_k,
    filter={"content_type": {"$in": allowed_content_types}} if allowed_content_types else None,
)
```

`similarity_search_with_relevance_scores` returns `(Document, score)` pairs where `score` is already normalized to a 0–1 relevance scale by LangChain's Chroma integration (using the collection's cosine space), which is what Section 7 thresholds operate on.

### 5.6 Ingestion Pipeline and Idempotent Updates

Unlike the Phase 0 FAISS prototype (`app/rag/ingest.py`), which rebuilds a full index from scratch, Chroma's `upsert` is keyed by `chunk_id` and is natively idempotent: re-running ingestion after editing a single blog post re-embeds and overwrites only the chunks belonging to that document, leaving the rest of the collection untouched.

```python
collection.upsert(
    ids=[c["chunk_id"] for c in chunks],
    embeddings=embeddings.embed_documents([c["content"] for c in chunks]),
    documents=[c["content"] for c in chunks],
    metadatas=[c["metadata"] for c in chunks],
)
```

A recommended `scripts/build_knowledge_index.py` (Section 10) iterates each content source directory, computes chunks + `chunk_id`s, and calls `upsert` — safe to run repeatedly, including in a scheduled re-ingestion job as ManaScience content changes.

---

## 6. Retrieval Pipeline

### 6.1 Pipeline Steps

```
Understanding output (intent, topic, search_query, emotional_state)
        │
        ▼
1. Skip check — intent == "general_chat"? ──yes──► return llm fallback (Section 3, FR-2)
        │ no
        ▼
2. Resolve allowed content_type filter from intent (Section 6.2)
        │
        ▼
3. Embed search_query (OpenAI embeddings)
        │
        ▼
4. similarity_search_with_relevance_scores(query, k=KNOWLEDGE_TOP_K, filter=allowed_types)
        │
        ▼
5. Filtered search returned < RAG_MIN_RELEVANT_CHUNKS chunks above threshold?
        │
   yes ─┴─► retry once with filter=None (search full collection)
        │
        ▼
6. Discard chunks with relevance_score < RAG_SIMILARITY_THRESHOLD
        │
        ▼
7. Rank surviving chunks descending by relevance_score
        │
        ▼
8. Source decision (Section 7.3)
        │
        ▼
9. Aggregate + cap (KNOWLEDGE_MAX_RETURNED_CHUNKS, KNOWLEDGE_MAX_CONTEXT_CHARS)
        │
        ▼
Structured KnowledgeOutput (Section 8)
```

### 6.2 Intent → Content-Type Filter Mapping

This filter biases retrieval toward the most plausible content types for a given intent, without making it impossible to retrieve from other types — it is a first-pass filter, with the no-filter retry in step 5 as a safety net (e.g., a `therapy_information` question might be best answered by a `research_article` chunk that the narrow filter would otherwise hide).

| Intent | Allowed `content_type`s (first pass) |
|---|---|
| `concept_explanation` | `neuroplasticity_content`, `blog`, `research_article` |
| `therapy_information` | `therapy_info`, `faq`, `blog` |
| `course_information` | `course`, `faq` |
| `research_information` | `research_article`, `pdf_document` |
| `website_information` | `website_content`, `faq` |
| `personal_concern` | `therapy_info`, `practitioner_info`, `neuroplasticity_content`, `faq` |
| `emotional_support` | `faq`, `website_content` (light retrieval only — see 6.4) |
| `general_chat` | retrieval skipped entirely (FR-2) |

### 6.3 Similarity Search

* **Top-K candidate pool:** `KNOWLEDGE_TOP_K = 8` by default — wider than the final returned-chunk cap so that thresholding and deduplication have room to discard noise without leaving too few results.
* **Distance → similarity:** with the collection configured for cosine space, LangChain's Chroma integration returns a relevance score already normalized to `[0, 1]`, where 1.0 is a perfect match. No manual distance conversion is required when using `similarity_search_with_relevance_scores`; if a lower-level Chroma client call is used instead (returning raw cosine distance), convert via `similarity = 1 - distance`.

### 6.4 Relevance Scoring and Context Aggregation

* Each candidate chunk's `relevance_score` is the cosine similarity between the embedded `search_query` and the chunk's stored embedding.
* Chunks below `RAG_SIMILARITY_THRESHOLD` (default `0.72`) are discarded before aggregation — they are not "weak matches" included for completeness, they are noise.
* Surviving chunks are deduplicated by `chunk_id` (relevant mainly when the no-filter retry re-surfaces a chunk already seen in the filtered pass).
* Surviving chunks are capped at `KNOWLEDGE_MAX_RETURNED_CHUNKS` (default `4`), dropping the lowest-ranked first.
* If the cumulative character length of included chunks would exceed `KNOWLEDGE_MAX_CONTEXT_CHARS` (default `6000`), chunks are dropped from the bottom of the ranking until the cap is satisfied — never truncated mid-chunk, since a truncated chunk is misleading reference material.
* For `emotional_support`, retrieval is intentionally light: it only surfaces supportive/FAQ-type resources if a strong match exists (same threshold, no special-casing of the threshold itself); there is no requirement to force a match, and `source = "llm"` is an entirely acceptable, expected outcome for most `emotional_support` queries.

---

## 7. Source Detection Logic

### 7.1 Why Source Detection Matters

ManaScience's value proposition depends on Manasi never presenting generic LLM knowledge as if it were ManaScience's own clinical or scientific position. The source decision is the mechanism that enforces the Knowledge Priority Rule: ManaScience content is used whenever it genuinely exists and is relevant; the LLM fallback is used only when it does not. Getting this decision wrong in either direction is costly — false `"rag"` results ground an answer in irrelevant content and erode trust when the mismatch is visible; false `"llm"` results discard genuinely useful ManaScience material and make Manasi sound generic when it should sound authoritative.

### 7.2 Thresholds and Configuration

| Setting | Default | Meaning |
|---|---|---|
| `RAG_SIMILARITY_THRESHOLD` | `0.72` | Minimum cosine similarity for a chunk to be considered relevant at all. |
| `RAG_MIN_RELEVANT_CHUNKS` | `1` | Minimum number of chunks above threshold required to decide `source = "rag"`. |
| `KNOWLEDGE_TOP_K` | `8` | Candidate pool size per search. |
| `KNOWLEDGE_MAX_RETURNED_CHUNKS` | `4` | Cap on chunks included in the output. |
| `KNOWLEDGE_MAX_CONTEXT_CHARS` | `6000` | Cap on total aggregated `content` length. |

These are tunable per deployment via environment variables (Section 10), since the "right" threshold is an empirical property of the embedding model and ManaScience's actual content density — Phase 2 ships with sensible defaults, not values claimed to be optimal without measurement (see Acceptance Criteria, Section 12).

### 7.3 Decision Algorithm

```python
def decide_source(scored_chunks: list[tuple[Document, float]]) -> tuple[str, float, list]:
    relevant = [
        (doc, score) for doc, score in scored_chunks
        if score >= settings.rag_similarity_threshold
    ]
    relevant.sort(key=lambda pair: pair[1], reverse=True)

    if len(relevant) >= settings.rag_min_relevant_chunks:
        top_score = relevant[0][1]
        return "rag", round(top_score, 2), relevant
    return "llm", 0.0, []
```

* **`source = "rag"`** when at least `RAG_MIN_RELEVANT_CHUNKS` chunks clear the threshold. `confidence` is the top-ranked surviving chunk's similarity score, rounded to two decimal places — a direct, auditable measure of "how good was our best match," not a derived or LLM-judged score.
* **`source = "llm"`** when fewer than `RAG_MIN_RELEVANT_CHUNKS` chunks clear the threshold. `confidence` is always `0.0` in this case — there is no partial credit for near-misses; downstream nodes should treat `"llm"` as a clean signal to answer from general knowledge, not a hint that ManaScience content was "close."

### 7.4 Confidence Scoring

Confidence is **not** an LLM-judged or learned score in Phase 2 — it is the raw cosine similarity of the best-matching chunk. This keeps the node fast, cheap, and fully deterministic (no extra LLM call to "grade" relevance). A learned/calibrated confidence model is a candidate future improvement (Section 13) once enough labeled retrieval outcomes exist to train or validate one.

### 7.5 Edge Cases

* **Empty collection / collection not yet built:** treated identically to "no relevant chunks found" — `source = "llm"`, with a logged warning distinguishing "empty collection" from "no match in a populated collection" for operational visibility.
* **Embedding or Chroma call failure:** handled by FR-11 — returns the same `source = "llm"` shape with `error` populated (Section 8.6), not a different error schema, so downstream nodes have exactly one fallback code path to handle.
* **Borderline single-chunk match exactly at threshold:** included as relevant (`score >= threshold` is inclusive); the threshold default of `0.72` is deliberately conservative against false positives — tune via measurement (Section 12.1), not by changing the comparison operator.
* **Filtered search starves valid results:** handled by the no-filter retry (Section 6.1, step 5) before falling back to `"llm"`.

---

## 8. JSON Schema

### 8.1 Input Contract (recap from Phase 1)

The Knowledge Node consumes exactly the Phase 1 `Understanding` object:

```json
{
  "intent": "therapy_information",
  "topic": "occupational therapy for sensory issues",
  "search_query": "occupational therapy effectiveness sensory issues",
  "emotional_state": "curious"
}
```

### 8.2 Output Schema Definition

```json
{
  "source": "rag",
  "retrieved_docs": [
    {
      "chunk_id": "a1b2c3d4e5f6",
      "content": "ManaScience's occupational therapy program focuses on sensory integration through structured play-based activities tailored to each child's sensory profile...",
      "content_type": "therapy_info",
      "source_title": "ManaScience Therapies — Occupational Therapy",
      "source_url": "https://manascience.com/therapies/occupational-therapy",
      "similarity_score": 0.91,
      "metadata": {
        "therapy_name": "Occupational Therapy",
        "age_group": "children",
        "conditions_addressed": "sensory processing, fine motor skills"
      }
    }
  ],
  "confidence": 0.91,
  "query_used": "occupational therapy effectiveness sensory issues",
  "intent": "therapy_information",
  "retrieval_skipped": false,
  "content_types_searched": ["therapy_info", "faq", "blog"],
  "retrieval_time_ms": 412.3,
  "error": null
}
```

LLM-fallback shape:

```json
{
  "source": "llm",
  "retrieved_docs": [],
  "confidence": 0.0,
  "query_used": "history of left-handedness in famous artists",
  "intent": "concept_explanation",
  "retrieval_skipped": false,
  "content_types_searched": ["neuroplasticity_content", "blog", "research_article"],
  "retrieval_time_ms": 358.7,
  "error": null
}
```

The minimal `{"source", "retrieved_docs", "confidence"}` shape from the original product brief is the **required core subset** of this schema; the additional fields (`query_used`, `intent`, `retrieval_skipped`, `content_types_searched`, `retrieval_time_ms`, `error`) are required production fields that give downstream nodes and observability tooling enough context to act on the decision without re-deriving it.

### 8.3 `RetrievedDocument` Object Schema

| Field | Type | Required | Notes |
|---|---|---|---|
| `chunk_id` | string | Yes | Stable chunk identifier (Section 5.2). |
| `content` | string | Yes | Raw chunk text. Reference material only — never pre-summarized (FR-10). |
| `content_type` | string (enum) | Yes | One of the nine content types (Section 5.2). |
| `source_title` | string | Yes | Human-readable parent document title. |
| `source_url` | string \| null | Yes | Nullable; `null` for internal-only content. |
| `similarity_score` | float | Yes | Cosine similarity in `[0, 1]`, rounded to 2 decimals. |
| `metadata` | object | Yes | Content-type-specific fields (Section 5.2); may be `{}` if none apply. |

### 8.4 Top-Level Field Definitions

| Field | Type | Required | Allowed Values | Notes |
|---|---|---|---|---|
| `source` | string (enum) | Yes | `"rag"`, `"llm"` | Never any other value. |
| `retrieved_docs` | array of `RetrievedDocument` | Yes | — | MUST be `[]` when `source == "llm"`. MUST be non-empty when `source == "rag"`. |
| `confidence` | float | Yes | `0.0`–`1.0` | MUST be `0.0` when `source == "llm"`. MUST be `> 0` when `source == "rag"` (in practice `>= RAG_SIMILARITY_THRESHOLD`). |
| `query_used` | string | Yes | — | The exact string searched; `""` when `retrieval_skipped == true`. |
| `intent` | string | Yes | Same enum as Phase 1's `intent` | Passed through unchanged for downstream convenience; the Knowledge Node does not reinterpret it. |
| `retrieval_skipped` | boolean | Yes | — | `true` only for `intent == "general_chat"` (FR-2). |
| `content_types_searched` | array of string | Yes | Subset of the nine content types | `[]` when `retrieval_skipped == true`. Reflects whichever pass (filtered or no-filter retry) ultimately produced the returned result. |
| `retrieval_time_ms` | float | Yes | — | Wall-clock time for the node's work, for latency monitoring (Section 4.2). |
| `error` | string \| null | Yes | — | `null` on success; a short machine-readable error code (Section 8.6) on infrastructure failure. |

### 8.5 Validation Rules

* The output MUST be a single JSON-serializable object (in-process, a Pydantic model; at any API boundary, valid JSON) — no surrounding prose.
* `source`, `retrieved_docs`, and `confidence` MUST be mutually consistent per the rules in Section 8.4 (empty docs + zero confidence iff `"llm"`; non-empty docs + positive confidence iff `"rag"`). A Pydantic `model_validator` enforces this, mirroring the pattern already used for Phase 1's `UnderstandingOutput` (`app/nodes/understanding_node.py`).
* `retrieved_docs` MUST NOT exceed `KNOWLEDGE_MAX_RETURNED_CHUNKS` entries.
* No field SHALL contain user-facing prose intended as a final answer — `content` is raw source material, not a drafted response.

### 8.6 Error Handling

On embedding or Chroma failure (FR-11), the node returns the `"llm"` shape with a populated `error` code instead of raising:

```json
{
  "source": "llm",
  "retrieved_docs": [],
  "confidence": 0.0,
  "query_used": "ManaScience therapies offered",
  "intent": "therapy_information",
  "retrieval_skipped": false,
  "content_types_searched": [],
  "retrieval_time_ms": 1203.5,
  "error": "vectorstore_unavailable"
}
```

Recognized `error` codes: `"vectorstore_unavailable"` (Chroma connection/timeout), `"embedding_failure"` (OpenAI embeddings API error), `null` (no error). These are logged as `knowledge_node_failure` events (mirroring Phase 1's `understanding_node_failure` pattern) for monitoring; downstream nodes treat any non-null `error` exactly like an ordinary `"llm"` result — Phase 2 does not special-case failure handling beyond logging it.

---

## 9. LangGraph Integration

### 9.1 Node Purpose

`knowledge_node` is the second node in the Manasi AI LangGraph, executed immediately after `understanding_node` for every user turn whose intent is not trivially skippable. It is a required predecessor to the (future) Response Generation node.

### 9.2 Input State

| State Field | Type | Source |
|---|---|---|
| `understanding` | `Understanding` (Phase 1 schema) | Written by `understanding_node` in the same turn. |

The node does not read `user_message` or `chat_history` directly — all retrieval-relevant information is expected to already be captured in `understanding.search_query` and `understanding.intent`, per Phase 1's contract. This keeps the Knowledge Node decoupled from how understanding was derived.

### 9.3 Output State

| State Field | Type | Description |
|---|---|---|
| `knowledge` | `Knowledge` (Section 8 schema) | The structured retrieval output for the current turn. |

The node MUST NOT mutate `user_message`, `chat_history`, or `understanding`. It only adds `knowledge` to state.

### 9.4 State Updates

```python
{"knowledge": {
    "source": "rag",
    "retrieved_docs": [...],
    "confidence": 0.91,
    "query_used": "...",
    "intent": "therapy_information",
    "retrieval_skipped": False,
    "content_types_searched": ["therapy_info", "faq", "blog"],
    "retrieval_time_ms": 412.3,
    "error": None,
}}
```

LangGraph merges this into the running `GraphState` for the turn, overwriting any prior `knowledge` value — Phase 2 does not retain a history of past retrievals in state (same rationale as Phase 1's `understanding` field).

### 9.5 State Definition (`graph/state.py`, extended)

```python
from typing import Literal, Optional, TypedDict


class ChatTurn(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class Understanding(TypedDict):
    intent: Literal[
        "concept_explanation", "therapy_information", "course_information",
        "research_information", "website_information", "personal_concern",
        "emotional_support", "general_chat",
    ]
    topic: str
    search_query: str
    emotional_state: Literal[
        "neutral", "curious", "confused", "worried", "overwhelmed", "frustrated"
    ]


class RetrievedDocument(TypedDict):
    chunk_id: str
    content: str
    content_type: Literal[
        "course", "blog", "research_article", "faq", "practitioner_info",
        "therapy_info", "website_content", "neuroplasticity_content", "pdf_document",
    ]
    source_title: str
    source_url: Optional[str]
    similarity_score: float
    metadata: dict


class Knowledge(TypedDict):
    source: Literal["rag", "llm"]
    retrieved_docs: list[RetrievedDocument]
    confidence: float
    query_used: str
    intent: str
    retrieval_skipped: bool
    content_types_searched: list[str]
    retrieval_time_ms: float
    error: Optional[str]


class GraphState(TypedDict):
    user_message: str
    chat_history: list[ChatTurn]
    understanding: Optional[Understanding]
    knowledge: Optional[Knowledge]
```

### 9.6 Node Responsibilities (`nodes/knowledge_node.py`)

```python
def knowledge_node(state: GraphState, retriever=None) -> dict:
    """LangGraph node: retrieve ManaScience knowledge for the current turn's understanding.

    Pure function of state["understanding"] -> partial state update; does not mutate
    user_message, chat_history, or understanding. Returns {"knowledge": {...}}.
    """
    understanding = state["understanding"]

    if understanding["intent"] == "general_chat":
        return {"knowledge": _skipped_result(understanding)}

    retriever = retriever or build_retriever()
    start = time.monotonic()
    try:
        result = retrieve_knowledge(retriever, understanding)
    except (ChromaError, OpenAIError) as exc:
        logger.error("knowledge_node_failure: query=%r error=%s", understanding["search_query"], exc)
        result = _error_result(understanding, error=_classify_error(exc))

    result["retrieval_time_ms"] = (time.monotonic() - start) * 1000
    return {"knowledge": result}
```

### 9.7 Graph Flow

```
graph = StateGraph(GraphState)
graph.add_node("understanding_node", understanding_node)
graph.add_node("knowledge_node", knowledge_node)
graph.add_edge(START, "understanding_node")
graph.add_edge("understanding_node", "knowledge_node")
# Phase 3+ will add:
# graph.add_node("response_generation_node", response_generation_node)
# graph.add_edge("knowledge_node", "response_generation_node")
graph.add_edge("knowledge_node", END)  # Phase 2 terminates here for isolated testing
```

For Phase 2 isolated testing/deployment (analogous to Phase 1's `build_understanding_graph`), the graph terminates immediately after `knowledge_node` so the two-node pipeline can be validated end-to-end (API → Understanding → Knowledge → JSON) before Response Generation exists:

```python
def build_knowledge_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(GraphState)
    graph.add_node("understanding_node", understanding_node)
    graph.add_node("knowledge_node", knowledge_node)
    graph.add_edge(START, "understanding_node")
    graph.add_edge("understanding_node", "knowledge_node")
    graph.add_edge("knowledge_node", END)
    return graph.compile()
```

### 9.8 Integration with Future Nodes

* **Phase 3 (Response Generation / Empathy Transformation / Understand-Simplify-Explain-Humanize):** will read `state["knowledge"]["source"]` to decide whether to ground its answer in `retrieved_docs` content or answer from general knowledge, and `state["knowledge"]["confidence"]` to decide how strongly to assert ManaScience-specific claims. It will read `state["understanding"]["emotional_state"]` (unchanged from Phase 1) for tone calibration. The Knowledge Node itself performs none of that transformation — it only supplies the signal and the raw material.
* **Safety/Disclaimer logic (future phase):** may use `knowledge.source == "llm"` combined with `understanding.intent == "personal_concern"` as a trigger to add an extra disclaimer (since an ungrounded answer to a personal/clinical-adjacent question warrants more caution), but implements none of that logic here.

---

## 10. File Structure

```
app/
  rag/
    chroma_client.py      # NEW — Chroma client/collection lifecycle
    embeddings.py         # NEW — embedding model wiring
    retriever.py          # NEW — similarity search + filtering + ranking
    ingest.py              # EXISTING (Phase 0 FAISS prototype) — unchanged, unrelated
    chain.py               # EXISTING (Phase 0 FAISS prototype) — unchanged, unrelated
  nodes/
    knowledge_node.py     # NEW — LangGraph node wiring retriever output to Knowledge schema
    understanding_node.py # EXISTING (Phase 1) — unchanged
  graph/
    state.py              # EXTENDED — add RetrievedDocument, Knowledge, GraphState.knowledge
scripts/
  build_knowledge_index.py # NEW — idempotent ingestion/upsert CLI for the Chroma collection
tests/
  test_knowledge_node.py   # NEW
```

`app/rag/chroma_client.py`, `embeddings.py`, and `retriever.py` are new and intentionally separate from the existing `app/rag/ingest.py`/`chain.py`, which back the unrelated Phase 0 FAISS prototype chat endpoint (`/chat`). The two systems coexist in the same `app/rag/` package without conflict; their eventual relationship is a Future Consideration (Section 13), not a Phase 2 decision.

### 10.1 `rag/chroma_client.py`
**Responsibility:** Owns the ChromaDB client and collection lifecycle — `get_or_create_collection`, persistence path configuration, and collection metadata (`hnsw:space`). Exposes a single `get_collection()` function used by both ingestion (`scripts/build_knowledge_index.py`) and retrieval (`rag/retriever.py`), so collection configuration is defined in exactly one place.

### 10.2 `rag/embeddings.py`
**Responsibility:** Wires the `OpenAIEmbeddings` instance using `settings.knowledge_embedding_model`. Exposes `get_embeddings()`. Kept separate from `chroma_client.py` so the embedding model can be swapped or mocked independently of the vector store in tests.

### 10.3 `rag/retriever.py`
**Responsibility:** Implements the retrieval pipeline (Section 6) — builds the LangChain `Chroma` retriever wrapper, applies the intent → content-type filter (Section 6.2), executes `similarity_search_with_relevance_scores`, performs the no-filter retry, and returns ranked `(Document, score)` pairs. Exposes `retrieve(search_query: str, intent: str) -> list[tuple[Document, float]]`. Contains no source-decision or schema logic — that belongs to `nodes/knowledge_node.py`.

### 10.4 `nodes/knowledge_node.py`
**Responsibility:** Implements `knowledge_node(state, retriever=None) -> dict` (Section 9.6). Responsibilities:
* Skip-check `intent == "general_chat"` (FR-2).
* Call `rag/retriever.py` to get scored candidates.
* Apply the source decision algorithm (Section 7.3) and aggregation/capping (Section 6.4).
* Catch and classify infrastructure failures (FR-11, Section 8.6).
* Return `{"knowledge": {...}}` matching the Pydantic model mirroring `Knowledge` (Section 9.5).
* Also exposes `build_knowledge_graph()` for Phase 2 isolated testing (Section 9.7).

### 10.5 `scripts/build_knowledge_index.py`
**Responsibility:** CLI entry point that walks each content source (courses, blogs, research articles, FAQs, practitioner info, therapy info, website content, neuroplasticity content, PDFs), applies the content-type-specific chunking strategy (Section 5.3), computes `chunk_id`s, and calls `collection.upsert(...)` (Section 5.6). Safe to re-run after any content edit; only touched documents' chunks are re-embedded.

### 10.6 `app/config.py` (additions)

```python
chroma_persist_dir: Path = BASE_DIR / os.getenv("CHROMA_PERSIST_DIR", "chroma_store")
chroma_collection_name: str = os.getenv("CHROMA_COLLECTION_NAME", "manascience_knowledge")
knowledge_embedding_model: str = os.getenv("KNOWLEDGE_EMBEDDING_MODEL", "text-embedding-3-small")
knowledge_top_k: int = int(os.getenv("KNOWLEDGE_TOP_K", "8"))
knowledge_max_returned_chunks: int = int(os.getenv("KNOWLEDGE_MAX_RETURNED_CHUNKS", "4"))
knowledge_max_context_chars: int = int(os.getenv("KNOWLEDGE_MAX_CONTEXT_CHARS", "6000"))
rag_similarity_threshold: float = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.72"))
rag_min_relevant_chunks: int = int(os.getenv("RAG_MIN_RELEVANT_CHUNKS", "1"))
```

---

## 11. Examples

The `content` field is truncated to roughly the first sentence in this table for readability; the full chunk text is what would actually populate `RetrievedDocument.content` in implementation.

| # | Category | Input `search_query` (`intent`) | Retrieved Chunks (truncated) | Source Decision | Output (key fields) |
|---|---|---|---|---|---|
| 1 | Neuroplasticity | "Explain neuroplasticity in simple language" (`concept_explanation`) | `neuroplasticity_content`: "Neuroplasticity is the brain's ability to reorganize itself..." (sim 0.89) | `rag` | `{"source":"rag","confidence":0.89,"retrieved_docs":[1 chunk]}` |
| 2 | Neuroplasticity | "how the brain rewires itself neuroplasticity mechanism" (`concept_explanation`) | `blog`: "When you practice a new skill, repeated activation strengthens..." (sim 0.84); `neuroplasticity_content`: "Synaptic pruning removes unused connections..." (sim 0.79) | `rag` | `{"source":"rag","confidence":0.84,"retrieved_docs":[2 chunks]}` |
| 3 | Primitive Reflexes | "retained primitive reflexes in children" (`concept_explanation`) | `therapy_info`: "Retained primitive reflexes, such as the Moro or ATNR reflex, can affect..." (sim 0.81); `faq`: "What are primitive reflexes? — Primitive reflexes are automatic..." (sim 0.77) | `rag` | `{"source":"rag","confidence":0.81,"retrieved_docs":[2 chunks]}` |
| 4 | Primitive Reflexes | "does my child need reflex integration therapy" (`personal_concern`) | `therapy_info`: "Reflex integration therapy addresses retained reflexes through targeted movement..." (sim 0.78) | `rag` | `{"source":"rag","confidence":0.78,"retrieved_docs":[1 chunk]}` |
| 5 | Therapy Information | "ManaScience therapies offered" (`therapy_information`) | `therapy_info`: "ManaScience offers occupational therapy, speech therapy, and sensory integration..." (sim 0.93) | `rag` | `{"source":"rag","confidence":0.93,"retrieved_docs":[1 chunk]}` |
| 6 | Therapy Information | "occupational therapy effectiveness sensory issues" (`therapy_information`) | `therapy_info`: "ManaScience's occupational therapy program focuses on sensory integration..." (sim 0.91) | `rag` | `{"source":"rag","confidence":0.91,"retrieved_docs":[1 chunk]}` |
| 7 | Courses | "ManaScience courses neuroplasticity" (`course_information`) | `course`: "Foundations of Neuroplasticity is a 6-week self-paced course covering..." (sim 0.88) | `rag` | `{"source":"rag","confidence":0.88,"retrieved_docs":[1 chunk]}` |
| 8 | Courses | "ManaScience certification program caregivers" (`course_information`) | `course`: "The Caregiver Certification Track prepares family members to support..." (sim 0.85) | `rag` | `{"source":"rag","confidence":0.85,"retrieved_docs":[1 chunk]}` |
| 9 | Research Articles | "research evidence neuroplasticity-based therapy effectiveness" (`research_information`) | `research_article`: "A 2021 randomized study found neuroplasticity-based intervention improved..." (sim 0.86); `pdf_document`: "Methods: 64 participants were assigned to..." (sim 0.74) | `rag` | `{"source":"rag","confidence":0.86,"retrieved_docs":[2 chunks]}` |
| 10 | Research Articles | "long-term outcomes of early intervention studies" (`research_information`) | `research_article`: "Longitudinal data suggests early intervention is associated with..." (sim 0.80) | `rag` | `{"source":"rag","confidence":0.80,"retrieved_docs":[1 chunk]}` |
| 11 | Website Information | "how to create a ManaScience account" (`website_information`) | `website_content`: "To create an account, click Sign Up and verify your email..." (sim 0.90) | `rag` | `{"source":"rag","confidence":0.90,"retrieved_docs":[1 chunk]}` |
| 12 | Website Information | "ManaScience blog posts location" (`website_information`) | `website_content`: "Our blog is available under the Resources tab..." (sim 0.83); `faq`: "Where can I find your blog? — You can find all blog posts under..." (sim 0.88) | `rag` | `{"source":"rag","confidence":0.88,"retrieved_docs":[2 chunks]}` |
| 13 | Practitioner Information | "ManaScience practitioners specializing in sensory processing" (`therapy_information`) | `practitioner_info`: "Dr. Asha Rao specializes in pediatric sensory integration with 12 years..." (sim 0.82) | `rag` | `{"source":"rag","confidence":0.82,"retrieved_docs":[1 chunk]}` |
| 14 | FAQ | "what age does ManaScience accept clients" (`website_information`) | `faq`: "What ages do you serve? — ManaScience works with children from age 2 through..." (sim 0.92) | `rag` | `{"source":"rag","confidence":0.92,"retrieved_docs":[1 chunk]}` |
| 15 | Personal Concern | "attention difficulties child development" (`personal_concern`) | `therapy_info`: "Attention difficulties in children can stem from several developmental factors..." (sim 0.79); `neuroplasticity_content`: "Executive function development continues through adolescence..." (sim 0.73) | `rag` | `{"source":"rag","confidence":0.79,"retrieved_docs":[2 chunks]}` |
| 16 | Emotional Support | "support for overwhelmed caregivers of children with developmental challenges" (`emotional_support`) | `faq`: weak match only (sim 0.61, below 0.72 threshold) | `llm` | `{"source":"llm","confidence":0.0,"retrieved_docs":[]}` |
| 17 | Unknown Topic | "history of left-handedness in famous artists" (`concept_explanation`) | No chunks above threshold across `neuroplasticity_content`, `blog`, `research_article`, or full-collection retry | `llm` | `{"source":"llm","confidence":0.0,"retrieved_docs":[]}` |
| 18 | Unknown Topic | "best laptop for video editing" (`concept_explanation`) | No relevant chunks found (off-domain query) | `llm` | `{"source":"llm","confidence":0.0,"retrieved_docs":[]}` |
| 19 | General Chat | `search_query = ""` (`general_chat`) | Retrieval skipped entirely (FR-2) | `llm` | `{"source":"llm","confidence":0.0,"retrieved_docs":[],"retrieval_skipped":true}` |
| 20 | Filter Retry | "ManaScience research on reflex integration" (`research_information`) | First pass (`research_article`, `pdf_document`) returns 0 chunks above threshold → retry without filter finds `therapy_info`: "Our reflex integration approach is informed by clinical observation..." (sim 0.75) | `rag` | `{"source":"rag","confidence":0.75,"content_types_searched":["therapy_info"]}` |

---

## 12. Acceptance Criteria

### 12.1 Test Case Categories

| Test Category | Description | Pass Criteria |
|---|---|---|
| Schema validity | Run node against all 20 examples in Section 11 | 100% of outputs are valid JSON matching Section 8, with required-field consistency rules (8.5) holding. |
| Source-decision accuracy | Run node against a labeled test set (≥50 queries spanning all content types and ≥10 genuinely out-of-domain queries) | ≥90% agreement with human-labeled "should this be rag or llm" judgment. |
| Retrieval relevance (precision@k) | For queries labeled `rag`, manually review top-returned chunk relevance | ≥85% of top-1 returned chunks judged relevant by a human reviewer. |
| Threshold calibration | Sweep `RAG_SIMILARITY_THRESHOLD` across a held-out labeled set | Document the precision/recall tradeoff at the chosen default (`0.72`) so it is a measured choice, not an assumed one, before Phase 2 ships to production. |
| No-document-dumping guarantee | Inspect all outputs across the test set | 0% of outputs contain rewritten/summarized/humanized chunk content; `content` fields match source documents verbatim. |
| Skip-logic correctness | Run node against `general_chat` and several `emotional_support` queries | `general_chat` always sets `retrieval_skipped=true` with zero search calls (verify via call-count instrumentation); `emotional_support` only retrieves when a genuine threshold-clearing match exists. |
| Metadata correctness | Spot-check `retrieved_docs[].metadata` against source content | Content-type-specific fields populate correctly per Section 5.2; no cross-type field leakage (e.g., no `practitioner_name` on a `blog` chunk). |
| Idempotent ingestion | Run `build_knowledge_index.py` twice without content changes | Collection chunk count and content are identical after the second run (no duplication). |
| Error handling | Simulate Chroma connection failure and OpenAI embeddings API failure independently | Node returns the `"llm"` fallback shape with the correct `error` code in both cases, without raising. |
| Latency | Run node against 20 representative queries | p95 latency under 800ms per Section 4.2. |

### 12.2 Definition of Done

Phase 2 (Knowledge Node) is considered complete only when **all** of the following hold:

1. Source-decision accuracy ≥90% on the labeled test set (Section 12.1).
2. Top-1 retrieval relevance ≥85% on `rag`-labeled queries.
3. JSON output is 100% schema-valid across the full test set, including the error-handling path exercised at least once.
4. Zero instances of summarized, rewritten, or "humanized" content appearing in `retrieved_docs[].content` across the full test set — chunks are verbatim source material.
5. `general_chat` retrieval-skip and `emotional_support` light-retrieval behaviors are verified exactly as specified (Section 6.4, FR-2).
6. The node is integrated into a LangGraph `StateGraph` per Section 9 and runnable end-to-end (API → Understanding → Knowledge → JSON) in isolation, without a Phase 3 generation node existing yet.
7. `scripts/build_knowledge_index.py` successfully ingests at least one real document from each of the nine content types into the Chroma collection, with correct metadata.

---

## 13. Future Considerations

The following are explicitly **out of scope for Phase 2** but noted here so the engineer understands what the Knowledge Node's output contract must remain stable for:

* **Phase 3 — Response Generation, Empathy Transformation, Understand/Simplify/Explain/Humanize:** will consume `knowledge.source`, `knowledge.confidence`, and `knowledge.retrieved_docs` to ground or generate the final user-facing answer, and `understanding.emotional_state` to calibrate tone. The Knowledge Node itself performs none of that work.
* **Hybrid search:** combining vector similarity with keyword/BM25 search (e.g., via Chroma's metadata filtering plus a separate keyword index) may improve recall for exact-name queries (specific therapy or practitioner names) where embeddings alone underperform.
* **Reranking:** a cross-encoder or hosted reranking model (e.g., Cohere Rerank) could improve top-1 precision beyond pure cosine similarity, at the cost of an extra API call and latency — worth revisiting if Acceptance Criteria precision targets are not met by similarity search alone.
* **Learned/calibrated confidence:** once enough labeled retrieval outcomes exist, `confidence` could become a calibrated probability (e.g., via isotonic regression over historical similarity-vs-relevance labels) rather than raw cosine similarity.
* **Per-content-type collection sharding:** if any single content type grows large enough to dominate retrieval latency or pollute cross-type ranking, splitting that type into its own Chroma collection is a natural next step; the metadata-filter design in Section 5.1 already anticipates this without requiring a schema change.
* **Caching:** identical `search_query` strings within a session (or across sessions, for highly common questions) could be cached to skip redundant embedding + search calls.
* **Multi-language embeddings:** Phase 2 assumes English content and English queries, consistent with Phase 1's English-only assumption.
* **Feedback loop:** if Phase 3+ or user feedback signals indicate a `rag`-sourced answer was unhelpful or a `llm`-sourced answer should have been grounded, that signal could feed back into threshold tuning or flag content gaps in the ManaScience knowledge base for the content team.
* **Relationship to the Phase 0 FAISS prototype:** `app/rag/chain.py` and `app/rag/ingest.py` implement a separate, simpler monolithic retrieval+generation chain that predates the phased LangGraph architecture and currently backs the `/chat` endpoint. Whether and when to retire that prototype in favor of the full Understanding → Knowledge → Response Generation pipeline is a product/migration decision for a later phase, not a Phase 2 requirement — Phase 2 introduces ChromaDB-backed retrieval as net-new, additive infrastructure alongside it.
* **Scheduled re-ingestion:** running `build_knowledge_index.py` on a schedule (or triggered by ManaScience CMS webhooks) so new courses/blogs/research are searchable without a manual step is a natural operational follow-up once content update frequency justifies it.

---

*End of Phase 2 Specification — Knowledge Node.*
