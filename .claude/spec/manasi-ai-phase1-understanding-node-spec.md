# Manasi AI — Phase 1 Technical Specification
## Understanding Node

**Project:** Manasi AI
**Organization:** ManaScience
**Phase:** 1 of N — Understanding Node
**Status:** Draft for implementation
**Audience:** Python + FastAPI + LangGraph engineer

---

## 1. Executive Summary

Manasi AI is ManaScience's empathetic AI guide, designed to help users understand neuroplasticity, developmental challenges, therapies, courses, research, and ManaScience's website content through natural conversation.

This document specifies **Phase 1 only: the Understanding Node** — the first node in the Manasi AI LangGraph pipeline. The Understanding Node's sole responsibility is to read an incoming user message and convert it into a structured, machine-readable representation: intent, topic, emotional state, and an optimized search query. It performs **no retrieval, no answer generation, no empathy transformation, no disclaimer logic, and no safety logic** — those are explicitly out of scope and will be specified in later phases.

The Understanding Node is the foundation the rest of the pipeline depends on. If it misclassifies intent or emotional state, every downstream node (retrieval, response generation, empathy shaping, safety checks) inherits that error. Phase 1 must therefore be implemented and validated in isolation, with a stable, well-tested output contract before any other node is built against it.

---

## 2. Business Objective

ManaScience needs Manasi to feel like a knowledgeable, caring guide rather than a generic chatbot. Achieving that tone reliably requires the system to *understand* what a user is actually asking and how they feel before it tries to answer — a worried parent asking about attention difficulties needs a different retrieval path and a different tone than a curious learner asking about neuroplasticity in the abstract.

The Understanding Node exists to make that distinction explicit and structured, so that:

* Retrieval (Phase 2) can fetch the *right* documents instead of generic keyword matches.
* Response generation (Phase 3) can calibrate tone and depth to the user's emotional state.
* Empathy transformation and safety/disclaimer logic (later phases) have a reliable signal — emotional state and intent — to act on, instead of re-deriving it themselves.

By isolating "understanding" into its own node with a strict, narrow contract (structured JSON, no answers), the system stays debuggable: if Manasi gives a bad answer, engineers can inspect the Understanding Node's output independently of retrieval and generation to localize the fault.

---

## 3. Functional Requirements

### FR-1: Message Analysis
The node SHALL accept a single most-recent user message (and optionally prior conversation history for context) and produce a structured analysis without generating any user-facing answer text.

### FR-2: Intent Classification
The node SHALL classify the user's message into exactly one of the eight supported intent categories (Section 5). If a message plausibly spans multiple intents, the node SHALL select the single best-fit primary intent using the precedence rules in Section 5.10.

### FR-3: Topic Extraction
The node SHALL identify the main subject of the message as a short, normalized topic string (e.g., `"neuroplasticity"`, `"attention difficulties"`, `"ManaScience therapies"`). Topic extraction SHALL NOT be left empty except in `general_chat` cases where no concrete subject exists.

### FR-4: Emotional State Detection
The node SHALL classify the emotional tone of the message into exactly one of the six supported emotional states (Section 6).

### FR-5: Query Rewriting
The node SHALL rewrite the user's message into a retrieval-optimized search query string suitable for embedding-based or hybrid search (Section 7). This field is REQUIRED even when the intent does not require retrieval (e.g., `emotional_support`), so that downstream nodes have a consistent contract; in those cases the query SHALL reflect the underlying topic of concern rather than being empty.

### FR-6: Structured Output
The node SHALL emit a single JSON object conforming exactly to the schema in Section 8. The node SHALL NOT emit prose, markdown, explanations, or any text outside the JSON object.

### FR-7: No Answering
The node SHALL NEVER attempt to answer the user's question, provide factual information about neuroplasticity/therapies/courses, offer reassurance text, or produce any user-facing content. Its only output is the structured JSON object.

### FR-8: Conversation History Awareness
When prior turns are available, the node SHALL use them to disambiguate pronouns, follow-up questions, and topic continuity (e.g., "What about for adults?" following a question about a child therapy) when rewriting the query and extracting topic/intent. History SHALL NOT change the output schema.

### FR-9: Determinism Within Tolerance
Given the same message and history, repeated invocations SHOULD produce the same intent and emotional_state classification. Minor wording variation in `search_query` across repeated calls is acceptable; classification fields (`intent`, `emotional_state`) are NOT acceptable to vary.

---

## 4. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Latency** | The Understanding Node SHOULD complete in under 1.5s p95 using the configured LLM, since it sits before retrieval and generation in the user-facing latency budget. |
| **Reliability** | The node MUST return valid JSON on every invocation. If the underlying LLM returns malformed output, the node MUST retry once with a corrective re-prompt before falling back to an error state (Section 8.4). |
| **Statelessness** | The node itself SHALL be a pure function of (message, history) → JSON. It SHALL NOT persist state, call retrieval, or call any external API other than the LLM. |
| **Testability** | The node MUST be unit-testable in isolation from retrieval/generation, using fixed message inputs and asserting on JSON output. |
| **Observability** | Every invocation SHOULD be logged with input message, output JSON, latency, and any retry/fallback events, to support tuning intent/emotion accuracy over time. |
| **Cost** | The node SHOULD use a small/fast LLM tier where possible, since it is a classification + rewriting task, not a generation task requiring the largest available model. |
| **Extensibility** | Adding a new intent or emotional state SHALL require only a prompt and schema enum update, not a structural rewrite of the node. |
| **Privacy** | The node MUST NOT log or forward personally identifiable information beyond what the user already typed; no additional PII inference fields are in scope for Phase 1. |

