from typing import Literal, Optional, TypedDict


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


class RetrievedDocument(TypedDict):
    chunk_id: str
    content: str
    content_type: Literal[
        "course",
        "blog",
        "research_article",
        "faq",
        "practitioner_info",
        "therapy_info",
        "website_content",
        "neuroplasticity_content",
        "pdf_document",
        # Structured knowledge corpora under data/knowledge/**. Only concern_knowledge is
        # populated today; the rest are reserved so adding a corpus is a content task, not
        # a schema change across every node.
        "concern_knowledge",
        "condition_knowledge",
        "therapy_knowledge",
        "assessment_knowledge",
        "milestone_knowledge",
    ]
    source_title: str
    source_url: Optional[str]
    similarity_score: float
    metadata: dict


class RelatedConcernSummary(TypedDict):
    concern_id: str
    title: str
    summary: str
    relation: str


class ResolvedConcern(TypedDict):
    """One concern file resolved from the retrieved chunks (Knowledge Node stage B).

    Carries the *structured* record rather than chunk text, so Response Generation
    assembles an answer from named sections instead of stitching fragments. Section
    bullets are keyed by the loader's section keys (summary, possible_explanations, ...).
    """

    concern_id: str
    title: str
    category: str
    topic: str
    score: float
    margin: float
    matched_sections: list[str]
    development_domains: list[str]
    related_therapies: list[str]
    sections: dict[str, list[str]]
    summary: str
    related_concerns: list[RelatedConcernSummary]


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
    resolved_concern: Optional[ResolvedConcern]


class Response(TypedDict):
    answer: str
    source: Literal["rag", "llm"]
    answer_type: Literal[
        "concept_explanation",
        "therapy_information",
        "course_information",
        "research_summary",
        "website_information",
        "personal_guidance",
        "supportive_information",
        "general_knowledge",
    ]
    topic: str
    intent: str
    confidence: float
    grounded_chunk_ids: list[str]
    generation_time_ms: float
    error: Optional[str]


class Empathy(TypedDict):
    final_answer: str
    emotional_state: Literal[
        "neutral", "curious", "confused", "worried", "overwhelmed", "frustrated"
    ]
    source: Literal["rag", "llm"]
    answer_type: Literal[
        "concept_explanation",
        "therapy_information",
        "course_information",
        "research_summary",
        "website_information",
        "personal_guidance",
        "supportive_information",
        "general_knowledge",
    ]
    topic: str
    intent: str
    confidence: float
    grounded_chunk_ids: list[str]
    humanization_time_ms: float
    error: Optional[str]


class Safety(TypedDict):
    safe_response: str
    safety_status: Literal["approved", "modified", "escalated"]
    violations_detected: list[str]
    escalation_level: Literal["none", "moderate", "high"]
    disclaimer_added: bool
    original_final_answer: str
    emotional_state: Literal[
        "neutral", "curious", "confused", "worried", "overwhelmed", "frustrated"
    ]
    source: Literal["rag", "llm"]
    answer_type: Literal[
        "concept_explanation",
        "therapy_information",
        "course_information",
        "research_summary",
        "website_information",
        "personal_guidance",
        "supportive_information",
        "general_knowledge",
    ]
    topic: str
    intent: str
    confidence: float
    grounded_chunk_ids: list[str]
    validation_time_ms: float
    error: Optional[str]


class CTA(TypedDict):
    cta_found: bool
    cta_id: Optional[str]
    cta_url: Optional[str]
    cta_trigger: Optional[str]
    cta_category: Optional[str]
    match_reason: Literal["specific_match", "category_fallback", "no_match"]
    matched_phrase: Optional[str]
    response: str
    lookup_time_ms: float
    error: Optional[str]


class GraphState(TypedDict):
    user_message: str
    chat_history: list[ChatTurn]
    understanding: Optional[Understanding]
    knowledge: Optional[Knowledge]
    response: Optional[Response]
    empathy: Optional[Empathy]
    safety: Optional[Safety]
    cta: Optional[CTA]
