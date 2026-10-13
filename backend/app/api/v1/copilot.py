"""
FastAPI Router for Agent Response Co-Pilot & Quick Replies (Phase 8).
Exposes endpoints for generative draft creation, tone refinement, thread summarization,
and canned response template macros.
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.ticket import Ticket, TicketActivity, TicketStatus
from app.services.copilot_service import copilot_service
from app.schemas.copilot import (
    DraftRequest,
    DraftResponse,
    RefineRequest,
    RefineResponse,
    SummarizeRequest,
    SummarizeResponse,
    QuickReplyTemplate,
    TemplateCreate,
    TemplateInterpolateRequest,
    TemplateInterpolateResponse,
    CopilotTone,
)

router = APIRouter(prefix="/copilot", tags=["Agent Response Co-Pilot (Phase 8)"])


@router.get("/tones", response_model=List[Dict[str, Any]])
def get_supported_tones():
    """Returns available tone personas with descriptions and styling cues."""
    return [
        {
            "tone": CopilotTone.PROFESSIONAL.value,
            "label": "Professional",
            "description": "Clear, courteous, articulate enterprise tone. Authoritative and respectful.",
            "badge_color": "indigo",
            "sample_opener": "Dear Valued Customer, Thank you for contacting our support desk.",
        },
        {
            "tone": CopilotTone.EMPATHETIC.value,
            "label": "Empathetic",
            "description": "Warm, reassuring, validating user frustration with sincere understanding.",
            "badge_color": "rose",
            "sample_opener": "Hello! I am truly sorry to hear that you are encountering this disruption.",
        },
        {
            "tone": CopilotTone.CONCISE.value,
            "label": "Concise",
            "description": "Zero fluff, action-oriented, direct answers and clear next steps.",
            "badge_color": "amber",
            "sample_opener": "Hi. Here are the immediate steps to resolve your inquiry:",
        },
        {
            "tone": CopilotTone.TECHNICAL.value,
            "label": "Technical",
            "description": "Diagnostic-focused, CLI/API syntax, root cause analysis, and log checks.",
            "badge_color": "cyan",
            "sample_opener": "Diagnostic review: Let us examine the endpoint status and trace logs.",
        },
        {
            "tone": CopilotTone.FRIENDLY.value,
            "label": "Friendly",
            "description": "Casual, approachable, upbeat, and enthusiastic communication.",
            "badge_color": "emerald",
            "sample_opener": "Hey there! Thanks so much for reaching out today—happy to help!",
        },
    ]


@router.post("/draft", response_model=DraftResponse)
def draft_reply(
    data: DraftRequest,
    db: Session = Depends(get_db),
):
    """
    Drafts an agent reply based on ticket context, tone, length, and optional KB grounding.
    """
    # If ticket_id is provided, augment context if missing
    if data.ticket_id:
        ticket = db.query(Ticket).filter(Ticket.id == data.ticket_id).first()
        if ticket:
            if not data.title:
                data.title = ticket.title
            if not data.description:
                data.description = ticket.description
            if not data.ticket_code:
                data.ticket_code = ticket.ticket_code
            if hasattr(ticket, "customer") and ticket.customer and data.customer_name == "Valued Customer":
                data.customer_name = ticket.customer.full_name or ticket.customer.email

    try:
        response = copilot_service.draft_reply(db=db, data=data)
        return response
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Co-Pilot response generation failed: {str(exc)}",
        )


@router.post("/refine", response_model=RefineResponse)
def refine_draft(
    data: RefineRequest,
    db: Session = Depends(get_db),
):
    """
    Refines an existing draft reply with specific tone shifts, bulletization, or grammar polishing.
    """
    if not data.draft_text.strip():
        raise HTTPException(status_code=400, detail="draft_text cannot be empty.")
    try:
        response = copilot_service.refine_draft(db=db, data=data)
        return response
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Draft refinement failed: {str(exc)}",
        )


@router.post("/summarize", response_model=SummarizeResponse)
def summarize_thread(
    data: SummarizeRequest,
    db: Session = Depends(get_db),
):
    """
    Generates a structured internal handover note summarizing ticket conversation thread.
    """
    if data.ticket_id and not data.title:
        ticket = db.query(Ticket).filter(Ticket.id == data.ticket_id).first()
        if ticket:
            data.title = ticket.title
            data.description = ticket.description

    try:
        response = copilot_service.summarize_thread(db=db, data=data)
        return response
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Thread summarization failed: {str(exc)}",
        )


@router.get("/templates", response_model=List[QuickReplyTemplate])
def list_templates(
    category: Optional[str] = Query(default=None, description="Filter by category"),
    search: Optional[str] = Query(default=None, description="Search keyword in title or content"),
):
    """Lists available canned response quick reply macros."""
    return copilot_service.list_templates(category=category, search=search)


@router.post("/templates", response_model=QuickReplyTemplate, status_code=status.HTTP_201_CREATED)
def create_template(data: TemplateCreate):
    """Creates a custom canned quick reply macro."""
    return copilot_service.create_template(data=data)


@router.get("/templates/{template_id}", response_model=QuickReplyTemplate)
def get_template(template_id: str):
    """Retrieves a specific canned response template by ID."""
    tpl = copilot_service.get_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    return tpl


@router.post("/templates/{template_id}/interpolate", response_model=TemplateInterpolateResponse)
def interpolate_template(
    template_id: str,
    payload: TemplateInterpolateRequest,
    db: Session = Depends(get_db),
):
    """Interpolates template placeholder tokens with ticket and agent details."""
    tpl = copilot_service.get_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")

    ticket = None
    if payload.ticket_id:
        ticket = db.query(Ticket).filter(Ticket.id == payload.ticket_id).first()

    result = copilot_service.interpolate_template(
        template_id=template_id,
        ticket=ticket,
        custom_vars=payload.custom_variables,
    )

    return TemplateInterpolateResponse(
        template_id=template_id,
        interpolated_content=result["interpolated_content"],
        applied_variables=result["applied_variables"],
    )


@router.post("/apply-to-ticket/{ticket_id}")
def apply_reply_to_ticket(
    ticket_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Inserts a co-pilot generated reply or internal note directly into the ticket activities
    and updates the ticket lifecycle state.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")

    reply_content = payload.get("reply_content", "").strip()
    if not reply_content:
        raise HTTPException(status_code=400, detail="reply_content cannot be empty.")

    is_internal = payload.get("is_internal", False)
    new_status = payload.get("new_status")

    # Update ticket status if provided
    if new_status and hasattr(TicketStatus, new_status.upper()):
        ticket.status = getattr(TicketStatus, new_status.upper())

    ticket.ai_suggested_response = reply_content

    activity = TicketActivity(
        ticket_id=ticket.id,
        author_id=ticket.assigned_agent_id or ticket.customer_id,
        activity_type="copilot_reply" if not is_internal else "internal_note",
        note=reply_content,
        is_internal=is_internal,
    )
    db.add(activity)
    db.commit()
    db.refresh(ticket)

    return {
        "success": True,
        "ticket_id": ticket.id,
        "ticket_code": ticket.ticket_code,
        "status": ticket.status.value,
        "activity_id": activity.id,
        "message": "Co-Pilot response successfully saved to ticket history.",
    }