---

## 5. Architecture

### 5.1 Position in the Pipeline

```
User Message
     │
     ▼
┌─────────────────────┐
│  Understanding Node  │  ◄── Phase 1 (this document)
│  (this spec)         │
└─────────────────────┘
     │  structured JSON
     ▼
┌─────────────────────┐
│  Retrieval Node      │  ◄── Phase 2 (out of scope)
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│  Response Generation │  ◄── Phase 3 (out of scope)
│  + Empathy Transform │
│  + Disclaimer/Safety │
└─────────────────────┘
     │
     ▼
Final Answer to User
```

### 5.2 Internal Composition

The Understanding Node is a single LangGraph node internally composed of three logical steps, all performed by one LLM call to minimize latency:

1. **Context assembly** — combine current message with relevant prior turns (if any).
2. **LLM classification + rewriting call** — single prompt (Section 9) that performs intent, topic, emotion, and query rewriting together.
3. **Validation + parsing** — parse and validate the LLM's JSON output against the schema (Section 8) before writing it into LangGraph state.

A single combined LLM call (rather than four separate calls for intent/topic/emotion/rewrite) is recommended to keep latency and cost low, since all four outputs are derived from the same read of the message and benefit from shared context.

### 5.3 Why Understanding Is Isolated

Separating understanding from retrieval and generation means:

* Retrieval logic can change (vector DB, hybrid search, reranking) without touching how intent/emotion is detected.
* Generation/empathy/safety logic (Phases 2+) can be tuned independently using the same stable understanding contract.
* Misbehavior is localizable: a bad final answer can be traced to "Understanding got the intent wrong" vs. "Retrieval found nothing" vs. "Generation answered poorly" by inspecting the JSON at each stage.

---

## 6. Supported Intents

The node classifies every message into exactly one of the following eight intents.

### 6.1 `concept_explanation`
**Meaning:** The user wants to understand a concept, mechanism, or idea (e.g., neuroplasticity, sensory processing, developmental milestones) in general, educational terms — not tied to a specific therapy, course, or their personal situation.

**Detection logic:** Message asks "what is X", "how does X work", "can you explain/elaborate X", where X is a concept/scientific term rather than a product, service, or personal situation.

**Examples:**
- "Can you elaborate neuroplasticity?"
- "What is sensory integration?"
- "How does the brain rewire itself after injury?"

**Expected output (example):**
```json
{
  "intent": "concept_explanation",
  "topic": "neuroplasticity",
  "search_query": "Explain neuroplasticity in simple language",
  "emotional_state": "curious"
}
```

### 6.2 `therapy_information`
**Meaning:** The user is asking about specific therapies, interventions, or treatment approaches that ManaScience offers or discusses.

**Detection logic:** Message references a named therapy/intervention, asks "what therapies do you offer," "does X therapy help with Y," or asks about therapy mechanics, duration, or suitability in general (non-personalized) terms.

**Examples:**
- "What therapies do you provide?"
- "Does occupational therapy help with sensory issues?"
- "How long does a typical therapy program last?"

**Expected output (example):**
```json
{
  "intent": "therapy_information",
  "topic": "ManaScience therapies",
  "search_query": "ManaScience therapies offered",
  "emotional_state": "curious"
}
```

### 6.3 `course_information`
**Meaning:** The user is asking about ManaScience's educational courses, training programs, or learning materials.

**Detection logic:** Message references "course," "program," "training," "certification," "curriculum," or asks how to enroll/learn through ManaScience's structured offerings.

**Examples:**
- "What courses do you have on neuroplasticity?"
- "Is there a training program for caregivers?"

**Expected output (example):**
```json
{
  "intent": "course_information",
  "topic": "ManaScience courses",
  "search_query": "ManaScience courses on neuroplasticity for caregivers",
  "emotional_state": "curious"
}
```

### 6.4 `research_information`
**Meaning:** The user wants to know about research, studies, evidence, or scientific literature behind a concept or therapy.

**Detection logic:** Message uses words like "research," "studies," "evidence," "proven," "science behind," or asks for citations/sources.

**Examples:**
- "Is there research backing neuroplasticity-based therapy?"
- "What does the science say about early intervention?"

**Expected output (example):**
```json
{
  "intent": "research_information",
  "topic": "evidence for neuroplasticity-based therapy",
  "search_query": "research evidence neuroplasticity-based therapy effectiveness",
  "emotional_state": "curious"
}
```

