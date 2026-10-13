"""
Machine Learning Ticket Categorization & Automated Triage Endpoints (Phase 7).
Provides prediction, confidence calibration, automated triage on database tickets,
model retraining with historical tickets, explainability, and evaluation metrics.
"""
from datetime import datetime, timezone
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User, UserRole
from app.models.ticket import Ticket, TicketActivity, TicketCategory, TicketPriority
from app.models.audit import AuditEvent, ModelUsage
from app.api.deps import get_current_user, require_agent_or_admin
from app.schemas.ml import (
    TicketClassificationRequest,
    TicketClassificationResponse,
    TriageTicketRequest,
    TriageTicketResponse,
    ModelMetricsResponse,
    ModelRetrainRequest,
    ModelRetrainResponse,
    ExplainClassificationRequest,
    ExplainClassificationResponse,
)
from app.services.ticket_classifier import classifier_engine, SEED_TRAINING_DATA

router = APIRouter(prefix="/ml", tags=["Machine Learning Ticket Categorization"])


@router.post(
    "/predict",
    response_model=TicketClassificationResponse,
    summary="Classify Ticket Text",
    description="Runs TF-IDF feature extraction and Logistic Regression inference to predict category and priority with confidence calibration.",
)
def predict_ticket(
    payload: TicketClassificationRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
) -> TicketClassificationResponse:
    """Infers ticket category and priority for given subject and body."""
    res = classifier_engine.predict(
        title=payload.title,
        description=payload.description,
        confidence_threshold=payload.confidence_threshold or 0.55,
    )

    # Record model usage telemetry
    try:
        user_id = current_user.id if current_user else None
        usage = ModelUsage(
            user_id=user_id,
            provider="scikit-learn" if classifier_engine.is_sklearn_active else "pure-python-tfidf",
            model_name=res.model_version,
            operation="ticket_categorization",
            prompt_tokens=len(payload.title.split()) + len(payload.description.split()),
            completion_tokens=len(res.category_probabilities),
            total_tokens=len(payload.title.split()) + len(payload.description.split()) + 7,
            latency_ms=res.inference_latency_ms,
            estimated_cost_usd=0.0,  # Zero-cost local inference
        )
        db.add(usage)
        db.commit()
    except Exception:
        db.rollback()

    return res


