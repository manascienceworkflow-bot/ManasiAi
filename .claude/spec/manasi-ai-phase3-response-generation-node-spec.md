# Manasi AI — Phase 3 Technical Specification
## Response Generation Node

**Project:** Manasi AI
**Organization:** ManaScience
**Phase:** 3 of N — Response Generation Node
**Status:** Draft for implementation
**Audience:** Python + FastAPI + LangGraph engineer
**Depends on:** Phase 1 — Understanding Node (`manasi-ai-phase1-understanding-node-spec.md`), Phase 2 — Knowledge Node (`manasi-ai-phase2-knowledge-node-spec.md`)

---

## 1. Executive Summary

Phase 1 (the Understanding Node) converts a raw user message into a structured object — `intent`, `topic`, `search_query`, `emotional_state`. Phase 2 (the Knowledge Node) takes that structure and returns a grounding decision — `source`, `retrieved_docs`, `confidence` — either ManaScience reference material from ChromaDB or a clean signal to fall back to general knowledge. Neither phase produces a single word of user-facing text.

This document specifies **Phase 3 only: the Response Generation Node**, the third node in the Manasi AI LangGraph pipeline. Its job is narrow and specific: take the structured outputs of Phases 1 and 2 and produce one accurate, simplified, freshly-written answer to the user's question. It is the first node in the pipeline that is allowed to write prose intended for the user — and even then, only the *informational* content of the response. Tone, warmth, empathy, personality, and safety disclaimers are explicitly out of scope; those belong to later phases (a future Humanize/Empathy node and a future Disclaimer/Safety node) that will sit downstream of this one and transform the answer this node produces, not generate it from scratch.

The Response Generation Node treats retrieved ManaScience content the same way a good teacher treats a textbook: as material to understand and explain, never to recite. Its single most important behavioral guarantee is that **no retrieved chunk is ever returned to the user verbatim or near-verbatim** — every answer is rewritten in the node's own words, simplified, and structured for understanding. Its second most important guarantee is **universal coverage**: every reasonable question gets a substantive answer, whether or not ManaScience has relevant content for it, because the node falls back to general LLM knowledge rather than refusing.

---

## 2. Business Objective

Manasi's usefulness depends on users getting real answers, not citations. A user who asks "what is neuroplasticity?" does not want a paragraph lifted from a blog post — they want to understand the concept. A user who asks "what is Python?" — a question with zero ManaScience-specific content behind it — should still get a clear, accurate answer rather than a dead end. The Response Generation Node exists to guarantee both of these outcomes mechanically, rather than leaving "should I rewrite this" or "should I answer this at all" to inconsistent prompt-level judgment buried inside a larger, harder-to-audit generation step.

Specifically, this node exists to:

* **Protect ManaScience's content from being repackaged as a copy-paste delivery mechanism.** Retrieved chunks are ManaScience's intellectual material; presenting them unedited is not a feature, it is a missed opportunity to actually help the user understand them — and it is also a content-licensing and brand-voice liability if a chunk's original wording does not match the personality ManaScience wants Manasi to have.
* **Guarantee Manasi never appears unhelpful.** A chatbot that says "I don't know" or "no information found" the first time a user asks something ManaScience hasn't written about teaches the user to stop asking. Phase 3's Universal Knowledge Requirement makes that failure mode structurally impossible: every node invocation produces a substantive answer.
* **Separate "what to say" from "how to say it."** By producing a plain, accurate, simplified answer with no tone engineering, this node hands later phases (empathy transformation, disclaimers) a clean substrate to adjust — they can add warmth to a correct answer, but they should never have to fix a wrong, copied, or evasive one.
* **Keep the decision of *whether* an answer is ManaScience-grounded auditable.** By passing `source` and `confidence` through unchanged from Phase 2 rather than re-deriving them, engineers can always trace a generated answer back to the exact retrieval decision that produced it.

---

## 3. Functional Requirements

### FR-1: Structured Dual-Input Consumption
The node SHALL accept the Phase 1 `Understanding` object (`intent`, `topic`, `search_query`) and the Phase 2 `Knowledge` object (`source`, `retrieved_docs`, `confidence`) as its only required inputs. The node SHALL NOT perform any vector search, embedding call, or re-retrieval of its own — retrieval is exclusively Phase 2's responsibility.