### 6.5 `website_information`
**Meaning:** The user is asking about ManaScience itself as a platform/organization — navigation, account, pricing, contact, "who are you," blog content, etc. — rather than clinical or scientific content.

**Detection logic:** Message references the platform/website/organization directly: "how do I sign up," "where can I find your blog," "who runs ManaScience," "how do I contact support."

**Examples:**
- "How do I create an account on ManaScience?"
- "Where can I read your blog posts?"

**Expected output (example):**
```json
{
  "intent": "website_information",
  "topic": "ManaScience account signup",
  "search_query": "how to create a ManaScience account",
  "emotional_state": "neutral"
}
```

### 6.6 `personal_concern`
**Meaning:** The user describes a specific situation involving themselves or someone they care about (a child, family member, client) and is seeking information relevant to that situation — but is not explicitly asking for emotional support.

**Detection logic:** Message includes a personal reference ("my child," "my son," "I struggle with") paired with a description of a challenge, without strong distress language.

**Examples:**
- "My child struggles with attention."
- "My daughter has trouble with handwriting, is that related to motor skills?"

**Expected output (example):**
```json
{
  "intent": "personal_concern",
  "topic": "attention difficulties in a child",
  "search_query": "attention difficulties child development",
  "emotional_state": "worried"
}
```

### 6.7 `emotional_support`
**Meaning:** The user is primarily expressing distress, overwhelm, or seeking reassurance/comfort, where the emotional content dominates over a specific informational request.

**Detection logic:** Message is dominated by affect language ("I feel," "I'm scared," "I don't know what to do," "I'm exhausted") with little or no concrete informational question, or an explicit request for comfort/support.

**Examples:**
- "I'm so overwhelmed, I don't know if I'm doing enough for my son."
- "I just need to talk to someone, this has been really hard."

**Expected output (example):**
```json
{
  "intent": "emotional_support",
  "topic": "caregiver overwhelm",
  "search_query": "support for overwhelmed caregivers of children with developmental challenges",
  "emotional_state": "overwhelmed"
}
```

### 6.8 `general_chat`
**Meaning:** Greetings, small talk, gratitude, or messages with no concrete informational or emotional content relevant to ManaScience's domain.

**Detection logic:** Message is a greeting, thanks, farewell, or off-topic remark with no ManaScience-relevant subject matter.

**Examples:**
- "Hi Manasi!"
- "Thank you, that was helpful."

**Expected output (example):**
```json
{
  "intent": "general_chat",
  "topic": "",
  "search_query": "",
  "emotional_state": "neutral"
}
```

### 6.9 Intent Precedence Rules (for ambiguous messages)

When a message could match more than one intent, resolve using this precedence order (highest first):

1. `emotional_support` — if distress/overwhelm dominates the message, classify as emotional_support even if a factual question is also present, since tone must be handled before facts.
2. `personal_concern` — if a personal situation is described without dominant distress language.
3. `therapy_information` / `course_information` / `research_information` / `website_information` — if the message names a specific category (therapy, course, research, website/platform) without a personal frame.
4. `concept_explanation` — if the message is a general "what/how/why" question with no personal frame and no named category above.
5. `general_chat` — only if none of the above apply.

---

## 7. Emotional State Detection

### 7.1 Why Emotional Detection Matters

Manasi's value proposition is that it responds like a caring guide, not a generic chatbot. A flat, factual answer to "My child struggles with attention" reads as cold and clinical even if factually correct. Emotional state is the signal that lets downstream response generation (Phase 3) decide *how* to say something — leading with acknowledgment for a worried parent, staying light and direct for a curious learner. Phase 1 does not generate that empathetic phrasing itself; it only detects and labels the emotional state so later phases can act on it reliably.

### 7.2 Supported Emotional States

| State | Meaning |
|---|---|
| `neutral` | No notable emotional charge; informational or transactional tone. |
| `curious` | Genuine interest in learning more; positive, exploratory tone. |
| `confused` | User signals not understanding something, asks for clarification or simplification. |
| `worried` | User expresses concern about a specific situation, typically involving someone they care about. |
| `overwhelmed` | User expresses being unable to cope, exhausted, or facing too much at once. |
| `frustrated` | User expresses annoyance, impatience, or dissatisfaction (e.g., with a process, lack of progress, or the platform itself). |

### 7.3 Detection Rules

* **`neutral`** — default state when no emotional language, intensifiers, or distress markers are present. Used heavily for `website_information`, `general_chat`, and matter-of-fact `concept_explanation` queries.
* **`curious`** — presence of exploratory phrasing ("I'd love to understand," "can you elaborate," "interesting, tell me more") without distress markers.
* **`confused`** — explicit confusion markers ("I don't understand," "that doesn't make sense," "can you simplify," repeated clarifying questions).
* **`worried`** — concern markers tied to a specific person/situation ("I'm concerned," "is this normal," "should I be worried") without overwhelm-level intensity.
* **`overwhelmed`** — intensity/coping markers ("I can't keep up," "I don't know what to do anymore," "this is too much," "I'm exhausted").
* **`frustrated`** — annoyance/impatience markers ("this isn't working," "I've tried everything," "why is this so hard," irritated tone toward the platform or a lack of progress).

