"""
RAG Orchestration Service.
Coordinates hybrid retrieval, evidence thresholding, prompt compilation,
LLM provider execution, citation attribution, and model usage logging.
"""
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.audit import ModelUsage
from app.services.hybrid_retriever import hybrid_retriever
from app.services.llm.base import LLMMessage, LLMResponse
from app.services.llm.factory import get_llm_provider

SYSTEM_RAG_PROMPT = """You are an AI Customer Support Specialist for an enterprise SaaS platform.
Answer the customer's question directly and concisely based STRICTLY on the provided internal context passages.

RULES:
1. Rely ONLY on the documented facts provided in the CONTEXT PASSAGES.
2. Do not invent or assume company policies, prices, or procedures.
3. If the context does not contain sufficient information, state that clearly and offer to escalate to a human agent.
4. Maintain a helpful, empathetic, professional tone.
"""


def orchestrate_rag_response(
    db: Session,
    query: str,
    user_id: Optional[int] = None,
    conversation_id: Optional[int] = None,
    ticket_id: Optional[int] = None,
    top_k: int = 3,
    threshold: float = 0.45,
    provider_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes end-to-end RAG pipeline:
    1. Hybrid retrieval (pgvector + FTS)
    2. Evidence sufficiency evaluation
    3. Grounded prompt assembly
    4. Pluggable LLM provider execution
    5. Verifiable citation extraction
    6. Model usage audit logging
    """
    # 1. Retrieve supporting passages
    retrieved_chunks = hybrid_retriever.retrieve(
        db=db,
        query=query,
        top_k=top_k,
        threshold=threshold,
    )

    has_sufficient_evidence = len(retrieved_chunks) > 0

    # 2. Build context block
    if has_sufficient_evidence:
        context_blocks = []
        for c in retrieved_chunks:
            context_blocks.append(
                f"[Document: {c['document_title']} | Chunk #{c['chunk_index']} | Score: {c['similarity_score']}]\n{c['content']}"
            )
        context_text = "\n\n".join(context_blocks)
    else:
        context_text = "[INSUFFICIENT_EVIDENCE] No relevant passages exceeded the similarity threshold."

    # 3. Assemble prompt messages
    user_prompt = f"CUSTOMER INQUIRY:\n{query.strip()}\n\nCONTEXT PASSAGES:\n{context_text}"
    messages = [
        LLMMessage(role="system", content=SYSTEM_RAG_PROMPT),
        LLMMessage(role="user", content=user_prompt),
    ]

    # 4. Invoke LLM provider adapter
    llm = get_llm_provider(provider_override)
    llm_resp: LLMResponse = llm.generate_response(messages)

    # 5. Extract verifiable source citations
    citations = []
    if has_sufficient_evidence:
        for c in retrieved_chunks:
            citations.append({
                "document_title": c["document_title"],
                "chunk_id": c["chunk_id"],
                "chunk_index": c["chunk_index"],
                "snippet": c["content"][:200] + ("..." if len(c["content"]) > 200 else ""),
                "relevance_score": c["similarity_score"],
            })

    # 6. Record token and latency metrics in model_usage table
    try:
        estimated_cost = (llm_resp.total_tokens / 1000.0) * 0.00015
        usage = ModelUsage(
            user_id=user_id,
            conversation_id=conversation_id,
            ticket_id=ticket_id,
            provider=llm_resp.provider,
            model_name=llm_resp.model_name,
            operation="rag_response",
            prompt_tokens=llm_resp.prompt_tokens,
            completion_tokens=llm_resp.completion_tokens,
            total_tokens=llm_resp.total_tokens,
            latency_ms=llm_resp.latency_ms,
            estimated_cost_usd=round(estimated_cost, 6),
        )
        db.add(usage)
        db.commit()
    except Exception:
        db.rollback()

    return {
        "answer": llm_resp.content,
        "has_sufficient_evidence": has_sufficient_evidence,
        "citations": citations,
        "retrieved_chunks_count": len(retrieved_chunks),
        "model_name": llm_resp.model_name,
        "provider": llm_resp.provider,
        "tokens": {
            "prompt": llm_resp.prompt_tokens,
            "completion": llm_resp.completion_tokens,
            "total": llm_resp.total_tokens,
        },
        "latency_ms": llm_resp.latency_ms,
    }