### FR-2: No Empathy, Personality, Disclaimer, or Safety Logic
The node SHALL NOT consume `understanding.emotional_state` for tone calibration, SHALL NOT inject reassurance, warmth, or conversational personality, and SHALL NOT add clinical, legal, or safety disclaimers. These responsibilities belong to future phases that sit downstream of this node (Section 14).

### FR-3: Knowledge-Source Branching
The node SHALL select its generation instructions based on `knowledge.source` (Section 6): when `source == "rag"`, retrieved content is the primary reference material; when `source == "llm"`, the node answers from general knowledge with no reference to ManaScience material being absent.

### FR-4: Universal Answer Requirement
The node SHALL generate a substantive, accurate answer for every input, including topics entirely absent from ManaScience's knowledge base (e.g., "What is Python?", "What is the Solar System?"). The node SHALL NOT emit any response consisting of or dominated by a refusal phrase from the banned list (Section 6.3) under normal operation.

### FR-5: Document-Dump Prohibition
The node SHALL NOT return an answer containing a verbatim or near-verbatim excerpt of any `retrieved_docs[].content` at or above the configured overlap threshold (Section 6.4). Retrieved content MUST be rewritten in fresh language.

### FR-6: Simplification
The node SHALL translate academic, technical, and research language present in retrieved content into plain, conversational, everyday language, per the transformation rules in Section 7.

### FR-7: Structured Explanation for Concept Questions
When `understanding.intent == "concept_explanation"`, the generated answer SHALL contain, woven into natural prose, a definition, a simple explanation, a statement of why the concept matters, and a concrete example where one would genuinely aid understanding.

### FR-8: Direct-Answer Mode for Non-Concept Intents
For intents other than `concept_explanation`, the node SHOULD favor a direct, proportionate answer over imposing the full four-part structure, so that simple factual questions (e.g., "what age does ManaScience accept clients") are not padded into an unnecessary essay.

### FR-9: Deterministic Metadata Assignment
`source`, `answer_type`, `confidence`, and `grounded_chunk_ids` in the output SHALL be computed deterministically by the node's own Python logic from the input state — never self-reported by the generation LLM. Only the `answer` field's content is produced by the LLM.

### FR-10: Structured Output Only
The node SHALL emit a single JSON-serializable object conforming to Section 8. The `answer` field MAY contain light, user-facing markdown (paragraphs, bullet points) but the overall node output SHALL NOT be wrapped in commentary, code fences, or any surrounding prose.

### FR-11: Retry on Quality-Guard Failure
If the generated answer fails the banned-phrase check, the document-dump check, or schema validation, the node SHALL retry generation exactly once with a corrective reprompt before falling back (Section 8.7).

### FR-12: Never-Block Fallback
If both generation attempts fail a quality guard, or the LLM call itself fails at the infrastructure level, the node SHALL still return a non-empty, non-refusing `answer` and SHALL NOT raise an unhandled exception under any input (Section 8.7).

### FR-13: Source and Confidence Passthrough Integrity
The output `source` and `confidence` fields SHALL exactly equal `knowledge.source` and `knowledge.confidence` from the input. The node SHALL NOT independently re-derive, override, or "upgrade" these values based on how the generation turned out.

### FR-14: Statelessness
The node SHALL be a pure function of (`understanding`, `knowledge`, and optionally `user_message` for phrasing nuance) → JSON. It SHALL NOT mutate any input state object or persist conversation state across invocations.

---

## 4. Non-Functional Requirements

### 4.1 General NFRs

