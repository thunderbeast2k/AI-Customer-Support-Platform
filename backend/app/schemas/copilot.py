"""
Pydantic Schemas for Agent Response Co-Pilot & Quick Replies (Phase 8).
Covers drafting, tones, tone refinement, thread summarization, and canned template macros.
"""
from typing import List, Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field


class CopilotTone(str, Enum):
    PROFESSIONAL = "professional"
    EMPATHETIC = "empathetic"
    CONCISE = "concise"
    TECHNICAL = "technical"
    FRIENDLY = "friendly"


class CopilotLength(str, Enum):
    BRIEF = "brief"
    STANDARD = "standard"
    DETAILED = "detailed"


class RefinementAction(str, Enum):
    MORE_EMPATHETIC = "more_empathetic"
    MORE_CONCISE = "more_concise"
    BULLETIZE = "bulletize"
    FIX_GRAMMAR = "fix_grammar"
    TECHNICAL_DEPTH = "technical_depth"


class DraftRequest(BaseModel):
    ticket_id: Optional[int] = Field(default=None, description="Optional ticket database ID for auto context")
    ticket_code: Optional[str] = Field(default=None, description="Optional ticket human-readable code e.g. TIK-2026-1001")
    title: str = Field(..., description="Ticket issue title or subject")
    description: str = Field(..., description="Ticket problem description or customer message")
    customer_name: Optional[str] = Field(default="Valued Customer", description="Customer full name")
    customer_email: Optional[str] = Field(default=None, description="Customer contact email")
    category: Optional[str] = Field(default="general_inquiry", description="Ticket categorized topic")
    priority: Optional[str] = Field(default="medium", description="Ticket priority level")
    status: Optional[str] = Field(default="open", description="Current ticket lifecycle status")
    tone: CopilotTone = Field(default=CopilotTone.PROFESSIONAL, description="Desired response persona tone")
    length: CopilotLength = Field(default=CopilotLength.STANDARD, description="Response detail length")
    custom_instructions: Optional[str] = Field(default=None, description="Agent-specific instructions or guidance")
    use_grounding: bool = Field(default=False, description="Whether to query internal Knowledge Base for grounded facts")
    provider_override: Optional[str] = Field(default=None, description="Optional provider override: mock or gemini")


class CitationSnippet(BaseModel):
    document_title: str
    chunk_id: Any
    chunk_index: int
    snippet: str
    relevance_score: float


class DraftResponse(BaseModel):
    draft_reply: str = Field(..., description="Synthesized agent reply draft")
    tone: str = Field(..., description="Tone applied to response")
    length: str = Field(..., description="Length setting used")
    grounded: bool = Field(default=False, description="Whether knowledge retrieval was included")
    citations: List[CitationSnippet] = Field(default_factory=list, description="Grounding source citations")
    model_name: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    estimated_cost_usd: float = 0.0


class RefineRequest(BaseModel):
    draft_text: str = Field(..., description="Current draft text to be revised")
    action: RefinementAction = Field(..., description="Refinement transformation action")
    custom_note: Optional[str] = Field(default=None, description="Optional extra guidance")
    provider_override: Optional[str] = Field(default=None, description="Optional provider override")


class RefineResponse(BaseModel):
    refined_text: str = Field(..., description="Polished response text")
    action: str = Field(..., description="Action applied")
    model_name: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float


class SummarizeRequest(BaseModel):
    ticket_id: Optional[int] = Field(default=None, description="Ticket ID")
    title: Optional[str] = Field(default="", description="Ticket title")
    description: Optional[str] = Field(default="", description="Ticket main description")
    conversation_thread: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Sequence of customer & agent messages")
    internal_notes: Optional[List[str]] = Field(default_factory=list, description="Existing internal notes")
    provider_override: Optional[str] = Field(default=None, description="Optional provider override")


class SummarizeResponse(BaseModel):
    summary: str = Field(..., description="Markdown structured internal handoff summary")
    issue_topic: str
    key_findings: List[str]
    current_status: str
    recommended_action: str
    model_name: str
    provider: str
    latency_ms: float


class QuickReplyTemplate(BaseModel):
    id: str
    title: str
    category: str
    content: str
    variables: List[str]
    is_system: bool = True


class TemplateCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=100)
    category: str = Field(..., min_length=2, max_length=50)
    content: str = Field(..., min_length=10)


class TemplateInterpolateRequest(BaseModel):
    ticket_id: Optional[int] = None
    custom_variables: Optional[Dict[str, str]] = None


class TemplateInterpolateResponse(BaseModel):
    template_id: str
    interpolated_content: str
    applied_variables: Dict[str, str]
