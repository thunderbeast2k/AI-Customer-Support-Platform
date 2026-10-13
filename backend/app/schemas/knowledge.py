"""
Pydantic Schemas for Knowledge Base Documents, Chunks, and Vector Search.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.models.knowledge import DocumentStatus


class DocumentChunkResponse(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    content: str
    token_count: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class KnowledgeDocumentResponse(BaseModel):
    id: int
    title: str
    filename: str
    file_type: str
    file_size_bytes: int
    content_hash: str
    status: DocumentStatus
    chunk_count: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeDocumentDetailResponse(KnowledgeDocumentResponse):
    chunks: List[DocumentChunkResponse] = []


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="Customer question or search phrase")
    top_k: int = Field(default=3, ge=1, le=20, description="Number of passages to retrieve")
    threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="Minimum cosine similarity relevance threshold")
    document_id: Optional[int] = Field(default=None, description="Optional filter to search within a specific document")


class KnowledgeSearchResultItem(BaseModel):
    document_id: int
    document_title: str
    filename: str
    chunk_id: int
    chunk_index: int
    content: str
    similarity_score: float
    distance: float


class KnowledgeSearchResponse(BaseModel):
    query: str
    top_k: int
    threshold: float
    total_matches: int
    results: List[KnowledgeSearchResultItem]
    model_name: str
    dimension: int
    latency_ms: float