| Category | Requirement |
|---|---|
| **Latency** | The node SHOULD complete in under 3,500ms p95 (one generation call, plus a possible one corrective retry), since it is the first LLM-generation node — heavier than Phase 1's classification call or Phase 2's pure vector search. |
| **Reliability** | The node MUST always return a valid, schema-conforming, non-refusing output (Section 8), even on LLM infrastructure failure or repeated quality-guard failure (FR-12). It MUST NOT raise an unhandled exception under any input. |
| **Statelessness** | Per FR-14. The node SHALL NOT call the retriever, the embeddings model, or any other phase's logic directly. |
| **Testability** | The node MUST be unit-testable in isolation using a fake/mock LLM that returns scripted JSON, independent of Phases 1 and 2 and without live OpenAI calls. |
| **Observability** | Every invocation SHOULD be logged with `intent`, `source`, `answer_type`, retry count, which quality guard (if any) triggered a retry, and latency, to support prompt and threshold tuning over time. |
| **Cost** | The node SHOULD use the smallest chat model that meets quality targets (`gpt-4o-mini` by default, matching Phase 1's `understanding_model` default) and SHALL bound retries to at most one extra call per turn, keeping worst-case cost at 2x a single generation call. |
| **Consistency** | Because generation runs at non-zero temperature (Section 5), identical inputs are NOT expected to produce byte-identical answers across calls — but they SHOULD be consistent in factual content, structure, and quality, since both retrieved content and the prompt's instructions are deterministic. |
| **Safety boundary** | The node MUST NOT fabricate ManaScience-specific claims (specific outcomes, statistics, or program details) beyond what is supported by `retrieved_docs` when `source == "rag"`. It performs no diagnostic or prescriptive language filtering itself — that is the future Disclaimer node's job (Section 14) — but it also MUST NOT invent false certainty where retrieved content is qualified or tentative. |

### 4.2 Performance Targets

| Metric | Target | Notes |
|---|---|---|
| Generation call latency (first attempt) | p95 < 2,500ms | Single chat completion call; larger expected output than Phase 1's short classification JSON. |
| End-to-end node latency | p95 < 3,500ms | First attempt + possible one corrective retry + guard checks (guard checks are local string operations, not LLM calls, and add negligible latency). |
| Max generation attempts | 2 (`RESPONSE_MAX_RETRIES = 1`) | One initial attempt, one corrective retry; never more (FR-11, FR-12). |
| Max context chunks read | 4 (inherited from `KNOWLEDGE_MAX_RETURNED_CHUNKS`) | The node does not raise this cap — it reads exactly what Phase 2 already bounded. |
| Max context size read | 6,000 characters (inherited from `KNOWLEDGE_MAX_CONTEXT_CHARS`) | Same rationale as Phase 2 — keeps prompt size predictable regardless of source verbosity. |
| Min answer length | 40 characters (`RESPONSE_MIN_ANSWER_LENGTH`) | A floor against degenerate near-empty answers; tunable per deployment. |
| Cost per turn | 1–2 chat completion calls | No embedding cost (Phase 2 already embedded the query); cost scales with retry rate, which should trend toward zero as the prompt is tuned. |

---

## 5. Response Generation Architecture

### 5.1 Pipeline Steps

```
Understanding (intent, topic, search_query) + Knowledge (source, retrieved_docs, confidence)
        │
        ▼
1. Select knowledge-utilization instruction block from knowledge.source (Section 6.1/6.2)
        │
        ▼
2. Format retrieved_context block from knowledge.retrieved_docs, or an explicit
   "no ManaScience content" marker when source == "llm" (Section 6.1)
        │
        ▼
3. Select structure instruction block from understanding.intent — full four-part
   structure for concept_explanation, direct-answer mode otherwise (Section 7.2)
        │
        ▼
4. Build prompt from response_prompt.txt template + substituted placeholders (Section 9)
        │
        ▼
5. Invoke generation LLM (temperature = RESPONSE_TEMPERATURE, non-zero — Section 5.2)
        │
        ▼
6. Parse {"answer": "..."} JSON (strip code fences, json.loads)
        │
        ▼
7. Pydantic schema validation: non-empty, min length, banned-phrase scan (Section 6.3)
        │
   fail │ pass
        │   └─────────────► 8. Document-dump check against retrieved_docs (Section 6.4)
        ▼                          │
   ┌─────────────────────────┐ fail │ pass
   │ Corrective reprompt retry│◄────┘
   │ (max 1 retry — FR-11)    │
   └───────────┬──────────────┘
               │
               ▼ (retry attempt also fails a guard, or LLM call itself errors)
9. Best-effort fallback selection — never raises, never refuses (Section 8.7)
        │
        ▼
10. Assemble deterministic fields: source/confidence passthrough, answer_type from
    intent (Section 6.5), grounded_chunk_ids, generation_time_ms
        │
        ▼
Structured ResponseOutput (Section 8)
```

### 5.2 Generation Model Configuration

Unlike Phase 1's classification call (`temperature=0`, deterministic), Phase 3's generation call uses a small non-zero temperature, because rewriting retrieved content into fresh language and simplifying technical explanations are inherently generative tasks where a small amount of lexical variation is desirable and a temperature of exactly 0 tends to produce stilted, overly literal paraphrases that drift back toward the source wording.

```python
def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(model=settings.response_model, temperature=settings.response_temperature)
```

Default `RESPONSE_TEMPERATURE = 0.3` — low enough to keep factual content stable across calls, high enough to avoid mechanical near-copies of retrieved text.

### 5.3 Why Metadata Is Computed, Not Generated

Phases 1 and 2 already establish the pattern of having the LLM do only the work it is uniquely suited for, while Python computes everything that can be computed deterministically and auditably (Phase 2 Section 7.4 makes the same call for `confidence`). Phase 3 follows the same principle: the generation LLM is asked to produce exactly one thing — the `answer` text — inside a minimal `{"answer": "..."}` JSON envelope. `source`, `answer_type`, `confidence`, and `grounded_chunk_ids` are all assigned by the node's own code from inputs it already has. This removes an entire class of failure mode (the LLM mislabeling its own answer's source or type) without giving up anything: the LLM was never the right component to make that decision, since it has no privileged knowledge that Phase 2's retrieval decision didn't already establish.