When multiple emotional markers are present, prefer the most intense one present (`overwhelmed` > `frustrated` ≈ `worried` > `confused` > `curious` > `neutral`), since downstream tone calibration should err toward more care rather than less.

### 7.4 Examples

| Message | Emotional State |
|---|---|
| "Can you elaborate neuroplasticity?" | curious |
| "Wait, I'm not sure I follow — what do you mean by 'rewiring'?" | confused |
| "My child struggles with attention, is that something to worry about?" | worried |
| "I'm so overwhelmed, I don't know if I'm doing enough for my son." | overwhelmed |
| "I've contacted support three times and nothing has changed, this is so frustrating." | frustrated |
| "How do I create an account on ManaScience?" | neutral |

### 7.5 Output Structure

Emotional state is emitted as a single string field, `emotional_state`, constrained to the six enum values above. It is always present, never null, and defaults to `"neutral"` when no signal is detected.

---

## 8. Query Rewriting Requirements

### 8.1 Objectives

The `search_query` field exists to maximize retrieval quality in Phase 2. Raw user messages are often conversational, ambiguous, or missing the domain vocabulary that matches ManaScience's indexed content. The rewritten query should:

* Strip conversational filler ("can you," "I was wondering," "elaborate") while preserving meaning.
* Surface domain-relevant vocabulary that increases the chance of matching indexed documents (e.g., "ManaScience therapies," "child development").
* Resolve pronouns and ellipsis using conversation history (e.g., "What about for adults?" → "attention therapy options for adults" if the prior turn was about attention therapy for children).
* Stay topic-focused and concise — a query, not a restated question.

### 8.2 Rules

1. The rewritten query MUST be in plain, simple language — not a complex Boolean or keyword-stuffed string.
2. The rewritten query MUST preserve the original meaning and MUST NOT introduce facts, assumptions, or specifics not present in the user's message or prior context.
3. The rewritten query SHOULD be 3–12 words; long enough to be specific, short enough to stay retrieval-friendly.
4. For `general_chat`, the rewritten query SHALL be an empty string `""` since there is nothing to retrieve.
5. For `emotional_support`, the rewritten query SHALL still reflect the underlying topic of concern (e.g., "support for overwhelmed caregivers") rather than being empty, so retrieval can still surface relevant supportive resources if Phase 2 chooses to use them.
6. The node MUST NOT answer or explain within the query string — it is a search query, not a response.

### 8.3 Examples

| User Message | Rewritten Query |
|---|---|
| "Can you elaborate neuroplasticity?" | "Explain neuroplasticity in simple language" |
| "What therapies do you provide?" | "ManaScience therapies offered" |
| "My child struggles with attention." | "attention difficulties child development" |
| "Is there any actual evidence this stuff works?" | "research evidence neuroplasticity-based therapy effectiveness" |
| "Where do I even sign up for this?" | "how to create a ManaScience account" |

### 8.4 Edge Cases

* **Empty or near-empty message** (e.g., "?", "hi"): classify as `general_chat`, `search_query` = `""`.
* **Multi-question messages** (e.g., "What is neuroplasticity and do you have courses on it?"): select the dominant/first concrete question for `intent` and `topic`, but the `search_query` MAY combine both concepts concisely if they are tightly related (e.g., "neuroplasticity courses overview"). Precedence rules in 6.9 still apply to `intent`.
* **Follow-up messages referencing prior turns** ("What about for adults?"): use conversation history to resolve the referent before rewriting; if no history is available, treat the message at face value and note lower confidence is acceptable (confidence scoring is out of scope for Phase 1, but the rewrite must not fabricate a referent it cannot resolve).
* **Non-English or mixed-language input:** out of scope for Phase 1; assume English input. (Flag as a future consideration, Section 16.)
* **Abusive or off-topic content:** Phase 1 performs no moderation/safety filtering; classify as `general_chat` if no legitimate informational/emotional content is present, and pass through as-is. Safety logic is explicitly deferred to a later phase.

---

## 9. Output Schema (JSON)

### 9.1 Schema Definition

```json
{
  "intent": "concept_explanation",
  "topic": "neuroplasticity",
  "search_query": "Explain neuroplasticity in simple language",
  "emotional_state": "curious"
}
```

### 9.2 Field Definitions

| Field | Type | Required | Allowed Values | Notes |
|---|---|---|---|---|
| `intent` | string (enum) | Yes | `concept_explanation`, `therapy_information`, `course_information`, `research_information`, `website_information`, `personal_concern`, `emotional_support`, `general_chat` | Exactly one value; never null, never an array. |
| `topic` | string | Yes | free text, normalized, lowercase preferred | May be `""` only when `intent == "general_chat"`. Max 80 characters. |
| `search_query` | string | Yes | free text | May be `""` only when `intent == "general_chat"`. Max 200 characters. |
| `emotional_state` | string (enum) | Yes | `neutral`, `curious`, `confused`, `worried`, `overwhelmed`, `frustrated` | Exactly one value; never null. Defaults to `neutral` when undetected. |

