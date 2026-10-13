"""
Knowledge Base Management & Semantic Vector Search API Endpoints.
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeDocumentResponse,
    KnowledgeDocumentDetailResponse,
    DocumentChunkResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.api.deps import get_current_user, require_agent_or_admin
from app.services import knowledge_service

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base & Semantic Vector Search"])


@router.post(
    "/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload & Ingest Knowledge Document",
    description="Uploads a PDF, TXT, or Markdown document, chunks content, generates Sentence Transformers embeddings, and indexes into pgvector.",
)
async def upload_document(
    file: UploadFile = File(..., description="Document file (.pdf, .txt, .md)"),
    title: Optional[str] = Form(None, description="Optional custom document title"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_agent_or_admin),
) -> KnowledgeDocumentResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    doc = knowledge_service.ingest_document(
        db=db,
        filename=file.filename or "uploaded_document.txt",
        content_bytes=content,
        title=title,
        current_user_id=current_user.id,
    )
    return KnowledgeDocumentResponse.model_validate(doc)


@router.get(
    "/documents",
    response_model=List[KnowledgeDocumentResponse],
    summary="List Knowledge Documents",
    description="Returns all uploaded knowledge documents with chunk counts and ingestion status.",
)
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[KnowledgeDocumentResponse]:
    _, items = knowledge_service.list_documents(db=db, skip=skip, limit=limit)
    return [KnowledgeDocumentResponse.model_validate(d) for d in items]


@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentDetailResponse,
    summary="Get Document Chunks & Metadata",
    description="Returns complete document metadata and all chunked passages.",
)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDocumentDetailResponse:
    doc = knowledge_service.get_document_or_404(db=db, doc_id=document_id)
    chunks = [DocumentChunkResponse.model_validate(c) for c in doc.chunks]

    response = KnowledgeDocumentDetailResponse.model_validate(doc)
    response.chunks = chunks
    return response


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Knowledge Document",
    description="Permanently deletes a knowledge document and cascades deletion to all vector chunks in pgvector.",
)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_agent_or_admin),
):
    knowledge_service.delete_document(db=db, doc_id=document_id, current_user_id=current_user.id)
    return {"message": f"Knowledge document #{document_id} and all associated vector chunks deleted successfully."}


@router.post(
    "/documents/{document_id}/reindex",
    response_model=KnowledgeDocumentResponse,
    summary="Re-index Document",
    description="Re-chunks text and regenerates Sentence Transformers dense embeddings.",
)
def reindex_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_agent_or_admin),
) -> KnowledgeDocumentResponse:
    doc = knowledge_service.reindex_document(db=db, doc_id=document_id, current_user_id=current_user.id)
    return KnowledgeDocumentResponse.model_validate(doc)


@router.post(
    "/search",
    response_model=KnowledgeSearchResponse,
    summary="Semantic Vector Search (pgvector)",
    description="Converts customer query to 384-dimensional vector and executes pgvector cosine similarity search with score thresholding.",
)
def search_knowledge(
    payload: KnowledgeSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeSearchResponse:
    return knowledge_service.semantic_search(
        db=db,
        query=payload.query,
        top_k=payload.top_k,
        threshold=payload.threshold,
        document_id=payload.document_id,
    )
