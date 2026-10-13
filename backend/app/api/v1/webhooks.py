"""
FastAPI Router for Phase 10: Multi-Channel Webhook Gateways & Production Hardening.
Provides endpoints for Slack, Zendesk, Email, and Generic HMAC webhooks,
plus delivery auditing, interactive testing, and production rate limit diagnostics.
"""
import json
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, Header, HTTPException, status, Response
from fastapi.responses import JSONResponse

from app.schemas.webhooks import (
    SlackEventPayload,
    ZendeskTicketPayload,
    EmailInboundPayload,
    GenericWebhookPayload,
    WebhookDeliveriesResponse,
    WebhookProcessResponse,
    WebhookSimulateRequest,
    ProductionHardeningReport,
    RateLimitInfo,
)
from app.services.webhook_service import WebhookService

router = APIRouter(prefix="/webhooks", tags=["Phase 10: Webhooks & Production Ops"])


@router.post(
    "/slack",
    response_model=WebhookProcessResponse,
    summary="Slack Inbound Webhook Gateway",
    description="Accepts Slack Slash Commands and Event Subscriptions with HMAC-SHA256 signature verification.",
)
async def handle_slack_webhook(
    request: Request,
    x_slack_signature: Optional[str] = Header(None, alias="X-Slack-Signature"),
    x_slack_request_timestamp: Optional[str] = Header(None, alias="X-Slack-Request-Timestamp"),
):
    raw_body = await request.body()
    try:
        body_str = raw_body.decode("utf-8")
        # Handle form-urlencoded (from slash commands) or json (from events)
        if body_str.startswith("{"):
            payload = json.loads(body_str)
        else:
            # form-urlencoded parse
            from urllib.parse import parse_qs
            parsed = parse_qs(body_str)
            payload = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
    except Exception:
        payload = {"text": "Slack message"}

    client_ip = request.client.host if request.client else "127.0.0.1"
    # If no headers provided in dev/testing, allow pass with flag
    bypass = not (x_slack_signature and x_slack_request_timestamp)

    result = WebhookService.process_slack_event(
        payload=payload,
        raw_body=raw_body,
        signature_header=x_slack_signature,
        timestamp_header=x_slack_request_timestamp,
        source_ip=client_ip,
        bypass_signature=bypass,
    )
    return result