### 9.3 Validation Rules

* The output MUST be a single, valid JSON object — no surrounding prose, no markdown code fences, no trailing commentary.
* All four fields MUST be present in every response, even when empty strings.
* `intent` and `emotional_state` MUST be one of the literal enum values listed above — any other value is invalid.
* `topic` and `search_query` MUST be strings (never null, never numbers/objects/arrays).
* `topic` and `search_query` MUST be empty strings (`""`) when and only when `intent == "general_chat"`; for any other intent, both MUST be non-empty (except `search_query` may follow the emotional_support exception in 8.2.5, which still requires a non-empty string).
* No additional fields beyond the four defined SHALL be present in the output (no extra metadata, no nested objects) for Phase 1.

### 9.4 Error Handling

The Understanding Node wraps the raw LLM call with a validation layer:

1. **Parse attempt:** Try to `json.loads()` the LLM output.
2. **Schema validation:** Validate parsed object against the Pydantic model (Section 11.2) — enum membership, required fields, string types.
3. **On failure (parse error or validation error):** Retry exactly once with a corrective re-prompt that includes the original message plus an instruction such as: *"Your previous output was not valid JSON matching the required schema. Return ONLY a valid JSON object with the four required fields."*
4. **On second failure:** Return a deterministic fallback object rather than raising an unhandled exception, so the graph can continue safely:
   ```json
   {
     "intent": "general_chat",
     "topic": "",
     "search_query": "",
     "emotional_state": "neutral"
   }
   ```
   This fallback is logged as an `understanding_node_failure` event for monitoring (Section 4, Observability). Downstream nodes treat this fallback intent like any other `general_chat` result — Phase 1 does not special-case failure handling beyond logging it.

---

## 10. LangGraph Integration

### 10.1 Node Purpose

`understanding_node` is the entry node of the Manasi AI LangGraph. It is the first node executed for every user turn and is a required predecessor to the (future) retrieval node.

### 10.2 Input State

The node reads from the shared LangGraph state:

| State Field | Type | Source |
|---|---|---|
| `user_message` | `str` | Set by the API layer (e.g., FastAPI request handler) before graph invocation. |
| `chat_history` | `list[dict]` (e.g., `[{"role": "user"/"assistant", "content": str}, ...]`) | Carried over from prior turns in the conversation session. |

The node does not read or depend on any other state fields in Phase 1 (no retrieval results, no prior understanding output, since this is the first node).

### 10.3 Output State

The node writes a single new field into state:

| State Field | Type | Description |
|---|---|---|
| `understanding` | `dict` matching Section 9 schema | The structured understanding output for the current turn. |

The node MUST NOT mutate `user_message` or `chat_history`. It only adds `understanding` to state.

### 10.4 State Updates

Using LangGraph's typed state pattern (Section 11.1), the node's update is a partial state dict:

```python
{"understanding": {
    "intent": "...",
    "topic": "...",
    "search_query": "...",
    "emotional_state": "..."
}}
```

LangGraph merges this into the running `GraphState` for the turn. Because `understanding` is overwritten (not appended) each turn, Phase 1 does not retain a history of past `understanding` objects in state — if future phases need that, it should be added explicitly as a list field in a later revision, not assumed here.

### 10.5 Integration with Future Nodes

* **Phase 2 (Retrieval Node):** will read `state["understanding"]["search_query"]` and `state["understanding"]["intent"]` to decide retrieval strategy (e.g., skip retrieval entirely for `general_chat`/`emotional_support` with no informational need).
* **Phase 3 (Response Generation / Empathy Transformation):** will read `state["understanding"]["emotional_state"]` to calibrate tone, and `state["understanding"]["intent"]` to decide response structure (e.g., `personal_concern` may always route toward a gentle Personalized Roadmap mention).
* **Safety/Disclaimer logic (future phase):** may use `intent == "personal_concern"` or `emotional_state in ["overwhelmed", "worried"]` as a trigger condition, but the Understanding Node itself implements none of that logic — it only supplies the signal.

### 10.6 Recommended LangGraph Architecture

```
graph = StateGraph(GraphState)
graph.add_node("understanding_node", understanding_node)
graph.set_entry_point("understanding_node")
# Phase 2+ will add:
# graph.add_node("retrieval_node", retrieval_node)
# graph.add_edge("understanding_node", "retrieval_node")
graph.add_edge("understanding_node", END)  # Phase 1 terminates here for isolated testing
```

For Phase 1 isolated testing/deployment, the graph may terminate immediately after `understanding_node` so the node can be validated end-to-end (API → graph → JSON response) before Phase 2 is built.

### 10.7 State Definition (`graph/state.py`)

```python
from typing import TypedDict, Literal, Optional

class ChatTurn(TypedDict):
    role: Literal["user", "assistant"]
    content: str

class Understanding(TypedDict):
    intent: Literal[
        "concept_explanation",
        "therapy_information",
        "course_information",
        "research_information",
        "website_information",
        "personal_concern",
        "emotional_support",
        "general_chat",
    ]
    topic: str
    search_query: str
    emotional_state: Literal[
        "neutral", "curious", "confused", "worried", "overwhelmed", "frustrated"
    ]

class GraphState(TypedDict):
    user_message: str
    chat_history: list[ChatTurn]
    understanding: Optional[Understanding]
```

