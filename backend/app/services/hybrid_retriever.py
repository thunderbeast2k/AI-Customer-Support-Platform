"""
Hybrid Knowledge Retrieval Service.
Combines pgvector dense semantic embeddings with PostgreSQL Full-Text Search (tsvector/tsquery)
using Reciprocal Rank Fusion (RRF) and weighted score merging.
"""
import time
import math
import re
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeDocument, DocumentChunk
from app.services.embedding_service import embedding_service
from app.services.knowledge_service import _cosine_similarity


class HybridRetriever:
    """
    Retrieves knowledge base chunks using hybrid semantic + keyword scoring.
    """

    def __init__(self, vector_weight: float = 0.65, keyword_weight: float = 0.35):
        self.vector_weight = vector_weight
        self.keyword_weight = keyword_weight

    def retrieve(
        self,
        db: Session,
        query: str,
        top_k: int = 3,
        threshold: float = 0.45,
        document_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Executes hybrid retrieval and merges dense semantic and sparse lexical rankings.
        """
        if not query or not query.strip():
            return []

        query_cleaned = query.strip()
        query_embedding = embedding_service.generate_embedding(query_cleaned)

        is_postgres = False
        try:
            bind = db.get_bind()
            is_postgres = "postgres" in str(bind.dialect.name).lower()
        except Exception:
            pass

        if is_postgres:
            # Native PostgreSQL Hybrid Search combining pgvector <=> and ts_rank_cd
            vector_str = f"[{','.join(str(x) for x in query_embedding)}]"
            doc_filter = "AND c.document_id = :doc_id" if document_id else ""

            sql = text(f"""
                WITH vector_matches AS (
                    SELECT 
                        c.id AS chunk_id,
                        c.document_id,
                        c.chunk_index,
                        c.content,
                        d.title AS document_title,
                        d.filename,
                        (1.0 - (c.embedding <=> :query_vector::vector)) AS vector_sim
                    FROM document_chunks c
                    JOIN knowledge_documents d ON c.document_id = d.id
                    WHERE c.embedding IS NOT NULL {doc_filter}
                    ORDER BY (c.embedding <=> :query_vector::vector) ASC
                    LIMIT 20
                ),
                fts_matches AS (
                    SELECT 
                        c.id AS chunk_id,
                        ts_rank_cd(to_tsvector('english', c.content), plainto_tsquery('english', :query_text)) AS fts_rank
                    FROM document_chunks c
                    WHERE to_tsvector('english', c.content) @@ plainto_tsquery('english', :query_text)
                    LIMIT 20
                )
                SELECT 
                    v.chunk_id,
                    v.document_id,
                    v.chunk_index,
                    v.content,
                    v.document_title,
                    v.filename,
                    COALESCE(v.vector_sim, 0.0) AS vector_sim,
                    COALESCE(f.fts_rank, 0.0) AS fts_rank,
                    (0.65 * COALESCE(v.vector_sim, 0.0) + 0.35 * LEAST(1.0, COALESCE(f.fts_rank, 0.0) * 2.0)) AS hybrid_score
                FROM vector_matches v
                LEFT JOIN fts_matches f ON v.chunk_id = f.chunk_id
                ORDER BY hybrid_score DESC
                LIMIT :top_k
            """)

            params = {
                "query_vector": vector_str,
                "query_text": query_cleaned,
                "top_k": top_k,
            }
            if document_id:
                params["doc_id"] = document_id

            rows = db.execute(sql, params).fetchall()

            results = []
            for r in rows:
                score = float(r.hybrid_score)
                if score >= threshold:
                    results.append({
                        "chunk_id": r.chunk_id,
                        "document_id": r.document_id,
                        "chunk_index": r.chunk_index,
                        "document_title": r.document_title,
                        "filename": r.filename,
                        "content": r.content,
                        "similarity_score": round(score, 4),
                        "vector_similarity": round(float(r.vector_sim), 4),
                        "keyword_rank": round(float(r.fts_rank), 4),
                    })
            return results

        else:
            # Fallback for SQLite / unit tests
            chunk_query = db.query(DocumentChunk, KnowledgeDocument).join(
                KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id
            )
            if document_id:
                chunk_query = chunk_query.filter(DocumentChunk.document_id == document_id)

            chunks = chunk_query.all()
            q_terms = set(re.findall(r"\w+", query_cleaned.lower()))

            scored = []
            for c, d in chunks:
                # 1. Dense vector cosine similarity
                chunk_emb = c.embedding
                vec_sim = 0.0
                if isinstance(chunk_emb, list) and len(chunk_emb) == len(query_embedding):
                    vec_sim = max(0.0, _cosine_similarity(query_embedding, chunk_emb))

                # 2. Sparse keyword matching
                c_terms = set(re.findall(r"\w+", c.content.lower()))
                overlap = len(q_terms.intersection(c_terms))
                keyword_rank = min(1.0, overlap / max(1, len(q_terms)))

                # 3. Hybrid score
                hybrid_score = (0.65 * vec_sim) + (0.35 * keyword_rank)

                if hybrid_score >= threshold:
                    scored.append({
                        "chunk_id": c.id,
                        "document_id": d.id,
                        "chunk_index": c.chunk_index,
                        "document_title": d.title,
                        "filename": d.filename,
                        "content": c.content,
                        "similarity_score": round(hybrid_score, 4),
                        "vector_similarity": round(vec_sim, 4),
                        "keyword_rank": round(keyword_rank, 4),
                    })

            scored.sort(key=lambda x: x["similarity_score"], reverse=True)
            return scored[:top_k]


hybrid_retriever = HybridRetriever()
