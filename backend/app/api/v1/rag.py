"""
RAG Orchestration, Hybrid Retrieval & LLM Provider API Endpoints.
"""
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.models.audit import ModelUsage
from app.api.deps import get_current_user, require_agent_or_admin
from app.schemas.rag import (
    RAGQueryRequest,
    RAGQueryResponse,
    RAGTokenUsage,
    RAGCitation,
    HybridSearchRequest,
    HybridSearchResponse,
    HybridChunkResult,
    LLMProviderInfo,
    ModelUsageRecord,
)
from app.services.rag_orchestrator import orchestrate_rag_response
from app.services.hybrid_retriever import hybrid_retriever, HybridRetriever
from app.services.llm.factory import get_llm_provider
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.gemini_provider import GeminiLLMProvider

router = APIRouter(prefix="/rag", tags=["RAG & Hybrid Search Engine"])


@router.post(
    "/query",
    response_model=RAGQueryResponse,
    summary="Execute Grounded RAG Query",
    description="Combines hybrid retrieval with evidence thresholding, grounded prompt assembly, LLM generation, citation extraction, and token usage tracking.",
)
def execute_rag_query(
    payload: RAGQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RAGQueryResponse:
    start_time = time.perf_counter()

    result = orchestrate_rag_response(
        db=db,
        query=payload.query,
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
        ticket_id=payload.ticket_id,
        top_k=payload.top_k,
        threshold=payload.threshold,
        provider_override=payload.provider,
    )

    citations = [
        RAGCitation(
            document_title=c["document_title"],
            chunk_id=c["chunk_id"],
            chunk_index=c.get("chunk_index", 0),
            snippet=c["snippet"],
            relevance_score=c["relevance_score"],
        )
        for c in result.get("citations", [])
    ]

    tokens_data = result.get("tokens", {})
    token_usage = RAGTokenUsage(
        prompt=tokens_data.get("prompt", 0),
        completion=tokens_data.get("completion", 0),
        total=tokens_data.get("total", 0),
    )

    return RAGQueryResponse(
        answer=result["answer"],
        has_sufficient_evidence=result["has_sufficient_evidence"],
        citations=citations,
        retrieved_chunks_count=result.get("retrieved_chunks_count", 0),
        model_name=result["model_name"],
        provider=result["provider"],
        tokens=token_usage,
        latency_ms=result.get("latency_ms", round((time.perf_counter() - start_time) * 1000.0, 2)),
    )


@router.post(
    "/hybrid-search",
    response_model=HybridSearchResponse,
    summary="Execute Hybrid Semantic + Keyword Search",
    description="Combines dense pgvector cosine distance with sparse keyword full-text search scores.",
)
def execute_hybrid_search(
    payload: HybridSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HybridSearchResponse:
    start_time = time.perf_counter()

    custom_retriever = HybridRetriever(
        vector_weight=payload.vector_weight,
        keyword_weight=payload.keyword_weight,
    )

    chunks = custom_retriever.retrieve(
        db=db,
        query=payload.query,
        top_k=payload.top_k,
        threshold=payload.threshold,
        document_id=payload.document_id,
    )

    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    results = [
        HybridChunkResult(
            chunk_id=c["chunk_id"],
            document_id=c["document_id"],
            chunk_index=c["chunk_index"],
            document_title=c["document_title"],
            filename=c["filename"],
            content=c["content"],
            similarity_score=c["similarity_score"],
            vector_similarity=c["vector_similarity"],
            keyword_rank=c["keyword_rank"],
        )
        for c in chunks
    ]

    return HybridSearchResponse(
        query=payload.query,
        total_found=len(results),
        results=results,
        latency_ms=elapsed_ms,
    )


@router.get(
    "/providers",
    response_model=List[LLMProviderInfo],
    summary="Inspect LLM Providers & Health",
    description="Returns configuration and latency health of available LLM adapters (Mock and Gemini).",
)
def list_providers(
    current_user: User = Depends(get_current_user),
) -> List[LLMProviderInfo]:
    providers_info = []

    # 1. Mock Provider
    mock_prov = MockLLMProvider()
    mock_health = mock_prov.health_check()
    providers_info.append(
        LLMProviderInfo(
            provider="mock",
            model_name=mock_prov.model_name,
            status=mock_health.get("status", "healthy"),
            is_mock=True,
            latency_ms=mock_health.get("latency_ms", 1.0),
            notes="Deterministic local mock provider. Zero external API calls, instant response.",
        )
    )

    # 2. Gemini Provider
    gemini_prov = GeminiLLMProvider()
    gemini_health = gemini_prov.health_check()
    has_gemini_key = bool(gemini_prov.api_key)
    providers_info.append(
        LLMProviderInfo(
            provider="gemini",
            model_name=gemini_prov.model_name,
            status=gemini_health.get("status", "missing_key"),
            is_mock=False,
            latency_ms=gemini_health.get("latency_ms"),
            notes="Google Gemini 1.5 / 2.0 Flash integration. "
            + ("Ready for queries." if has_gemini_key else "Requires LLM_API_KEY environment variable."),
        )
    )

    return providers_info


@router.get(
    "/usage",
    response_model=List[ModelUsageRecord],
    summary="Query Token Usage & Latency Audit Logs",
    description="Returns recent model invocations, token counts, latencies, and estimated USD costs.",
)
def get_usage_audit_logs(
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_agent_or_admin),
) -> List[ModelUsageRecord]:
    logs = (
        db.query(ModelUsage)
        .order_by(desc(ModelUsage.created_at))
        .limit(limit)
        .all()
    )
    return [ModelUsageRecord.model_validate(log) for log in logs]