---

## 11. File Structure

```
graph/
    state.py

nodes/
    understanding_node.py

prompts/
    understanding_prompt.txt
```

### 11.1 `graph/state.py`
**Responsibility:** Defines the shared `GraphState` TypedDict (and supporting types `ChatTurn`, `Understanding`) used across all LangGraph nodes. This is the single source of truth for state shape; Phase 2+ nodes extend this file rather than defining parallel state structures.

### 11.2 `nodes/understanding_node.py`
**Responsibility:** Implements the `understanding_node(state: GraphState) -> dict` function. Responsibilities:
* Load `understanding_prompt.txt` and format it with `user_message` and `chat_history`.
* Call the configured LLM (small/fast tier per Section 4 NFRs).
* Parse and validate the response against a Pydantic model mirroring `Understanding`.
* Implement the retry-then-fallback error handling from Section 9.4.
* Return `{"understanding": {...}}` for LangGraph to merge into state.

Recommended Pydantic model co-located in this file (or in `graph/state.py` if preferred for reuse):

```python
from pydantic import BaseModel
from typing import Literal

class UnderstandingOutput(BaseModel):
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
```

### 11.3 `prompts/understanding_prompt.txt`
**Responsibility:** Holds the full system/instruction prompt (Section 12) as a standalone text file, kept separate from code so prompt iteration does not require a code deploy and can be tracked/diffed independently. Loaded and formatted (e.g., via `.format()` or a templating call) by `understanding_node.py`.

---

## 12. Prompt Engineering

### 12.1 Requirements

The prompt in `understanding_prompt.txt` MUST:

* Instruct the model to analyze only — never answer the user's question.
* Instruct the model to return JSON only, with no surrounding text or markdown.
* Provide the full intent taxonomy with definitions (Section 6).
* Provide the full emotional state taxonomy with definitions (Section 7).
* Instruct query rewriting per the rules in Section 8.
* Include the exact output schema with field names and types.
* Accept conversation history as optional context for disambiguation.

### 12.2 Production-Ready Prompt Example

```text
You are the Understanding Node for Manasi AI, ManaScience's guide.

Your ONLY job is to analyze the user's message and return a single structured
JSON object. You must NEVER answer the user's question, explain a concept,
offer reassurance, or produce any user-facing text. You are not generating a
response — you are structuring information for other systems to use.

Return ONLY a valid JSON object. No markdown, no code fences, no commentary,
no text before or after the JSON.

---
INTENT CATEGORIES (choose exactly one):

- concept_explanation: User wants to understand a general concept or
  mechanism (e.g., neuroplasticity, sensory processing), not tied to a
  specific therapy, course, or their personal situation.
- therapy_information: User asks about specific therapies, interventions,
  or treatment approaches ManaScience offers or discusses.
- course_information: User asks about ManaScience courses, training
  programs, or learning materials.
- research_information: User asks about research, studies, or evidence
  behind a concept or therapy.
- website_information: User asks about the ManaScience platform itself
  (account, navigation, blog, contact, pricing).
- personal_concern: User describes a specific situation involving
  themselves or someone they care about, seeking information, without
  dominant distress language.
- emotional_support: User's message is dominated by distress, overwhelm,
  or a request for comfort/reassurance, more than a concrete question.
- general_chat: Greetings, thanks, small talk, or off-topic messages with
  no concrete informational or emotional content.

If a message could fit more than one category, use this precedence order:
emotional_support > personal_concern > (therapy/course/research/website)_information
> concept_explanation > general_chat.

---
EMOTIONAL STATES (choose exactly one):

- neutral: no notable emotional charge.
- curious: genuine, positive interest in learning more.
- confused: signals not understanding, asks for clarification.
- worried: concern about a specific situation, not at overwhelm intensity.
- overwhelmed: expresses inability to cope, exhaustion, "too much."
- frustrated: annoyance, impatience, dissatisfaction.

If multiple signals are present, prefer the most intense:
overwhelmed > frustrated ≈ worried > confused > curious > neutral.

---
QUERY REWRITING RULES:

- Rewrite the user's message into a short (3-12 word), plain-language search
  query suitable for retrieval against ManaScience's knowledge base.
- Preserve meaning exactly. Do not add facts, assumptions, or specifics the
  user did not provide.
- Strip conversational filler ("can you," "I was wondering," "elaborate").
- Use conversation history to resolve pronouns/follow-ups (e.g., "what about
  for adults?" referring to a prior topic).
- If intent is general_chat, search_query MUST be "".
- If intent is emotional_support, search_query MUST still reflect the
  underlying topic of concern (not empty).

---
OUTPUT SCHEMA (return exactly these four fields, nothing more):

{
  "intent": "<one of the eight intent categories above>",
  "topic": "<short normalized topic string, or \"\" only if general_chat>",
  "search_query": "<rewritten query, or \"\" only if general_chat>",
  "emotional_state": "<one of the six emotional states above>"
}

---
CONVERSATION HISTORY (most recent last, may be empty):
{chat_history}

CURRENT USER MESSAGE:
{user_message}

Return the JSON object now.
```

