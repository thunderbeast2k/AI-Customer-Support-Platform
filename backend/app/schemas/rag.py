"""
Pydantic Schemas for RAG Orchestration, Hybrid Retrieval, and LLM Usage Auditing.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class RAGCitation(BaseModel):
    document_title: str = Field(..., description="Source document title")
    chunk_id: int = Field(..., description="Database chunk primary key")
    chunk_index: int = Field(..., description="Zero-based chunk index within document")
    snippet: str = Field(..., description="Text excerpt from the verified chunk")
    relevance_score: float = Field(..., description="Hybrid similarity score (0.0 to 1.0)")


class RAGTokenUsage(BaseModel):
    prompt: int = Field(0, description="Tokens evaluated in prompt context")
    completion: int = Field(0, description="Tokens generated in model completion")
    total: int = Field(0, description="Total tokens consumed")


class RAGQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000, description="Customer or agent inquiry text")
    provider: Optional[str] = Field(None, description="Provider override: 'mock' or 'gemini'")
    top_k: int = Field(3, ge=1, le=10, description="Maximum number of context chunks to retrieve")
    threshold: float = Field(0.40, ge=0.0, le=1.0, description="Minimum similarity score required to consider evidence valid")
    conversation_id: Optional[int] = Field(None, description="Optional conversation context ID")
    ticket_id: Optional[int] = Field(None, description="Optional ticket context ID")


class RAGQueryResponse(BaseModel):
    answer: str = Field(..., description="Grounded AI response or fallback explanation")
    has_sufficient_evidence: bool = Field(..., description="Whether context chunks met threshold requirements")
    citations: List[RAGCitation] = Field(default_factory=list, description="Verifiable source citations")
    retrieved_chunks_count: int = Field(0, description="Number of passages retrieved and injected into prompt")
    model_name: str = Field(..., description="Model identifier used for generation")
    provider: str = Field(..., description="Provider adapter executed ('mock' or 'gemini')")
    tokens: RAGTokenUsage = Field(..., description="Token breakdown")
    latency_ms: float = Field(..., description="Total pipeline latency in milliseconds")


class HybridSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    top_k: int = Field(5, ge=1, le=20, description="Max passages to return")
    threshold: float = Field(0.35, ge=0.0, le=1.0, description="Score cutoff")
    document_id: Optional[int] = Field(None, description="Filter by specific document")
    vector_weight: float = Field(0.65, ge=0.0, le=1.0, description="Weight given to dense vector distance")
    keyword_weight: float = Field(0.35, ge=0.0, le=1.0, description="Weight given to sparse keyword lexical match")


class HybridChunkResult(BaseModel):
    chunk_id: int
    document_id: int
    chunk_index: int
    document_title: str
    filename: str
    content: str
    similarity_score: float
    vector_similarity: float
    keyword_rank: float


class HybridSearchResponse(BaseModel):
    query: str
    total_found: int
    results: List[HybridChunkResult]
    latency_ms: float


class LLMProviderInfo(BaseModel):
    provider: str
    model_name: str
    status: str
    is_mock: bool
    latency_ms: Optional[float] = None
    notes: Optional[str] = None


class ModelUsageRecord(BaseModel):
    id: int
    user_id: Optional[int]
    conversation_id: Optional[int]
    ticket_id: Optional[int]
    provider: str
    model_name: str
    operation: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    estimated_cost_usd: float
    created_at: datetime

    class Config:
        from_attributes = True