@router.post(
    "/triage-ticket/{ticket_id}",
    response_model=TriageTicketResponse,
    summary="Auto-Triage Existing Ticket",
    description="Runs ML inference on a stored ticket, applies predictions if confidence threshold is met, and records an activity audit event.",
)
def triage_ticket_endpoint(
    ticket_id: int,
    payload: TriageTicketRequest = TriageTicketRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_agent_or_admin),
) -> TriageTicketResponse:
    """Auto-triages a database ticket using the ML classifier."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket {ticket_id} not found",
        )

    prediction = classifier_engine.predict(
        title=ticket.title,
        description=ticket.description,
        confidence_threshold=payload.confidence_threshold or 0.55,
    )

    applied_cat = None
    applied_prio = None
    activity_id = None
    needs_review = not prediction.is_confident

    if prediction.is_confident and payload.auto_apply:
        applied_cat = prediction.predicted_category
        applied_prio = prediction.predicted_priority

        old_cat = ticket.category.value
        old_prio = ticket.priority.value

        ticket.category = applied_cat
        ticket.priority = applied_prio
        ticket.category_confidence = prediction.confidence_score

        activity = TicketActivity(
            ticket_id=ticket.id,
            author_id=current_user.id,
            activity_type="ml_triage",
            old_value=f"cat:{old_cat}|prio:{old_prio}",
            new_value=f"cat:{applied_cat.value}|prio:{applied_prio.value}",
            note=(
                f"Automated ML Triage applied: Categorized as '{applied_cat.value}' "
                f"with {prediction.confidence_score:.1%} confidence (priority: '{applied_prio.value}')."
            ),
            is_internal=True,
        )
        db.add(activity)

        audit = AuditEvent(
            user_id=current_user.id,
            event_type="ticket.ml_triage",
            target_type="ticket",
            target_id=str(ticket.id),
            details={
                "ticket_code": ticket.ticket_code,
                "category": applied_cat.value,
                "priority": applied_prio.value,
                "confidence": prediction.confidence_score,
            },
        )
        db.add(audit)
        db.commit()
        db.refresh(activity)
        activity_id = activity.id
        msg = f"Ticket successfully auto-triaged to {applied_cat.value} ({prediction.confidence_score:.1%} confidence)."
    else:
        # Record review recommendation
        ticket.category_confidence = prediction.confidence_score
        activity = TicketActivity(
            ticket_id=ticket.id,
            author_id=current_user.id,
            activity_type="ml_triage_review",
            old_value=None,
            new_value="needs_human_review",
            note=(
                f"ML Triage evaluated: Top prediction '{prediction.predicted_category.value}' "
                f"had {prediction.confidence_score:.1%} confidence (below threshold {payload.confidence_threshold}). "
                f"Flagged for manual agent triage."
            ),
            is_internal=True,
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)
        activity_id = activity.id
        msg = f"Confidence {prediction.confidence_score:.1%} is below threshold. Flagged for human review."

    return TriageTicketResponse(
        ticket_id=ticket.id,
        ticket_code=ticket.ticket_code,
        applied_category=applied_cat,
        applied_priority=applied_prio,
        confidence=prediction.confidence_score,
        needs_human_review=needs_review,
        activity_id=activity_id,
        message=msg,
    )


@router.get(
    "/metrics",
    response_model=ModelMetricsResponse,
    summary="Get Model Status & Metrics",
    description="Returns current ML model metadata, evaluation accuracy, vocabulary size, and training sample distributions.",
)
def get_metrics() -> ModelMetricsResponse:
    """Returns model health, accuracy, and vocabulary statistics."""
    return classifier_engine.get_metrics()


@router.post(
    "/retrain",
    response_model=ModelRetrainResponse,
    summary="Retrain Classifier",
    description="Retrains TF-IDF vectorizer and Logistic Regression models on seed dataset plus historical tickets in the database.",
)
def retrain_model(
    payload: ModelRetrainRequest = ModelRetrainRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_agent_or_admin),
) -> ModelRetrainResponse:
    """Retrains the classification pipeline."""
    combined_data = list(SEED_TRAINING_DATA)

    if payload.include_db_tickets:
        db_tickets = db.query(Ticket).all()
        for t in db_tickets:
            combined_data.append({
                "text": f"{t.title} {t.description}",
                "category": t.category.value,
                "priority": t.priority.value,
            })

    result = classifier_engine.fit(combined_data)

    class_dist = {}
    for d in combined_data:
        c = d["category"]
        class_dist[c] = class_dist.get(c, 0) + 1

    # Audit event
    try:
        audit = AuditEvent(
            user_id=current_user.id,
            event_type="ml.retrain",
            target_type="ml_model",
            target_id="ticket_classifier",
            details={
                "samples_trained": result["samples"],
                "vocab_size": result["vocab_size"],
                "duration_ms": result["duration_ms"],
            },
        )
        db.add(audit)
        db.commit()
    except Exception:
        db.rollback()

    return ModelRetrainResponse(
        success=True,
        samples_trained=result["samples"],
        vocabulary_size=result["vocab_size"],
        accuracy=result["accuracy"],
        duration_ms=result["duration_ms"],
        class_distribution=class_dist,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post(
    "/explain",
    response_model=ExplainClassificationResponse,
    summary="Explain Prediction Signals",
    description="Returns top salient TF-IDF feature weights and tokens driving classification decisions.",
)
def explain_text(payload: ExplainClassificationRequest) -> ExplainClassificationResponse:
    """Analyzes text and returns feature importance weights per category."""
    return classifier_engine.explain(payload.text, top_n=payload.top_n_features)


@router.get(
    "/samples",
    summary="Get Test Scenarios",
    description="Returns pre-built domain test prompts covering high-confidence and edge-case tickets.",
)
def get_sample_prompts():
    """Provides sample tickets for interactive playground evaluation."""
    return [
        {
            "id": "sample-billing",
            "title": "Duplicate charge on Visa ending 4040",
            "description": "I noticed two identical charges of $149.00 on my credit card statement for renewal invoice INV-2024-889. Please remove the second transaction and refund my account.",
            "expected_category": "billing",
            "expected_priority": "high",
        },
        {
            "id": "sample-tech",
            "title": "PostgreSQL database connection pool exhausted in production",
            "description": "Our application servers are returning 500 Internal Server Error and 504 Gateway Timeout. The logs show 'remaining connection slots are reserved for non-replication superuser connections'. Services are completely down.",
            "expected_category": "technical_issue",
            "expected_priority": "urgent",
        },
        {
            "id": "sample-account",
            "title": "Locked out after losing 2FA phone",
            "description": "I got a new mobile device and no longer have access to my Google Authenticator app for two-factor authentication. I cannot log into my admin dashboard.",
            "expected_category": "account_access",
            "expected_priority": "high",
        },
        {
            "id": "sample-refund",
            "title": "Requesting refund under 30-day money-back guarantee",
            "description": "I purchased the annual Pro subscription three days ago, but our company decided to go another direction. Please cancel the subscription and issue a full refund to my card.",
            "expected_category": "refund_request",
            "expected_priority": "medium",
        },
        {
            "id": "sample-order",
            "title": "Tracking status not updating for order ORD-9921",
            "description": "My package was shipped 6 days ago via courier tracking number 9400111202556784920, but the status is stuck at 'Label Created'. Can you check the delivery status?",
            "expected_category": "order_status",
            "expected_priority": "medium",
        },
        {
            "id": "sample-inquiry",
            "title": "Does the Enterprise plan support SAML Okta SSO?",
            "description": "We are evaluating your software for a 500-seat deployment. Does the platform integrate with Okta SAML 2.0 and offer custom RBAC role definitions?",
            "expected_category": "product_inquiry",
            "expected_priority": "low",
        },
    ]
