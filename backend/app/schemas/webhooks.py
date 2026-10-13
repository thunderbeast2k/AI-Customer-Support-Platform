"""
Pydantic Schemas for Phase 10: Multi-Channel Webhook Gateways & Production Hardening.
Supports Slack, Zendesk, Email Inbound, and Generic HMAC Webhooks, along with Delivery Auditing.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WebhookChannel(str, Enum):
    SLACK = "slack"
    ZENDESK = "zendesk"
    EMAIL = "email"
    GENERIC = "generic"


class WebhookStatus(str, Enum):
    SUCCESS = "success"
    VERIFIED = "verified"
    REJECTED = "rejected"
    PROCESSED = "processed"
    FAILED = "failed"


# --- Inbound Payloads ---

class SlackEventPayload(BaseModel):
    token: Optional[str] = None
    team_id: Optional[str] = "T01234567"
    api_app_id: Optional[str] = "A01234567"
    type: str = Field(default="event_callback", description="event_callback, url_verification, etc.")
    challenge: Optional[str] = None
    event: Optional[Dict[str, Any]] = Field(
        default_factory=lambda: {
            "type": "app_mention",
            "user": "U123456",
            "text": "Help! Our checkout page is throwing 500 errors for European credit cards.",
            "channel": "C987654",
            "ts": "1712345678.000100",
        }
    )
    command: Optional[str] = None
    text: Optional[str] = None
    user_name: Optional[str] = None
    channel_name: Optional[str] = None


class ZendeskTicketPayload(BaseModel):
    ticket_id: str = Field(..., description="External Zendesk Ticket ID")
    title: str = Field(..., description="Ticket subject")
    description: str = Field(..., description="Initial ticket body")
    requester_email: str = Field(..., description="Customer email")
    requester_name: Optional[str] = "Customer"
    priority: str = Field(default="normal", description="urgent, high, normal, low")
    status: str = Field(default="new", description="new, open, pending, solved")
    tags: List[str] = Field(default_factory=list)
    custom_fields: Optional[Dict[str, Any]] = Field(default_factory=dict)


class EmailInboundPayload(BaseModel):
    from_email: str = Field(..., description="Sender email address")
    from_name: Optional[str] = Field(default="", description="Sender display name")
    to_email: str = Field(default="support@company.com", description="Inbound inbox address")
    subject: str = Field(..., description="Email subject line")
    body_plain: str = Field(..., description="Plaintext email body")
    body_html: Optional[str] = None
    spf_check: str = Field(default="pass", description="pass, neutral, fail")
    dkim_check: str = Field(default="pass", description="pass, neutral, fail")
    attachment_count: int = Field(default=0, ge=0)
    message_id: Optional[str] = None


class GenericWebhookPayload(BaseModel):
    event_type: str = Field(..., description="e.g. ticket.external_sync, alert.critical, customer.inquiry")
    source_system: str = Field(default="crm_salesforce", description="Identifier of calling system")
    timestamp: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    signature: Optional[str] = None


# --- Webhook Deliveries & Audit Log Models ---

class WebhookDeliveryItem(BaseModel):
    delivery_id: str
    channel: WebhookChannel
    event_type: str
    source_ip: str
    signature_verified: bool
    status: WebhookStatus
    status_code: int
    processing_time_ms: float
    created_ticket_id: Optional[str] = None
    summary: str
    payload_preview: Dict[str, Any]
    received_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WebhookDeliveriesResponse(BaseModel):
    total_deliveries: int
    verified_rate_pct: float
    channel_counts: Dict[str, int]
    deliveries: List[WebhookDeliveryItem]


class WebhookProcessResponse(BaseModel):
    status: WebhookStatus
    message: str
    delivery_id: str
    channel: WebhookChannel
    signature_verified: bool
    ticket_id: Optional[str] = None
    ticket_title: Optional[str] = None
    ticket_category: Optional[str] = None
    ticket_priority: Optional[str] = None
    latency_ms: float
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WebhookSimulateRequest(BaseModel):
    channel: WebhookChannel
    custom_payload: Optional[Dict[str, Any]] = None
    simulate_signature_failure: bool = False


# --- Production Rate Limiting & Diagnostics ---

class RateLimitInfo(BaseModel):
    client_ip: str
    limit_per_minute: int
    tokens_remaining: int
    reset_seconds: int
    burst_capacity: int
    status: str = "active"


class SecurityHeadersCheck(BaseModel):
    header: str
    status: str
    value: str
    description: str


class ProductionHardeningReport(BaseModel):
    environment: str
    rate_limiting_active: bool
    security_headers_count: int
    security_headers: List[SecurityHeadersCheck]
    rate_limit_info: RateLimitInfo
    active_webhook_channels: List[str]
    audit_logging_active: bool
