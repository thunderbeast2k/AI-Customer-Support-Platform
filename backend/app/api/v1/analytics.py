"""
FastAPI Router for Phase 9: Analytics Dashboard & CSAT Metrics.
Exposes endpoints for Executive KPIs, CSAT surveys, Sentiment Velocity,
Agent Workload Heatmaps, and Category Resolution breakdown.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.analytics import (
    TimeRange,
    DashboardOverviewResponse,
    CSATMetrics,
    CSATSubmitRequest,
    CSATSubmitResponse,
    SentimentVelocity,
    HeatmapCell,
    AgentPerformance,
    CategoryMetric,
)
from app.services.analytics_service import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/dashboard",
    response_model=DashboardOverviewResponse,
    summary="Get complete Executive KPIs and CSAT Dashboard Overview",
)
def get_dashboard_overview(
    time_range: TimeRange = Query(TimeRange.LAST_7_DAYS, description="Time filter window"),
    db: Session = Depends(get_db)
):
    """
    Returns executive metrics including First-Contact Resolution (FCR),
    Mean Time to Resolve (MTTR), CSAT distributions, and sentiment shifts.
    """
    return analytics_service.get_dashboard_overview(time_range=time_range, db=db)


@router.get(
    "/csat",
    response_model=CSATMetrics,
    summary="Get CSAT metrics, star distribution, and verified feedback",
)
def get_csat_metrics():
    """
    Returns 5-to-1 star ratings distribution, average score, and recent customer reviews.
    """
    return analytics_service.get_csat_metrics()


@router.post(
    "/csat",
    response_model=CSATSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit customer satisfaction survey response",
)
def submit_csat_survey(req: CSATSubmitRequest):
    """
    Records a CSAT rating (1-5 stars) and optional written comments,
    automatically analyzing sentiment and updating platform metrics.
    """
    return analytics_service.submit_csat(req)


@router.get(
    "/sentiment-velocity",
    response_model=SentimentVelocity,
    summary="Get Sentiment Velocity and recovery tracking",
)
def get_sentiment_velocity(
    time_range: TimeRange = Query(TimeRange.LAST_7_DAYS, description="Time filter window")
):
    """
    Returns incoming customer sentiment vs post-resolution converted sentiment metrics.
    """
    return analytics_service.get_sentiment_velocity(time_range=time_range)


@router.get(
    "/heatmap",
    response_model=List[HeatmapCell],
    summary="Get 2D agent workload arrival heatmap",
)
def get_agent_workload_heatmap():
    """
    Returns Day-of-Week x Hour arrival density matrix for staffing and scheduling optimization.
    """
    return analytics_service.get_agent_workload_heatmap()


@router.get(
    "/agents",
    response_model=List[AgentPerformance],
    summary="Get agent performance and workload leaderboard",
)
def get_agent_performance():
    """
    Returns per-agent caseload, MTTR, CSAT, and FCR metrics.
    """
    return analytics_service.get_agent_performance()


@router.get(
    "/categories",
    response_model=List[CategoryMetric],
    summary="Get ticket category resolution speed and breach risk",
)
def get_category_metrics(
    total_tickets: int = Query(142, ge=1, description="Base ticket count for calculation")
):
    """
    Returns category breakdown with MTTR, CSAT, and SLA breach risk.
    """
    return analytics_service.get_category_metrics(total_tickets=total_tickets)