### 12.3 Notes on Prompt Maintenance

* `{chat_history}` should be formatted as a simple turn-by-turn transcript (e.g., `User: ...` / `Manasi: ...`) rather than raw JSON, to keep token usage efficient and improve model comprehension.
* `{user_message}` is the verbatim current message — no preprocessing/cleaning beyond whitespace trimming, since the model needs to see the user's actual phrasing to detect emotional state accurately.
* This file should be versioned alongside code (e.g., committed to git) so prompt changes are reviewable, but is intentionally kept as plain text rather than embedded in Python to support fast iteration.

---

## 13. Examples (15+ Required Coverage)

| # | Category | User Message | Expected JSON Output |
|---|---|---|---|
| 1 | Neuroplasticity | "Can you elaborate neuroplasticity?" | `{"intent": "concept_explanation", "topic": "neuroplasticity", "search_query": "Explain neuroplasticity in simple language", "emotional_state": "curious"}` |
| 2 | Neuroplasticity | "How exactly does the brain rewire itself?" | `{"intent": "concept_explanation", "topic": "brain rewiring mechanisms", "search_query": "how the brain rewires itself neuroplasticity mechanism", "emotional_state": "curious"}` |
| 3 | Neuroplasticity | "Wait, I don't really get what 'neural pathways' means." | `{"intent": "concept_explanation", "topic": "neural pathways", "search_query": "what are neural pathways simple explanation", "emotional_state": "confused"}` |
| 4 | Therapy | "What therapies do you provide?" | `{"intent": "therapy_information", "topic": "ManaScience therapies", "search_query": "ManaScience therapies offered", "emotional_state": "curious"}` |
| 5 | Therapy | "Does occupational therapy actually help with sensory issues?" | `{"intent": "therapy_information", "topic": "occupational therapy for sensory issues", "search_query": "occupational therapy effectiveness sensory issues", "emotional_state": "curious"}` |
| 6 | Course | "What courses do you have on neuroplasticity?" | `{"intent": "course_information", "topic": "ManaScience courses on neuroplasticity", "search_query": "ManaScience courses neuroplasticity", "emotional_state": "curious"}` |
| 7 | Course | "Is there a certification program for caregivers?" | `{"intent": "course_information", "topic": "caregiver certification program", "search_query": "ManaScience certification program caregivers", "emotional_state": "curious"}` |
| 8 | Research | "Is there any actual evidence this stuff works?" | `{"intent": "research_information", "topic": "evidence for neuroplasticity-based therapy", "search_query": "research evidence neuroplasticity-based therapy effectiveness", "emotional_state": "frustrated"}` |
| 9 | Website | "How do I create an account on ManaScience?" | `{"intent": "website_information", "topic": "ManaScience account signup", "search_query": "how to create a ManaScience account", "emotional_state": "neutral"}` |
| 10 | Website | "Where can I read your blog posts?" | `{"intent": "website_information", "topic": "ManaScience blog", "search_query": "ManaScience blog posts location", "emotional_state": "neutral"}` |
| 11 | Personal Concern | "My child struggles with attention." | `{"intent": "personal_concern", "topic": "attention difficulties in a child", "search_query": "attention difficulties child development", "emotional_state": "worried"}` |
| 12 | Personal Concern | "My daughter has trouble with handwriting, is that related to motor skills?" | `{"intent": "personal_concern", "topic": "handwriting and motor skills in a child", "search_query": "handwriting difficulty motor skills children", "emotional_state": "worried"}` |
| 13 | Emotional Support | "I'm so overwhelmed, I don't know if I'm doing enough for my son." | `{"intent": "emotional_support", "topic": "caregiver overwhelm", "search_query": "support for overwhelmed caregivers of children with developmental challenges", "emotional_state": "overwhelmed"}` |
| 14 | Emotional Support | "I just need to talk to someone, this has been really hard lately." | `{"intent": "emotional_support", "topic": "caregiver emotional fatigue", "search_query": "support resources for caregivers feeling emotionally exhausted", "emotional_state": "overwhelmed"}` |
| 15 | General Chat | "Hi Manasi!" | `{"intent": "general_chat", "topic": "", "search_query": "", "emotional_state": "neutral"}` |
| 16 | General Chat | "Thank you, that was really helpful." | `{"intent": "general_chat", "topic": "", "search_query": "", "emotional_state": "neutral"}` |
| 17 | Frustrated/Website | "I've contacted support three times about my login and nothing's changed." | `{"intent": "website_information", "topic": "login support issue", "search_query": "ManaScience login support unresolved issue", "emotional_state": "frustrated"}` |
| 18 | Follow-up (history-dependent) | Prior turn about "attention therapy for children" → "What about for adults?" | `{"intent": "therapy_information", "topic": "attention therapy for adults", "search_query": "attention therapy options for adults", "emotional_state": "curious"}` |

