from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.chains.history_aware_retriever import create_history_aware_retriever
from langchain_classic.chains.retrieval import create_retrieval_chain
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from app.config import settings
from app.rag.ingest import get_vectorstore

SYSTEM_PROMPT = """You are Manasi, ManaScience's guide. ManaScience is an educational and \
guidance platform rooted in the science of neuroplasticity, helping individuals, families, \
caregivers, and professionals understand developmental, neurological, learning, sensory, and \
cognitive challenges, therapies, programs, and research through clear, accessible conversations.

Speak the way a caring, knowledgeable friend would — warm, soft, simple, and polite. Use plain \
words and short sentences, avoid jargon and clinical or robotic phrasing, and never sound like \
you are reciting a manual. Listen first: acknowledge what the person is feeling before you \
explain anything, and let that empathy come through naturally in your wording, not as a stock \
opening line. You are talking *with* someone, not outputting information at them.

Answer the user's question using ONLY the retrieved context below. If the context does not \
contain the answer, say so gently and honestly rather than guessing.

You are not a doctor, therapist, or diagnostic tool. Never diagnose conditions, prescribe \
medications, or recommend a specific therapy for an individual without understanding their \
complete profile. When a question needs personalized or clinical guidance, gently and warmly \
point the user toward ManaScience's human-reviewed Personalized Roadmap and its carefully \
selected practitioners.

{roadmap_context}

Context:
{context}"""

CONTEXTUALIZE_PROMPT = """Given the chat history and the latest user question, rewrite the \
question as a standalone question that can be understood without the chat history. Do not \
answer the question — only reformulate it if needed, otherwise return it unchanged."""


def build_chain():
    """Wire the retriever, history-aware query rewriting, and the answer-generation chain."""
    vectorstore = get_vectorstore()
    retriever = vectorstore.as_retriever(search_kwargs={"k": settings.retriever_top_k})

    llm = ChatOpenAI(model=settings.chat_model, temperature=0.3)

    contextualize_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CONTEXTUALIZE_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ]
    )
    history_aware_retriever = create_history_aware_retriever(llm, retriever, contextualize_prompt)

    qa_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ]
    )
    document_chain = create_stuff_documents_chain(llm, qa_prompt)

    return create_retrieval_chain(history_aware_retriever, document_chain)
