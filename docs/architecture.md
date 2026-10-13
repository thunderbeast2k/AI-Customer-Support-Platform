# Architecture and Technology Blueprint

## Project: AI Customer Support Platform
**Version:** 1.0.0 (Phase 1 Baseline)  
**System Architecture:** Modular Monolith with Decoupled AI Orchestration

---

## 1. High-Level Architecture Overview

The platform is designed as an enterprise-grade AI customer support and ticket management system. Rather than coupling generative AI and classification directly into API endpoints, the application separates request intake, deterministic business logic, traditional machine learning, vector retrieval, and generative LLM integration.

```
                              +-------------------------+
                              |      Web Frontend       |
                              |   React + TypeScript    |
                              |   Vite + Tailwind CSS   |
                              +------------+------------+
                                           | REST / HTTPS
                                           v
                              +-------------------------+
                              |       FastAPI App       |
                              |  (Modular Monolith API) |
                              +------------+------------+
                                           |
                 +-------------------------+-------------------------+
                 |                                                   |
                 v                                                   v
     +-----------------------+                           +-----------------------+
     |   Authentication &    |                           |    AI Orchestration   |
     | Role-Based Access     |                           |        Engine         |
     | (Admin/Agent/Customer)|                           +-----------+-----------+
     +-----------------------+                                       |
                                                                     |
         +-----------------------------------+-----------------------+-----------------------+
         |                                   |                                               |
         v                                   v                                               v
+------------------+                +------------------+                           +------------------+
|  scikit-learn    |                | Sentence         |                           | Hosted LLM       |
|  Classification  |                | Transformers     |                           | Provider Adapter |
|  - TF-IDF        |                | - all-MiniLM-L6  |                           | - Gemini / OpenAI|
|  - LogReg Model  |                | - 384d Vectors   |                           | - Mock Adapter   |
+------------------+                +--------+---------+                           +------------------+
                                             |
                                             v
                                +--------------------------+
                                |  PostgreSQL 16 + pgvector|
                                |  - Relational Data       |
                                |  - Full-Text Search (ts) |
                                |  - Cosine / L2 Vectors   |
                                +--------------------------+
```

---

## 2. Technology Choices & Technical Rationale

| Component | Technology | Rationale |
| :--- | :--- | :--- |
| **Backend Framework** | FastAPI (Python 3.12) | Asynchronous capabilities, native OpenAPI generation, automatic Pydantic validation, and high performance. |
| **Relational Database** | PostgreSQL 16 | ACID transactions, robust foreign keys, relational integrity for users, conversations, and tickets. |
| **Vector Search** | pgvector extension | Eliminates the operational complexity of maintaining an external vector database (e.g. Pinecone/Milvus) during early and mid scale. |
| **Keyword Search** | PostgreSQL tsvector & tsquery | Native hybrid search combining BM25-like full-text keyword ranking with dense vector similarity. |
| **Machine Learning** | scikit-learn | Lightweight, explainable, reproducible TF-IDF + Logistic Regression classification without heavy GPU or deep-learning overhead. |
| **Dense Embeddings** | Sentence Transformers (`all-MiniLM-L6-v2`) | Compact (384-dimensional), fast CPU inference (<15ms per chunk), high semantic quality. |
| **Generative LLM** | Provider-Agnostic Adapter Pattern | Isolates the platform from vendor lock-in. Default mock provider allows tests and development without API key expenses. |
| **Frontend Framework** | React 19 + TypeScript + Vite | Rapid compile times, strict type safety, responsive component lifecycle. |
| **UI Design System** | Tailwind CSS + Lucide Icons | Clean modern enterprise design system with accessible contrast, responsive breakpoints, and clear states. |

---

## 3. Directory Layout (Modular Monolith)

```
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── __init__.py
│   │   │   │   └── health.py          # Operational & readiness probes
│   │   │   └── __init__.py
│   │   ├── core/
│   │   │   ├── config.py              # Pydantic Settings
│   │   │   ├── database.py            # SQLAlchemy 2.0 & pgvector connection
│   │   │   └── logging.py             # Structured JSON logging
│   │   ├── schemas/
│   │   │   ├── health.py              # Status & health response schemas
│   │   │   └── __init__.py
│   │   ├── ml/                        # (Phase 7) scikit-learn models & artifacts
│   │   ├── services/                  # (Phase 5/6) RAG and AI Orchestration
│   │   └── main.py                    # Application entrypoint & middleware
│   ├── scripts/
│   │   └── verify_phase1.py           # Verification and diagnostics
│   ├── tests/
│   │   ├── __init__.py
│   │   └── test_health.py             # Pytest test suite
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── src/                               # Frontend React Application
│   ├── components/                    # Reusable UI widgets
│   ├── App.tsx                        # Interactive Phase 1 Console & Dashboard
│   └── main.tsx
├── docs/
│   └── architecture.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── package.json
└── README.md
```

---

## 4. Phase Roadmap

- **Phase 1 (Current):** Architecture, Docker Compose, PostgreSQL + pgvector configuration, FastAPI modular baseline, health/readiness probes, and interactive management console.
- **Phase 2:** Database models (Users, Conversations, Tickets, Chunks), Alembic migrations, JWT Auth & RBAC (Admin, Agent, Customer), seed scripts.
- **Phase 3:** Support ticket management API (CRUD, status transitions, private notes, assignments).
- **Phase 4:** Customer conversation API, message persistence, real-time message stream.
- **Phase 5:** Knowledge base ingestion (PDF, TXT, MD), text chunking, Sentence Transformers embeddings, pgvector storage.
- **Phase 6:** Hybrid search (vector + tsvector), LLM adapter (Gemini/OpenAI/mock), grounded answer generation, source attribution.
- **Phase 7:** scikit-learn ticket classification pipeline (TF-IDF + Logistic Regression, evaluation metrics, confusion matrix, inference API).
- **Phase 8:** Agent and Admin analytics dashboards with real aggregated metrics.
- **Phase 9:** Security audit, automated tests (pytest + httpx), rate limiting, prompt-injection defenses.
- **Phase 10:** Production deployment, final end-to-end verification, and portfolio presentation.