---

## 14. Acceptance Criteria

### 14.1 Test Case Categories

| Test Category | Description | Pass Criteria |
|---|---|---|
| Schema validity | Run node against all 18 examples in Section 13 | 100% of outputs are valid JSON matching the schema in Section 9, with no extra/missing fields. |
| Intent accuracy | Run node against a labeled test set (≥50 messages spanning all 8 intents) | ≥90% exact-match accuracy against human-labeled intent. |
| Emotional state accuracy | Run node against a labeled test set (≥50 messages spanning all 6 states) | ≥85% exact-match accuracy against human-labeled emotional state (lower bar than intent, since emotion is inherently more subjective). |
| Query rewriting quality | Manual review of rewritten queries against Section 8 rules | ≥90% of rewrites judged by a human reviewer as "preserves meaning, retrieval-friendly, no hallucinated specifics." |
| No-answer guarantee | Run node against messages that invite an answer (e.g., "What is neuroplasticity?") | 0% of outputs contain explanatory/answering content in any field; `topic`/`search_query` describe the question, they do not answer it. |
| Empty/edge input handling | Run node against empty string, single punctuation, single emoji | 100% classified as `general_chat` with empty `topic`/`search_query`. |
| Malformed LLM output handling | Simulate LLM returning invalid JSON / missing field | Node retries once, then falls back to the deterministic fallback object (Section 9.4) without raising an unhandled exception. |
| Conversation history disambiguation | Run node against follow-up messages with prior turns provided vs. withheld | With history: correctly resolves referent (e.g., Example 18). Without history: does not fabricate a referent; treats message at face value. |
| Latency | Run node against 20 representative messages | p95 latency under 1.5s using the configured LLM tier (Section 4). |

### 14.2 Definition of Done

Phase 1 (Understanding Node) is considered complete only when **all** of the following hold:

1. Intent classification accuracy ≥90% on the labeled test set.
2. Emotional state detection accuracy ≥85% on the labeled test set.
3. Query rewriting judged retrieval-improving (≥90% human-reviewed pass rate) — measured qualitatively in Phase 1 since no retrieval system exists yet to measure quantitatively; a quantitative retrieval-quality benchmark is deferred to Phase 2.
4. JSON output is 100% schema-valid across the full test set, with the fallback path exercised and verified at least once in testing.
5. Zero instances of user-facing answer content appearing in any output field across the full test set.
6. The node is integrated into a LangGraph `StateGraph` per Section 10 and runnable end-to-end (API → graph → JSON) in isolation, without Phase 2/3 nodes existing yet.

---

## 15. Data Flow (Summary Diagram)

```
┌──────────────────────┐
│ FastAPI request       │
│ { message, history }  │
└──────────┬────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│ GraphState                                │
│  user_message: str                        │
│  chat_history: list[ChatTurn]              │
│  understanding: None                       │
└──────────┬────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│ understanding_node                         │
│  1. format understanding_prompt.txt        │
│  2. call LLM                                │
│  3. parse + validate JSON                   │
│  4. retry once on failure, else fallback    │
└──────────┬────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│ GraphState (updated)                       │
│  understanding: {                          │
│    intent, topic, search_query,             │
│    emotional_state                          │
│  }                                          │
└──────────┬────────────────────────────────┘
           │
           ▼
   (Phase 1 boundary — graph ends here
    for isolated testing; Phase 2 retrieval
    node attaches after this point)
```

---

## 16. Future Considerations

The following are explicitly **out of scope for Phase 1** but noted here so the engineer understands what the Understanding Node's output contract must remain stable for:

* **Phase 2 — Retrieval Node:** will consume `search_query` and `intent` to query the vector store / hybrid search and may skip retrieval entirely for `general_chat` or pure `emotional_support` cases.
* **Phase 3 — Response Generation, Empathy Transformation, Disclaimer/Safety Logic:** will consume `emotional_state` and `intent` to shape tone, decide when to surface the Personalized Roadmap, and apply "not a doctor/therapist" disclaimers for `personal_concern` and clinical-adjacent `therapy_information` queries.
* **Multi-language support:** Phase 1 assumes English input only; future phases may need a language-detection step feeding into or alongside the Understanding Node.
* **Confidence scoring:** Phase 1 does not emit a confidence score per field. A future revision may add `intent_confidence` / `emotional_state_confidence` fields if downstream phases need to branch on classification certainty (e.g., asking a clarifying question when confidence is low).
* **Multi-intent / compound message handling:** Phase 1 resolves compound messages to a single primary intent via precedence rules (Section 6.9). A future phase may support multi-intent decomposition if user testing shows this loses meaningful signal.
* **Understanding history tracking:** Phase 1's `understanding` state field is overwritten each turn. If future phases need trend detection (e.g., "user has expressed `overwhelmed` three turns in a row"), state will need to track a list of past `understanding` objects, not just the latest.
* **Moderation/abuse handling:** Phase 1 performs no content moderation. This is explicitly deferred to the safety logic phase referenced in the prompt's exclusions.

---

*End of Phase 1 Specification — Understanding Node.*