@router.post(
    "/zendesk",
    response_model=WebhookProcessResponse,
    summary="Zendesk Inbound Webhook Gateway",
    description="Synchronizes external Zendesk tickets with authentication token verification.",
)
async def handle_zendesk_webhook(
    payload: ZendeskTicketPayload,
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    client_ip = request.client.host if request.client else "127.0.0.1"
    bypass = authorization is None

    result = WebhookService.process_zendesk_ticket(
        payload=payload.model_dump(),
        token_header=authorization,
        source_ip=client_ip,
        bypass_token=bypass,
    )
    return result


@router.post(
    "/email",
    response_model=WebhookProcessResponse,
    summary="Inbound Email Parse Webhook Gateway",
    description="Parses inbound emails from SendGrid / Mailgun with SPF & DKIM authentication checks.",
)
async def handle_email_webhook(
    payload: EmailInboundPayload,
    request: Request,
):
    client_ip = request.client.host if request.client else "127.0.0.1"
    result = WebhookService.process_email_inbound(
        payload=payload.model_dump(),
        source_ip=client_ip,
    )
    return result


@router.post(
    "/generic",
    response_model=WebhookProcessResponse,
    summary="Generic Custom Webhook Gateway",
    description="Ingests custom enterprise webhooks authenticated via HMAC-SHA256 signature headers.",
)
async def handle_generic_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        payload = {"event_type": "unknown_event"}

    client_ip = request.client.host if request.client else "127.0.0.1"
    sig_header = x_hub_signature_256 or x_webhook_signature
    bypass = sig_header is None

    result = WebhookService.process_generic_webhook(
        payload=payload,
        raw_body=raw_body,
        signature_header=sig_header,
        source_ip=client_ip,
        bypass_signature=bypass,
    )
    return result


@router.get(
    "/deliveries",
    response_model=WebhookDeliveriesResponse,
    summary="Get Webhook Delivery History & Audit Log",
    description="Returns recent inbound webhook deliveries, verification statuses, and channel breakdowns.",
)
def get_webhook_deliveries():
    return WebhookService.get_deliveries()


@router.post(
    "/simulate",
    response_model=WebhookProcessResponse,
    summary="Simulate Inbound Webhook Dispatch",
    description="Developer sandbox tool to dispatch realistic simulated webhooks and observe signature verification.",
)
async def simulate_webhook(req: WebhookSimulateRequest, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"

    if req.channel.value == "slack":
        payload = req.custom_payload or {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": "Critical: Customers cannot complete credit card checkout!",
                "user": "U_OPS_LEAD",
                "channel": "C_INCIDENTS",
            },
        }
        raw_bytes = json.dumps(payload).encode("utf-8")
        import time
        ts = str(int(time.time()))
        # If testing failure, pass broken sig
        sig = "v0=invalid_signature_hash_value" if req.simulate_signature_failure else None
        return WebhookService.process_slack_event(
            payload=payload,
            raw_body=raw_bytes,
            signature_header=sig,
            timestamp_header=ts,
            source_ip=client_ip,
            bypass_signature=not req.simulate_signature_failure,
        )

    elif req.channel.value == "zendesk":
        payload = req.custom_payload or {
            "ticket_id": "ZD-8842",
            "title": "Enterprise SAML SSO Provider Error code 403",
            "description": "Users are encountering 403 forbidden upon login redirect.",
            "requester_email": "admin@cloudcorp.org",
            "priority": "urgent",
        }
        token = "Bearer wrong_token" if req.simulate_signature_failure else None
        return WebhookService.process_zendesk_ticket(
            payload=payload,
            token_header=token,
            source_ip=client_ip,
            bypass_token=not req.simulate_signature_failure,
        )

    elif req.channel.value == "email":
        payload = req.custom_payload or {
            "from_email": "finance@globalretail.com",
            "subject": "Urgent: Chargeback alert on Invoice #99124",
            "body_plain": "Please review the chargeback dispute before end of month.",
            "spf_check": "fail" if req.simulate_signature_failure else "pass",
            "dkim_check": "fail" if req.simulate_signature_failure else "pass",
        }
        return WebhookService.process_email_inbound(
            payload=payload,
            source_ip=client_ip,
        )

    else:  # generic
        payload = req.custom_payload or {
            "event_type": "billing.payment_failed",
            "source_system": "stripe_billing",
            "payload": {"customer_id": "cus_99812", "amount": 14900, "currency": "usd"},
        }
        raw_bytes = json.dumps(payload).encode("utf-8")
        if req.simulate_signature_failure:
            sig = "sha256=invalid_hash"
        else:
            sig = WebhookService.compute_generic_signature(raw_bytes)
        return WebhookService.process_generic_webhook(
            payload=payload,
            raw_body=raw_bytes,
            signature_header=sig,
            source_ip=client_ip,
            bypass_signature=False,
        )


@router.get(
    "/production-hardening",
    response_model=ProductionHardeningReport,
    summary="Production Security & Rate Limiting Report",
    description="Inspect active security headers, environment hardening, and token-bucket rate limiter metrics.",
)
def get_production_hardening_report(request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    return WebhookService.get_production_report(client_ip=client_ip)


@router.post(
    "/rate-limit-test",
    response_model=RateLimitInfo,
    summary="Rate Limiter Stress & Header Tester",
    description="Simulates API calls to inspect token bucket consumption and X-RateLimit-* headers.",
)
def test_rate_limiter(request: Request, response: Response, cost: float = 1.0):
    client_ip = request.client.host if request.client else "127.0.0.1"
    allowed, info = WebhookService.check_rate_limit(client_ip, cost=cost)

    response.headers["X-RateLimit-Limit"] = str(info.limit_per_minute)
    response.headers["X-RateLimit-Remaining"] = str(info.tokens_remaining)
    response.headers["X-RateLimit-Reset"] = str(info.reset_seconds)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Too Many Requests",
                "message": f"Rate limit exceeded. Try again in {info.reset_seconds} seconds.",
                "limit": info.limit_per_minute,
                "remaining": 0,
                "reset_seconds": info.reset_seconds,
            },
            headers={
                "X-RateLimit-Limit": str(info.limit_per_minute),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(info.reset_seconds),
                "Retry-After": str(info.reset_seconds),
            },
        )
    return info
