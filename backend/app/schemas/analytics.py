"""
Pydantic Schemas for Phase 9: Analytics Dashboard & CSAT Metrics.
Covers Executive KPIs, First-Contact Resolution (FCR), Mean Time to Resolve (MTTR),
CSAT rating distributions, Sentiment Velocity transitions, and Agent Workload Heatmaps.
"""
from typing import List, Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field


class TimeRange(str, Enum):
    LAST_24_HOURS = "24h"
    LAST_7_DAYS = "7d"
    LAST_30_DAYS = "30d"
    LAST_90_DAYS = "90d"
    ALL_TIME = "all"


class ExecutiveKPIs(BaseModel):
    total_tickets: int = Field(..., description="Total volume of tickets within period")
    active_tickets: int = Field(..., description="Currently unresolved/open tickets")
    resolved_tickets: int = Field(..., description="Successfully resolved tickets")
    resolution_rate_pct: float = Field(..., description="Percentage of tickets resolved")
    fcr_pct: float = Field(..., description="First-Contact Resolution percentage")
    mttr_hours: float = Field(..., description="Mean Time to Resolve in hours")
    avg_csat: float = Field(..., description="Average CSAT rating on 1.0 to 5.0 scale")
    nps_score: float = Field(..., description="Calculated Net Promoter Score (-100 to +100)")
    ai_deflection_pct: float = Field(..., description="Percentage deflected by RAG & automated suggestions")
    sla_compliance_pct: float = Field(..., description="Tickets resolved within SLA target time")


class CSATRatingCount(BaseModel):
    stars: int = Field(..., ge=1, le=5)
    count: int
    percentage: float


class CSATFeedback(BaseModel):
    id: str
    ticket_code: str
    customer_name: str
    rating: int = Field(..., ge=1, le=5)
    category: str
    comment: str
    sentiment: str  # positive, neutral, negative
    created_at: str


class CSATMetrics(BaseModel):
    average_score: float
    total_surveys: int
    positive_percentage: float
    distribution: List[CSATRatingCount]
    recent_feedbacks: List[CSATFeedback]


class HourlySentiment(BaseModel):
    hour_label: str
    positive_count: int
    neutral_count: int
    frustrated_count: int


class SentimentVelocity(BaseModel):
    initial_frustrated_pct: float
    initial_neutral_pct: float
    initial_positive_pct: float
    resolved_delighted_pct: float
    resolved_satisfied_pct: float
    resolved_neutral_pct: float
    resolved_dissatisfied_pct: float
    sentiment_recovery_rate_pct: float = Field(
        ...,
        description="Percentage of initially frustrated tickets converted to satisfied/delighted on resolution"
    )
    timeline: List[HourlySentiment]


class HeatmapCell(BaseModel):
    day: str
    hour: int
    ticket_count: int
    intensity: str  # low, medium, high, peak


class AgentPerformance(BaseModel):
    agent_id: int
    name: str
    role: str
    avatar: str
    active_load: int
    resolved_tickets: int
    mttr_hours: float
    csat_score: float
    fcr_pct: float
    sla_compliance_pct: float
    status: str  # online, busy, away


class CategoryMetric(BaseModel):
    category: str
    ticket_count: int
    percentage: float
    mttr_hours: float
    csat_score: float
    sla_breach_risk: str  # low, medium, high


class DashboardOverviewResponse(BaseModel):
    time_range: str
    kpis: ExecutiveKPIs
    csat: CSATMetrics
    sentiment: SentimentVelocity
    agent_performance: List[AgentPerformance]
    category_metrics: List[CategoryMetric]
    generated_at: str


class CSATSubmitRequest(BaseModel):
    ticket_id: Optional[int] = None
    ticket_code: Optional[str] = None
    rating: int = Field(..., ge=1, le=5, description="CSAT star rating between 1 and 5")
    comment: Optional[str] = Field(None, description="Customer feedback or comment")
    customer_name: Optional[str] = Field("Customer", description="Name of submitting customer")


class CSATSubmitResponse(BaseModel):
    success: bool
    survey_id: str
    recorded_rating: int
    detected_sentiment: str
    updated_avg_csat: float
    total_surveys: int
    message: str
