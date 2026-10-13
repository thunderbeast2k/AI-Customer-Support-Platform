"""
API v1 Router Package.
Consolidates and registers all versioned v1 sub-routers.
"""
from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.tickets import router as tickets_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.rag import router as rag_router
from app.api.v1.ml import router as ml_router
from app.api.v1.copilot import router as copilot_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.webhooks import router as webhooks_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(tickets_router)
api_v1_router.include_router(conversations_router)
api_v1_router.include_router(knowledge_router)
api_v1_router.include_router(rag_router)
api_v1_router.include_router(ml_router)
api_v1_router.include_router(copilot_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(webhooks_router)

__all__ = ["api_v1_router"]
