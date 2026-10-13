"""
Knowledge Service: Document Ingestion, Chunking, pgvector Storage, and Semantic Retrieval.
"""
import time
import math
from typing import Optional, List, Tuple
from sqlalchemy import desc, text
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.knowledge import KnowledgeDocument, DocumentChunk, DocumentStatus
from app.models.audit import AuditEvent
from app.services.text_extractor import extract_text_from_file, compute_sha256
from app.services.chunker import chunk_text
from app.services.embedding_service import embedding_service, EMBEDDING_DIMENSION, PINNED_MODEL_NAME
from app.schemas.knowledge import KnowledgeSearchResultItem, KnowledgeSearchResponse


def ingest_document(
    db: Session,
    filename: str,
    content_bytes: bytes,
    title: Optional[str] = None,
    current_user_id: Optional[int] = None,
) -> KnowledgeDocument:
    """
    Ingests a document:
    1. Validates file type and size
    2. Computes SHA-256 for deduplication
    3. Extracts text and normalizes content
    4. Splits text into overlapping semantic chunks
    5. Generates 384-dimensional Sentence Transformers embeddings
    6. Stores document metadata and chunks with vector embeddings in pgvector
    """
    content_hash = compute_sha256(content_bytes)

    # Duplicate check
    existing = db.query(KnowledgeDocument).filter(KnowledgeDocument.content_hash == content_hash).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A document with identical content already exists: '{existing.title}' (ID {existing.id})",
        )

    # Extract text
    raw_text = extract_text_from_file(filename=filename, content=content_bytes)
    if not raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file contains no extractable text.",
        )

    doc_title = title or filename.rsplit(".", 1)[0].replace("_", " ").title()
    file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"

    # Create document record in PROCESSING state
    doc = KnowledgeDocument(
        title=doc_title,
        filename=filename,
        file_type=file_type,
        file_size_bytes=len(content_bytes),
        content_hash=content_hash,
        status=DocumentStatus.PROCESSING,
        chunk_count=0,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        # Split into chunks (500 chars with 100 overlap)
        chunks = chunk_text(raw_text, chunk_size=500, chunk_overlap=100)

        # Batch generate embeddings
        chunk_texts = [c["content"] for c in chunks]
        embeddings = embedding_service.generate_embeddings_batch(chunk_texts)

        # Store chunks in database
        chunk_objects = []
        for i, c_data in enumerate(chunks):
            chunk_obj = DocumentChunk(
                document_id=doc.id,
                chunk_index=c_data["chunk_index"],
                content=c_data["content"],
                embedding=embeddings[i],
                token_count=c_data["token_estimate"],
                metadata_json={"char_length": c_data["char_length"]},
            )
            chunk_objects.append(chunk_obj)

        db.add_all(chunk_objects)
        doc.status = DocumentStatus.INDEXED
        doc.chunk_count = len(chunks)

        # Record audit event
        audit = AuditEvent(
            user_id=current_user_id,
            event_type="document.ingest",
            target_type="knowledge_document",
            target_id=str(doc.id),
            details={"title": doc.title, "chunks": doc.chunk_count},
        )
        db.add(audit)
        db.commit()
        db.refresh(doc)

        return doc

    except Exception as exc:
        db.rollback()
        doc.status = DocumentStatus.FAILED
        doc.error_message = str(exc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document ingestion failed: {str(exc)}",
        )


def list_documents(
    db: Session,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[int, List[KnowledgeDocument]]:
    """Lists knowledge documents with chunk totals."""
    query = db.query(KnowledgeDocument)
    total = query.count()
    items = query.order_by(desc(KnowledgeDocument.created_at)).offset(skip).limit(limit).all()
    return total, items


def get_document_or_404(db: Session, doc_id: int) -> KnowledgeDocument:
    """Fetches a document and its chunks."""
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge document with ID {doc_id} not found",
        )
    return doc


def delete_document(db: Session, doc_id: int, current_user_id: Optional[int] = None) -> None:
    """Deletes a document and cascades deletion to all chunks."""
    doc = get_document_or_404(db, doc_id)

    # Log audit event
    audit = AuditEvent(
        user_id=current_user_id,
        event_type="document.delete",
        target_type="knowledge_document",
        target_id=str(doc.id),
        details={"title": doc.title},
    )
    db.add(audit)
    db.delete(doc)
    db.commit()


def reindex_document(db: Session, doc_id: int, current_user_id: Optional[int] = None) -> KnowledgeDocument:
    """Rechunks and regenerates embeddings for all chunks of a document."""
    doc = get_document_or_404(db, doc_id)

    # Collect existing text from chunks
    existing_chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index.asc()).all()
    if not existing_chunks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No chunks found to re-index")

    full_text = "\n\n".join([c.content for c in existing_chunks])

    # Delete existing chunks
    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()

    # Re-chunk and re-embed
    chunks = chunk_text(full_text, chunk_size=500, chunk_overlap=100)
    embeddings = embedding_service.generate_embeddings_batch([c["content"] for c in chunks])

    new_chunk_objs = []
    for i, c_data in enumerate(chunks):
        new_chunk_objs.append(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=c_data["chunk_index"],
                content=c_data["content"],
                embedding=embeddings[i],
                token_count=c_data["token_estimate"],
            )
        )

    db.add_all(new_chunk_objs)
    doc.chunk_count = len(chunks)
    doc.status = DocumentStatus.INDEXED
    db.commit()
    db.refresh(doc)
    return doc


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def semantic_search(
    db: Session,
    query: str,
    top_k: int = 3,
    threshold: float = 0.5,
    document_id: Optional[int] = None,
) -> KnowledgeSearchResponse:
    """
    Performs semantic vector search:
    1. Generates 384-dimensional query embedding
    2. Executes cosine distance comparison against pgvector columns
    3. Filters by relevance threshold and returns top-k passages with citations
    """
    start_time = time.perf_counter()

    query_embedding = embedding_service.generate_embedding(query)
    results: List[KnowledgeSearchResultItem] = []

    # Check if we are running on real PostgreSQL with pgvector
    is_postgres = False
    try:
        bind = db.get_bind()
        is_postgres = "postgres" in str(bind.dialect.name).lower()
    except Exception:
        pass

    if is_postgres:
        # Use native pgvector cosine distance operator (<=>)
        vector_str = f"[{','.join(str(x) for x in query_embedding)}]"
        doc_filter_sql = "AND c.document_id = :doc_id" if document_id else ""

        sql = text(f"""
            SELECT 
                c.id AS chunk_id,
                c.document_id,
                c.chunk_index,
                c.content,
                d.title AS document_title,
                d.filename,
                (c.embedding <=> :query_vector::vector) AS distance
            FROM document_chunks c
            JOIN knowledge_documents d ON c.document_id = d.id
            WHERE c.embedding IS NOT NULL
              {doc_filter_sql}
            ORDER BY distance ASC
            LIMIT :limit
        """)

        params = {"query_vector": vector_str, "limit": top_k * 2}
        if document_id:
            params["doc_id"] = document_id

        rows = db.execute(sql, params).fetchall()

        for r in rows:
            dist = float(r.distance) if r.distance is not None else 1.0
            sim = max(0.0, 1.0 - dist)
            if sim >= threshold:
                results.append(
                    KnowledgeSearchResultItem(
                        document_id=r.document_id,
                        document_title=r.document_title,
                        filename=r.filename,
                        chunk_id=r.chunk_id,
                        chunk_index=r.chunk_index,
                        content=r.content,
                        similarity_score=round(sim, 4),
                        distance=round(dist, 4),
                    )
                )
                if len(results) >= top_k:
                    break

    else:
        # Fallback in-memory Python cosine computation (SQLite in tests or local mock)
        chunk_query = db.query(DocumentChunk, KnowledgeDocument).join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
        if document_id:
            chunk_query = chunk_query.filter(DocumentChunk.document_id == document_id)

        all_chunks = chunk_query.all()
        scored_chunks = []

        for c, d in all_chunks:
            chunk_emb = c.embedding
            if isinstance(chunk_emb, list) and len(chunk_emb) == len(query_embedding):
                sim = _cosine_similarity(query_embedding, chunk_emb)
                dist = 1.0 - sim
                if sim >= threshold:
                    scored_chunks.append((sim, dist, c, d))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        for sim, dist, c, d in scored_chunks[:top_k]:
            results.append(
                KnowledgeSearchResultItem(
                    document_id=d.id,
                    document_title=d.title,
                    filename=d.filename,
                    chunk_id=c.id,
                    chunk_index=c.chunk_index,
                    content=c.content,
                    similarity_score=round(sim, 4),
                    distance=round(dist, 4),
                )
            )

    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    return KnowledgeSearchResponse(
        query=query,
        top_k=top_k,
        threshold=threshold,
        total_matches=len(results),
        results=results,
        model_name=PINNED_MODEL_NAME,
        dimension=EMBEDDING_DIMENSION,
        latency_ms=elapsed_ms,
    )
