from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The user's question")
    session_id: str = Field(default="default", description="Conversation session identifier")
    user_id: Optional[str] = None


class SourceChunk(BaseModel):
    source: str
    content: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    cta: "CTAResponse"


class UnderstandResponse(BaseModel):
    intent: str
    topic: str
    search_query: str
    emotional_state: str


class RetrievedDocumentModel(BaseModel):
    chunk_id: str
    content: str
    content_type: str
    source_title: str
    source_url: str | None
    similarity_score: float
    metadata: dict


class KnowledgeResponse(BaseModel):
    source: str
    retrieved_docs: list[RetrievedDocumentModel]
    confidence: float
    query_used: str
    intent: str
    retrieval_skipped: bool
    content_types_searched: list[str]
    retrieval_time_ms: float
    error: str | None


class AnswerResponse(BaseModel):
    answer: str
    source: str
    answer_type: str
    topic: str
    intent: str
    confidence: float
    grounded_chunk_ids: list[str]
    generation_time_ms: float
    error: str | None


class HumanizeResponse(BaseModel):
    final_answer: str
    emotional_state: str
    source: str
    answer_type: str
    topic: str
    intent: str
    confidence: float
    grounded_chunk_ids: list[str]
    humanization_time_ms: float
    error: str | None


class SafetyResponse(BaseModel):
    safe_response: str
    safety_status: str
    violations_detected: list[str]
    escalation_level: str
    disclaimer_added: bool
    original_final_answer: str
    emotional_state: str
    source: str
    answer_type: str
    topic: str
    intent: str
    confidence: float
    grounded_chunk_ids: list[str]
    validation_time_ms: float
    error: str | None


class CTAResponse(BaseModel):
    cta_found: bool
    cta_id: str | None
    cta_url: str | None
    cta_trigger: str | None
    cta_category: str | None
    match_reason: str
    matched_phrase: str | None
    response: str
    lookup_time_ms: float
    error: str | None