---

## 6. Knowledge Utilization Logic

### 6.1 The Two Branches

**When `knowledge.source == "rag"`:**

* `retrieved_docs` (already deduplicated, ranked, and capped by Phase 2) is the primary reference material.
* The node SHALL read and understand each chunk, then explain the concepts in its own words.
* The node MAY expand on retrieved content with general background knowledge to make it clearer, as long as it does not contradict what ManaScience's material actually says.
* The node SHALL stay faithful to retrieved content — it SHALL NOT invent ManaScience-specific claims, statistics, program details, or outcomes that are not supported by `retrieved_docs`.

**When `knowledge.source == "llm"`:**

* `retrieved_docs` is always `[]` (guaranteed by Phase 2's contract — Section 8.4 of the Phase 2 spec).
* The node SHALL answer using general knowledge, exactly as a knowledgeable, accurate general-purpose assistant would.
* The node SHALL NOT mention, hedge on, or apologize for the absence of ManaScience-specific material. The user never sees evidence of which branch produced their answer — that is an internal routing signal, not a disclosure (a future Disclaimer node may choose to surface it; Phase 3 does not).

Both branches are pre-selected deterministically by the node from `knowledge.source` before the LLM is ever called (Section 9) — the LLM is never asked to judge which branch applies, since Phase 2 has already made and validated that decision.

### 6.2 Retrieved-Context Formatting

```python
def _format_retrieved_context(retrieved_docs: list[dict]) -> str:
    if not retrieved_docs:
        return "(No ManaScience content was retrieved for this question. Answer using general knowledge.)"
    blocks = [
        f"[{i}] ({doc['content_type']} — {doc['source_title']})\n{doc['content']}"
        for i, doc in enumerate(retrieved_docs, start=1)
    ]
    return "\n\n".join(blocks)
```

This formatted block becomes the prompt's `{{retrieved_context}}` placeholder (Section 9). Numbering and labeling each chunk by `content_type` and `source_title` lets the model (and a human reviewing logs) see exactly what reference material was available, without that structure leaking into the user-facing `answer`.

### 6.3 Universal Knowledge Requirement and the Banned-Phrase Guard

Manasi must attempt to answer all reasonable questions, whether or not ManaScience has written about them — `concept_explanation` is the intent Phase 1 assigns to exactly this kind of question (e.g., "What is Artificial Intelligence?", "What is Python?", "What is the Solar System?"), and Phase 2's `source = "llm"` fallback is the expected, correct outcome for most of them. Phase 3's job is to make sure that fallback always produces a real answer.

The following phrases (case-insensitive substring match) are prohibited from appearing as the dominant content of a generated answer, and trigger the retry path in Section 5.1 step 7 if detected:

```python
BANNED_PHRASES = [
    "i don't know", "i do not know", "i'm not sure", "i am not sure",
    "no information found", "no information available", "information unavailable",
    "i'm unable to answer", "i am unable to answer", "unable to answer this",
    "i cannot answer", "i can't answer", "i don't have information",
    "i don't have enough information", "not available in my knowledge base",
    "i have no information",
]
```

This check enforces FR-4. It is intentionally a simple substring scan rather than an LLM-judged "did this refuse" classifier, for the same reason Phase 2 keeps `confidence` as raw cosine similarity rather than an LLM-graded score (Phase 2 Section 7.4): determinism, speed, and auditability beat marginal precision gains from an extra model call.

### 6.4 Document-Dump Detection

FR-5's prohibition is operationalized as a shingled-overlap check rather than a full longest-common-substring computation, which is unnecessary work for chunk sizes in the hundreds of words:

```python
SHINGLE_SIZE_WORDS = 12

def _shingles(text: str) -> set[str]:
    words = text.lower().split()
    return {
        " ".join(words[i : i + SHINGLE_SIZE_WORDS])
        for i in range(len(words) - SHINGLE_SIZE_WORDS + 1)
    }

def _is_document_dump(answer: str, retrieved_docs: list[dict]) -> bool:
    if not retrieved_docs:
        return False
    answer_shingles = _shingles(answer)
    for doc in retrieved_docs:
        if _shingles(doc["content"]) & answer_shingles:
            return True
    return False
```

A shared 12-word shingle between the generated answer and any retrieved chunk is treated as conclusive evidence of copying — natural paraphrase essentially never reproduces a specific 12-word run verbatim by chance. `SHINGLE_SIZE_WORDS` is tunable (`RESPONSE_DOCUMENT_DUMP_SHINGLE_WORDS`) if the default proves too strict or too lenient once measured against real generations (Section 13).

This check only runs when `source == "rag"` and `retrieved_docs` is non-empty — there is nothing to dump when the answer came from general knowledge.

### 6.5 Deriving `answer_type` from `intent`

`answer_type` is a separate axis from `source`: `source` tracks *where the information came from*, `answer_type` tracks *what shape of answer was produced*. The mapping is a pure function of `understanding.intent`, applied identically regardless of `source`:

| `understanding.intent` | `answer_type` |
|---|---|
| `concept_explanation` | `concept_explanation` |
| `therapy_information` | `therapy_information` |
| `course_information` | `course_information` |
| `research_information` | `research_summary` |
| `website_information` | `website_information` |
| `personal_concern` | `personal_guidance` |
| `emotional_support` | `supportive_information` |
| `general_chat` | `general_knowledge` |

```python
ANSWER_TYPE_BY_INTENT = {
    "concept_explanation": "concept_explanation",
    "therapy_information": "therapy_information",
    "course_information": "course_information",
    "research_information": "research_summary",
    "website_information": "website_information",
    "personal_concern": "personal_guidance",
    "emotional_support": "supportive_information",
    "general_chat": "general_knowledge",
}
```

This reproduces both illustrative examples from the product brief — a ManaScience-grounded concept question naturally has `intent == "concept_explanation"` and therefore `answer_type == "concept_explanation"` regardless of whether `source` is `"rag"` or `"llm"` (an AI/Python/ML question has the same intent and the same `answer_type`, just with `source == "llm"`); a `general_chat` turn always yields `answer_type == "general_knowledge"`. `source` and `answer_type` are intentionally allowed to vary independently — Section 8 examples show both `{"source": "rag", "answer_type": "concept_explanation"}` and `{"source": "llm", "answer_type": "concept_explanation"}` as both being valid, common outcomes.

---

## 7. Simplification Strategy

### 7.1 Language Transformation Rules

Retrieved ManaScience content (blogs, research articles, therapy and course descriptions) is written for a mixed audience that includes clinicians and researchers. General LLM knowledge invoked for off-domain questions can default to the same register. The node SHALL transform both into the following target register before they reach the user:

| From | To | Example |
|---|---|---|
| Academic Language | Human Language | "neural plasticity mechanisms" → "how the brain changes and adapts" |
| Technical Language | Everyday Language | "sensory integration dysfunction" → "trouble processing what you see, hear, or feel" |
| Research Language | Conversational Explanation | "a 2021 randomized controlled trial demonstrated statistically significant improvement" → "a 2021 study found that kids who did this therapy improved noticeably more than kids who didn't" |
| Complex Definitions | Easy-to-Understand Explanations | "primitive reflexes are involuntary, stereotyped motor responses elicited by specific stimuli, present in infancy" → "primitive reflexes are automatic movements babies are born with, like instinctively gripping a finger placed in their palm" |

This is a register transformation, not a content reduction — simplifying language must not drop facts, caveats, or nuance that change what the answer actually communicates. A simplified answer that is shorter but wrong, or shorter but missing a load-bearing qualifier ("most children," "in some cases"), has failed FR-6, not satisfied it.

### 7.2 When the Four-Part Concept Structure Applies

Per FR-7/FR-8, structure is intent-driven, not a one-size-fits-all template:

| `understanding.intent` | Structure Used |
|---|---|
| `concept_explanation` | **Full four-part structure** (Definition → Simple Explanation → Why It Matters → Example), woven into natural prose, no literal section headers. |
| `therapy_information`, `research_information` | **Lightweight structure**: lead with a direct answer; add a one-sentence "why it matters" or example only if it materially helps (e.g., explaining an unfamiliar therapy name) — never force all four elements onto a question that didn't ask for them. |
| `course_information`, `website_information`, `personal_concern`, `emotional_support`, `general_chat` | **Direct-answer mode**: answer what was asked, proportionate to the question's scope. A factual lookup ("what age does ManaScience accept clients") gets a factual answer, not an essay. |

The Example element of the four-part structure is conditional even within `concept_explanation`: it SHALL be included "when appropriate" (per the brief) — i.e., when a concrete example would genuinely clarify an abstract concept (most cases) — and MAY be omitted for concepts that are already concrete enough that an example would be redundant filler.

### 7.3 Response Quality Requirements

Every generated answer, regardless of branch or structure, MUST satisfy all five of the following, in priority order when they trade off against each other:

1. **Accurate** — faithful to `retrieved_docs` when `source == "rag"`; factually correct general knowledge when `source == "llm"`. Accuracy is never sacrificed for simplicity.
2. **Clear** — a reader with no background in the topic can follow it on first read.
3. **Simple** — plain language per Section 7.1; no unnecessary jargon, no unexplained acronyms.
4. **Helpful** — answers what the user actually asked, not a tangential restatement of the question.
5. **Structured** — organized per Section 7.2, not a wall of undifferentiated text.

The node optimizes for understanding over technical completeness: it is acceptable, and often correct, to omit a minor technical caveat present in a research-article chunk if including it would confuse more than it would inform — as long as omitting it does not make the answer misleading. This is a judgment call left to the generation prompt (Section 9), not something Python can validate mechanically; Section 13's acceptance criteria rely on human review for this dimension specifically.

---

## 8. JSON Schema

### 8.1 Input Contract (recap from Phases 1 and 2)

The Response Generation Node consumes the Phase 1 `Understanding` object and the Phase 2 `Knowledge` object together:

```json
{
  "understanding": {
    "intent": "concept_explanation",
    "topic": "neuroplasticity",
    "search_query": "what is neuroplasticity simple explanation",
    "emotional_state": "curious"
  },
  "knowledge": {
    "source": "rag",
    "retrieved_docs": [
      {
        "chunk_id": "a1b2c3d4e5f6",
        "content": "Neuroplasticity refers to the brain's ability to reorganize itself by forming new neural connections throughout life...",
        "content_type": "neuroplasticity_content",
        "source_title": "Understanding Neuroplasticity",
        "source_url": "https://manascience.com/learn/neuroplasticity",
        "similarity_score": 0.89,
        "metadata": {"concept_tags": "brain development, plasticity"}
      }
    ],
    "confidence": 0.89,
    "query_used": "what is neuroplasticity simple explanation",
    "intent": "concept_explanation",
    "retrieval_skipped": false,
    "content_types_searched": ["neuroplasticity_content", "blog", "research_article"],
    "retrieval_time_ms": 312.4,
    "error": null
  }
}
```

`understanding.emotional_state` is present in the input (it is part of the Phase 1 contract) but, per FR-2, is never read by this node — it passes through state untouched for a future phase to consume.

### 8.2 Output Schema Definition

RAG-grounded example:

```json
{
  "answer": "Neuroplasticity is your brain's ability to reorganize itself by forming new connections between neurons, throughout your whole life — not just in childhood. Think of your brain less like a fixed circuit board and more like a path through a field: the more a particular path gets used, the clearer and stronger it becomes, while paths that go unused gradually fade. This matters because it means skills, habits, and even recovery from injury aren't fixed by what your brain was 'born with' — they can change with the right kind of practice. For example, when someone practices a new movement repeatedly during therapy, the brain strengthens the specific connections involved in that movement, which is part of why repetition-based therapies work over time.",
  "source": "rag",
  "answer_type": "concept_explanation",
  "topic": "neuroplasticity",
  "intent": "concept_explanation",
  "confidence": 0.89,
  "grounded_chunk_ids": ["a1b2c3d4e5f6"],
  "generation_time_ms": 1842.6,
  "error": null
}
```

LLM-fallback example:

```json
{
  "answer": "Python is a programming language known for being easy to read and write, which is why it's often recommended for beginners. Instead of needing a lot of complicated punctuation and rules, Python code looks close to plain English, so you can focus on the logic of what you're building rather than fighting the syntax. It's used for everything from building websites and analyzing data to automating repetitive tasks and powering AI systems. For example, a few lines of Python can read a spreadsheet, calculate totals, and print a summary — work that would take much more code in many other languages.",
  "source": "llm",
  "answer_type": "concept_explanation",
  "topic": "python programming language",
  "intent": "concept_explanation",
  "confidence": 0.0,
  "grounded_chunk_ids": [],
  "generation_time_ms": 1567.2,
  "error": null
}
```

The minimal `{"answer", "source", "answer_type"}` shape from the product brief is the **required core subset** of this schema; the remaining fields (`topic`, `intent`, `confidence`, `grounded_chunk_ids`, `generation_time_ms`, `error`) are required production fields, following the same pattern Phase 2 established for its own schema (Phase 2 Section 8.2).

### 8.3 Top-Level Field Definitions

| Field | Type | Required | Allowed Values | Notes |
|---|---|---|---|---|
| `answer` | string | Yes | — | The final, rewritten, simplified, user-facing answer. Never a verbatim chunk excerpt (FR-5). MUST be at least `RESPONSE_MIN_ANSWER_LENGTH` characters after stripping whitespace. |
| `source` | string (enum) | Yes | `"rag"`, `"llm"` | MUST exactly equal `knowledge.source` (FR-13). |
| `answer_type` | string (enum) | Yes | One of the 8 values in Section 6.5 | Deterministically derived from `understanding.intent` (FR-9); never produced by the LLM. |
| `topic` | string | Yes | — | Passed through unchanged from `understanding.topic`. |
| `intent` | string | Yes | Same enum as Phase 1's `intent` | Passed through unchanged from `understanding.intent`, for downstream convenience (mirrors how Phase 2 passes through `intent`). |
| `confidence` | float | Yes | `0.0`–`1.0` | MUST exactly equal `knowledge.confidence` (FR-13). |
| `grounded_chunk_ids` | array of string | Yes | — | The `chunk_id`s of every chunk in `knowledge.retrieved_docs` (i.e., all of them — the node does not partially ground). MUST be `[]` when `source == "llm"`. |
| `generation_time_ms` | float | Yes | — | Wall-clock time for this node's work (prompt build + LLM call(s) + guard checks), for latency monitoring (Section 4.2). |
| `error` | string \| null | Yes | — | `null` on a clean generation. A short machine-readable code (Section 8.6) when the never-block fallback path (Section 8.7) was used. |

### 8.4 Validation Rules

Enforced by a Pydantic model, `ResponseOutput`, mirroring the `model_validator`-based pattern already used by `UnderstandingOutput` and `KnowledgeOutput`:

```python
class ResponseOutput(BaseModel):
    answer: str
    source: Literal["rag", "llm"]
    answer_type: Literal[
        "concept_explanation", "therapy_information", "course_information",
        "research_summary", "website_information", "personal_guidance",
        "supportive_information", "general_knowledge",
    ]
    topic: str
    intent: str
    confidence: float
    grounded_chunk_ids: list[str]
    generation_time_ms: float
    error: Optional[str]

    @model_validator(mode="after")
    def _validate_answer_quality(self) -> "ResponseOutput":
        stripped = self.answer.strip()
        if len(stripped) < settings.response_min_answer_length:
            raise ValueError("answer shorter than response_min_answer_length")
        lowered = stripped.lower()
        if any(phrase in lowered for phrase in BANNED_PHRASES):
            raise ValueError("answer contains a banned refusal phrase")
        return self

    @model_validator(mode="after")
    def _validate_source_consistency(self) -> "ResponseOutput":
        if self.source == "llm" and self.grounded_chunk_ids:
            raise ValueError("source=='llm' requires empty grounded_chunk_ids")
        if self.source == "rag" and not self.grounded_chunk_ids:
            raise ValueError("source=='rag' requires non-empty grounded_chunk_ids")
        return self
```

Additional rules not expressible as static field validation, checked separately by the node before this model is constructed (Section 6.4):

* The document-dump shingle-overlap check runs against `knowledge.retrieved_docs`, which the Pydantic model itself has no access to — a failure here is treated identically to a `ValidationError` for retry purposes (Section 8.7).
* `source`, `topic`, `intent`, and `confidence` are never independently validated against the LLM's output, because the LLM never produces them — they are assigned by the node itself and are correct by construction (FR-9, FR-13).

### 8.5 Error Handling

Recognized `error` codes, all of which route through the same never-block fallback (Section 8.7) rather than raising:

| Code | Meaning |
|---|---|
| `null` | Clean generation; no fallback used. |
| `"llm_call_failure"` | The chat completion API call raised (timeout, connection error, API error) on both the initial attempt and the corrective retry. |
| `"quality_guard_exhausted"` | Both the initial attempt and the corrective retry produced an answer that failed the min-length check, the banned-phrase check, or the document-dump check; the best-effort fallback in Section 8.7 was used instead. |

These mirror Phase 2's `error` field exactly in spirit (Phase 2 Section 8.6): a non-null `error` is an internal observability signal, logged as a `response_node_failure` event, and is never itself shown to the user — the `answer` field always contains real, displayable text regardless of `error`'s value.

### 8.6 Best-Effort Fallback Algorithm (FR-12)

The node must never refuse, but it also must never raise. When both generation attempts (initial + one corrective retry, Section 5.1 step 8) fail to produce a guard-passing answer, or the LLM call itself errors on both attempts, the node falls back deterministically rather than blocking:

```python
def _select_fallback(attempts: list[GenerationAttempt], llm_call_failed: bool) -> tuple[str, str]:
    """Returns (answer, error_code). Never raises. Never empty."""
    if llm_call_failed:
        return (
            "I'm having trouble putting together an answer right now — could you ask "
            "that again in a moment?",
            "llm_call_failure",
        )
    # At least one attempt produced text, even if it failed a guard.
    # Prefer the attempt with the fewest guard violations; on a tie, prefer the longer one.
    best = min(attempts, key=lambda a: (a.violation_count, -len(a.answer)))
    return best.answer, "quality_guard_exhausted"
```

This is the only place in the node where a templated (non-LLM-generated) string is used, and it is reserved exclusively for the infrastructure-failure case (`llm_call_failure`) — a transient system error, not a substantive "I don't know," and distinguishable from it by both the `error` code and by not being one of the `BANNED_PHRASES` (Section 6.3). It does not violate FR-4/FR-12: it is a statement that *generation is temporarily unavailable*, not a claim that *no answer exists*. For `quality_guard_exhausted`, the node still returns genuine LLM-generated content (the least-bad of the two attempts) rather than a template — a guard failure means the wording needs work, not that the underlying answer was wrong or absent.

---

