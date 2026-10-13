"""
Pydantic Schemas for Machine Learning Ticket Categorization & Automated Triage (Phase 7).
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from app.models.ticket import TicketCategory, TicketPriority


class CategoryProbability(BaseModel):
    category: TicketCategory
    probability: float = Field(..., description="Calibrated confidence score between 0.0 and 1.0")


class PriorityProbability(BaseModel):
    priority: TicketPriority
    probability: float = Field(..., description="Calibrated confidence score between 0.0 and 1.0")


class FeatureContribution(BaseModel):
    feature: str = Field(..., description="N-gram or word token extracted by TF-IDF")
    weight: float = Field(..., description="Log-odds or TF-IDF contribution weight to prediction")
    category: Optional[str] = None


class TicketClassificationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Ticket title or subject")
    description: str = Field(..., min_length=1, description="Ticket body, logs, or customer issue description")
    confidence_threshold: Optional[float] = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Minimum probability required before accepting prediction without human review",
    )


class TicketClassificationResponse(BaseModel):
    predicted_category: TicketCategory
    confidence_score: float = Field(..., description="Top category probability")
    is_confident: bool = Field(..., description="Whether confidence exceeds threshold")
    predicted_priority: TicketPriority
    priority_confidence: float = Field(..., description="Top priority probability")
    category_probabilities: List[CategoryProbability]
    priority_probabilities: List[PriorityProbability]
    top_features: List[FeatureContribution] = Field(default_factory=list)
    inference_latency_ms: float
    model_version: str
    fallback_applied: bool = False
    recommended_action: str = Field(
        ...,
        description="'auto_triage' if confidence is above threshold, else 'manual_review_required'",
    )


class TriageTicketRequest(BaseModel):
    auto_apply: bool = Field(
        default=True,
        description="Whether to commit predicted category and priority to the database if confident",
    )
    confidence_threshold: Optional[float] = Field(default=0.55, ge=0.0, le=1.0)


class TriageTicketResponse(BaseModel):
    ticket_id: int
    ticket_code: str
    applied_category: Optional[TicketCategory] = None
    applied_priority: Optional[TicketPriority] = None
    confidence: float
    needs_human_review: bool
    activity_id: Optional[int] = None
    message: str


class ModelMetricsResponse(BaseModel):
    status: str
    model_version: str
    last_trained_at: Optional[str] = None
    sample_count: int
    vocabulary_size: int
    categories: List[str]
    priorities: List[str]
    evaluation_accuracy: float
    macro_f1: float
    is_using_sklearn: bool
    category_distribution: Dict[str, int] = Field(default_factory=dict)


class ModelRetrainRequest(BaseModel):
    include_db_tickets: bool = Field(
        default=True,
        description="Merge existing resolved/triaged tickets in the database with the seed training set",
    )


class ModelRetrainResponse(BaseModel):
    success: bool
    samples_trained: int
    vocabulary_size: int
    accuracy: float
    duration_ms: float
    class_distribution: Dict[str, int]
    timestamp: str


class ExplainClassificationRequest(BaseModel):
    text: str = Field(..., min_length=2, description="Text to analyze salient n-gram signals for")
    top_n_features: int = Field(default=5, ge=1, le=20)


class ExplainClassificationResponse(BaseModel):
    tokens_analyzed: List[str]
    category_explanations: Dict[str, List[FeatureContribution]]
