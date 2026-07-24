import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from app.config import settings
from app.db import supabase
from app.roadmap import services as roadmap_services
from app.roadmap.mapping_loader import MappingLoadError, get_mappings
from app.roadmap.routes import router as roadmap_router
from app.models import (
    AnswerResponse,
    ChatRequest,
    ChatResponse,
    CTAResponse,
    HumanizeResponse,
    KnowledgeResponse,
    SafetyResponse,
    SourceChunk,
    UnderstandResponse,
)
from app.nodes.cta_node import build_cta_graph, cta_node
from app.nodes.empathy_node import build_empathy_graph
from app.nodes.knowledge_node import build_knowledge_graph
from app.nodes.response_node import build_response_graph
from app.nodes.safety_node import build_safety_graph
from app.nodes.understanding_node import build_understanding_graph
from app.rag.chain import build_chain

from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("app.main")

MAX_HISTORY_TURNS = 6

chat_chain = None
understanding_graph = None
knowledge_graph = None
response_graph = None
empathy_graph = None
safety_graph = None
cta_graph = None
session_histories: dict[str, list] = {}


def _validate_mapping_data() -> None:
    """Eagerly load the therapy-mapping workbooks at startup so a misnamed,
    missing, or corrupt file surfaces here -- with its real cause -- instead of
    as an opaque `mapping_data_unavailable` 500 on the first request.

    Deliberately NON-fatal: the loader's design keeps this off the import path so
    a bad workbook can't take down the whole app (chat and the other endpoints
    don't need it). We warm the cache and log the exact reason loudly; the
    /roadmap/mapped-therapies route still returns its typed error if it's broken.
    """
    try:
        bundle = get_mappings()
        logger.info(
            "startup: therapy mapping data OK (ND=%d rows, NT=%d rows) from %s",
            bundle.neurodivergent.row_count,
            bundle.neurotypical.row_count,
            settings.roadmap_mapping_dir,
        )
    except MappingLoadError as exc:
        logger.error(
            "startup: THERAPY MAPPING DATA UNAVAILABLE -- /roadmap/mapped-therapies "
            "will fail until this is fixed. code=%s source=%s field=%s: %s",
            exc.code,
            exc.source,
            exc.field,
            exc.message,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global chat_chain, understanding_graph, knowledge_graph, response_graph, empathy_graph, safety_graph, cta_graph
    settings.validate()
    _validate_mapping_data()
    chat_chain = build_chain()
    understanding_graph = build_understanding_graph()
    knowledge_graph = build_knowledge_graph()
    response_graph = build_response_graph()
    empathy_graph = build_empathy_graph()
    safety_graph = build_safety_graph()
    cta_graph = build_cta_graph()
    yield


app = FastAPI(title="Manasi - ManaScience RAG Chatbot", lifespan=lifespan)

origins = [
    "http://localhost:5173", 
    "http://127.0.0.1:5173",
    "http://192.168.29.34:5173",
    "https://manascience.in",
    "https://www.manascience.in",
    "https://manascience.webflow.io"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(roadmap_router)


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if chat_chain is None:
        raise HTTPException(status_code=503, detail="Chatbot is still starting up")

    if not request.session_id or request.session_id.strip() == "":
        raise HTTPException(status_code=422, detail="A valid session_id must be provided")

    # 1. Fetch individual history matching the session_id row
    response = supabase.table("user_chat_histories") \
        .select("history, user_id") \
        .eq("session_id", request.session_id.strip()) \
        .execute()
        
    db_record = response.data[0] if (response.data and len(response.data) > 0) else None
    paired_history = db_record["history"] if db_record else []

    # 2. Extract Langchain components
    langchain_history = _convert_structured_to_langchain(paired_history)
    roadmap_context = roadmap_services.get_roadmap_context_text(request.session_id, supabase)

    # 3. Process Prompt Chain Execution
    result = chat_chain.invoke(
        {
            "input": request.message,
            "chat_history": langchain_history,
            "roadmap_context": roadmap_context,
        }
    )

    sources = [
        SourceChunk(source=doc.metadata.get("source", "unknown"), content=doc.page_content)
        for doc in result.get("context", [])
    ]
    cta_result = cta_node(
        {"user_message": request.message, "understanding": None, "safety": {"safe_response": result["answer"]}}
    )["cta"]
    
    new_turn = {
        "question": request.message,
        "answer": result["answer"],
        "cta": cta_result
    }
    paired_history.append(new_turn)

  # 4. Infer user payload identity
    # Look at existing database entry first; fallback to incoming request parameter if row is missing
    current_user_id = db_record["user_id"] if db_record else None
    if not current_user_id and request.user_id and request.user_id.strip() != "":
        current_user_id = request.user_id.strip()
    
    # Update title dynamically for the first turn to mirror real chat applications
    derived_title = f"Chat: {request.message[:25]}..." if len(paired_history) <= 1 else (db_record.get("title") if db_record else "New Assessment/Chat")

    # 5. Upsert tracking details matching session_id
    upsert_payload = {
        "session_id": request.session_id.strip(),
        "history": paired_history,
        "title": derived_title,
        "updated_at": "now()"
    }
    
    # This block now catches the user_id correctly on the first message send turn!
    if current_user_id:
        upsert_payload["user_id"] = current_user_id

    supabase.table("user_chat_histories").upsert(upsert_payload, on_conflict="session_id").execute()
    
    return ChatResponse(answer=result["answer"], sources=sources, cta=CTAResponse(**cta_result))


class SaveTurnRequest(BaseModel):
    session_id: str
    user_id: Optional[str] = None
    question: str
    answer: str

@app.post("/chat/save_turn")
def save_turn(request: SaveTurnRequest):
    if not request.session_id or request.session_id.strip() == "":
        raise HTTPException(status_code=422, detail="A valid session_id must be provided")

    # 1. Fetch current history matching the session row token
    response = supabase.table("user_chat_histories") \
        .select("history, title, user_id") \
        .eq("session_id", request.session_id.strip()) \
        .execute()
        
    db_record = response.data[0] if (response.data and len(response.data) > 0) else None
    paired_history = db_record["history"] if db_record else []

    # 2. Append the quiz turn trace layout
    new_turn = {
        "question": request.question,
        "answer": request.answer,
        "cta": None
    }
    paired_history.append(new_turn)

    # 3. Determine identity reference points
    resolved_uid = db_record["user_id"] if db_record else request.user_id
    derived_title = db_record.get("title") if db_record else "Roadmap Assessment"

    # 4. Save/Commit back down to Supabase
    upsert_payload = {
        "session_id": request.session_id.strip(),
        "history": paired_history,
        "title": derived_title,
        "updated_at": "now()"
    }
    if resolved_uid:
        upsert_payload["user_id"] = resolved_uid

    supabase.table("user_chat_histories").upsert(upsert_payload, on_conflict="session_id").execute()
    return {"status": "saved"}

@app.get("/chat/user/{user_id}/history")
def get_user_chat_history_list(user_id: str):
    """
    Sidebar Loader: Retrieves all distinct chat conversation sessions 
    belonging to a specific authenticated profile.
    """
    response = supabase.table("user_chat_histories") \
        .select("session_id, title, history, updated_at") \
        .eq("user_id", user_id) \
        .order("updated_at", desc=True) \
        .execute()
        
    return {
        "user_id": user_id,
        "history_records": response.data if response.data else []
    }


@app.get("/chat/session/{session_id}")
def get_single_session_history(session_id: str):
    """
    Window Loader: Retrieves a singular specific chat session record 
    (Works for loading an active conversation window).
    """
    response = supabase.table("user_chat_histories") \
        .select("session_id, title, history, updated_at, user_id") \
        .eq("session_id", session_id) \
        .execute()
        
    return {
        "session_id": session_id,
        "record": response.data[0] if (response.data and len(response.data) > 0) else None
    }


@app.delete("/chat/{session_id}")
def reset_session(session_id: str):
    """
    Deletes a specific conversation thread from both the live cache 
    and the permanent Supabase database records.
    """
    # 1. Clear the local transient server memory chunk
    session_histories.pop(session_id, None)
    
    # 2. Delete the row directly from Supabase so it drops off the frontend sidebar
    supabase.table("user_chat_histories") \
        .delete() \
        .eq("session_id", session_id) \
        .execute()
        
    return {"status": "deleted", "session_id": session_id}


def _history_to_chat_turns(history: list) -> list[dict]:
    return [
        {"role": "user" if isinstance(msg, HumanMessage) else "assistant", "content": msg.content}
        for msg in history
    ]
    
def _convert_structured_to_langchain(paired_history: list[dict]) -> list:
    flat_messages = []
    for turn in paired_history:
        flat_messages.append(HumanMessage(content=turn.get("question", "")))
        flat_messages.append(AIMessage(content=turn.get("answer", "")))
    return flat_messages


@app.post("/understand", response_model=UnderstandResponse)
def understand(request: ChatRequest):
    if understanding_graph is None:
        raise HTTPException(status_code=503, detail="Understanding node is still starting up")

    history = session_histories.get(request.session_id, [])
    result = understanding_graph.invoke(
        {
            "user_message": request.message,
            "chat_history": _history_to_chat_turns(history),
            "understanding": None,
        }
    )
    return UnderstandResponse(**result["understanding"])


@app.post("/knowledge", response_model=KnowledgeResponse)
def knowledge(request: ChatRequest):
    if knowledge_graph is None:
        raise HTTPException(status_code=503, detail="Knowledge node is still starting up")

    history = session_histories.get(request.session_id, [])
    result = knowledge_graph.invoke(
        {
            "user_message": request.message,
            "chat_history": _history_to_chat_turns(history),
            "understanding": None,
            "knowledge": None,
        }
    )
    return KnowledgeResponse(**result["knowledge"])


@app.post("/respond", response_model=AnswerResponse)
def respond(request: ChatRequest):
    if response_graph is None:
        raise HTTPException(status_code=503, detail="Response node is still starting up")

    history = session_histories.get(request.session_id, [])
    result = response_graph.invoke(
        {
            "user_message": request.message,
            "chat_history": _history_to_chat_turns(history),
            "understanding": None,
            "knowledge": None,
            "response": None,
        }
    )
    return AnswerResponse(**result["response"])


@app.post("/humanize", response_model=HumanizeResponse)
def humanize(request: ChatRequest):
    if empathy_graph is None:
        raise HTTPException(status_code=503, detail="Empathy node is still starting up")

    history = session_histories.get(request.session_id, [])
    result = empathy_graph.invoke(
        {
            "user_message": request.message,
            "chat_history": _history_to_chat_turns(history),
            "understanding": None,
            "knowledge": None,
            "response": None,
            "empathy": None,
        }
    )
    return HumanizeResponse(**result["empathy"])


@app.post("/safety", response_model=SafetyResponse)
def safety(request: ChatRequest):
    if safety_graph is None:
        raise HTTPException(status_code=503, detail="Safety node is still starting up")

    history = session_histories.get(request.session_id, [])
    result = safety_graph.invoke(
        {
            "user_message": request.message,
            "chat_history": _history_to_chat_turns(history),
            "understanding": None,
            "knowledge": None,
            "response": None,
            "empathy": None,
            "safety": None,
        }
    )
    return SafetyResponse(**result["safety"])


@app.post("/cta", response_model=CTAResponse)
def cta(request: ChatRequest):
    if cta_graph is None:
        raise HTTPException(status_code=503, detail="CTA node is still starting up")

    history = session_histories.get(request.session_id, [])
    result = cta_graph.invoke(
        {
            "user_message": request.message,
            "chat_history": _history_to_chat_turns(history),
            "understanding": None,
            "knowledge": None,
            "response": None,
            "empathy": None,
            "safety": None,
            "cta": None,
        }
    )
    return CTAResponse(**result["cta"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)