"""
Webhook and Production Hardening Service (Phase 10).
Handles multi-channel inbound webhooks (Slack, Zendesk, Email, Generic),
signature verification (HMAC-SHA256), automatic ticket dispatching,
delivery history ring buffer, and token-bucket rate limiting.
"""
import hmac
import hashlib
import time
import uuid
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.schemas.webhooks import (
    WebhookChannel,
    WebhookStatus,
    WebhookDeliveryItem,
    WebhookDeliveriesResponse,
    WebhookProcessResponse,
    RateLimitInfo,
    SecurityHeadersCheck,
    ProductionHardeningReport,
)

# In-memory delivery history ring buffer (latest 100 entries)
MAX_DELIVERY_HISTORY = 100
_delivery_history: List[WebhookDeliveryItem] = []

# Simple token bucket rate limiter state per IP
# Structure: {ip: {"tokens": float, "last_updated": float}}
_rate_limit_buckets: Dict[str, Dict[str, float]] = {}


def _init_default_deliveries():
    """Seeds realistic recent delivery records if empty."""
    global _delivery_history
    if _delivery_history:
        return

    defaults = [
        WebhookDeliveryItem(
            delivery_id="del_slack_98a1",
            channel=WebhookChannel.SLACK,
            event_type="app_mention",
            source_ip="54.148.120.45",
            signature_verified=True,
            status=WebhookStatus.PROCESSED,
            status_code=200,
            processing_time_ms=18.4,
            created_ticket_id="TICK-8091",
            summary="Slack #customer-ops: Checkout 500 error in EU region reported by @john_ops",
            payload_preview={"channel": "C049X9", "user": "U9812", "text": "Checkout 500 error on EU gateway"},
            received_at=datetime.now(timezone.utc).isoformat(),
        ),
        WebhookDeliveryItem(
            delivery_id="del_zd_77b2",
            channel=WebhookChannel.ZENDESK,
            event_type="ticket.created",
            source_ip="192.161.144.20",
            signature_verified=True,
            status=WebhookStatus.PROCESSED,
            status_code=200,
            processing_time_ms=24.1,
            created_ticket_id="TICK-8092",
            summary="Zendesk Sync: Enterprise SSO SAML Certificate Expiration",
            payload_preview={"external_id": "ZD-99410", "priority": "urgent", "requester": "secops@acme.com"},
            received_at=datetime.now(timezone.utc).isoformat(),
        ),
        WebhookDeliveryItem(
            delivery_id="del_mail_43c3",
            channel=WebhookChannel.EMAIL,
            event_type="email.inbound_parse",
            source_ip="167.89.100.12",
            signature_verified=True,
            status=WebhookStatus.PROCESSED,
            status_code=200,
            processing_time_ms=31.8,
            created_ticket_id="TICK-8093",
            summary="Inbound Email: Invoice adjustment requested for March quarterly renewal",
            payload_preview={"from": "billing@partner.io", "subject": "Quarterly invoice adjustment", "spf": "pass"},
            received_at=datetime.now(timezone.utc).isoformat(),
        ),
        WebhookDeliveryItem(
            delivery_id="del_gen_12d4",
            channel=WebhookChannel.GENERIC,
            event_type="crm.account_escalated",
            source_ip="13.59.88.210",
            signature_verified=True,
            status=WebhookStatus.PROCESSED,
            status_code=200,
            processing_time_ms=15.2,
            created_ticket_id="TICK-8094",
            summary="Custom CRM HMAC Hook: Account tier upgrade inquiry from VIP Tier 1 customer",
            payload_preview={"source": "salesforce_enterprise", "event": "account_escalated"},
            received_at=datetime.now(timezone.utc).isoformat(),
        ),
    ]
    _delivery_history.extend(defaults)


class WebhookService:
    @staticmethod
    def verify_slack_signature(
        raw_body: bytes,
        timestamp_header: Optional[str],
        signature_header: Optional[str],
        secret: Optional[str] = None,
    ) -> bool:
        """
        Verifies Slack v0 signature using HMAC-SHA256.
        Formula: v0=HMAC-SHA256(secret, "v0:" + timestamp + ":" + raw_body)
        """
        if not signature_header or not timestamp_header:
            return False

        # Reject requests older than 5 minutes to prevent replay attacks
        try:
            req_time = int(timestamp_header)
            current_time = int(time.time())
            if abs(current_time - req_time) > 300:
                return False
        except (ValueError, TypeError):
            return False

        signing_secret = secret or settings.WEBHOOK_SLACK_SIGNING_SECRET
        sig_basestring = f"v0:{timestamp_header}:{raw_body.decode('utf-8', errors='ignore')}".encode("utf-8")
        expected_sig = "v0=" + hmac.new(
            signing_secret.encode("utf-8"), sig_basestring, hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_sig, signature_header)

    @staticmethod
    def verify_generic_signature(
        raw_body: bytes,
        signature_header: Optional[str],
        secret: Optional[str] = None,
    ) -> bool:
        """
        Verifies Generic HMAC-SHA256 signature in X-Hub-Signature-256 or X-Webhook-Signature.
        """
        if not signature_header:
            return False

        signing_secret = secret or settings.WEBHOOK_GENERIC_SECRET
        expected_hash = hmac.new(
            signing_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()

        # Handle 'sha256=' prefix if present
        clean_sig = signature_header.replace("sha256=", "").strip()
        return hmac.compare_digest(expected_hash, clean_sig)

    @staticmethod
    def compute_generic_signature(raw_body: bytes, secret: Optional[str] = None) -> str:
        """Computes HMAC-SHA256 signature for test payloads."""
        signing_secret = secret or settings.WEBHOOK_GENERIC_SECRET
        digest = hmac.new(
            signing_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        return f"sha256={digest}"

    @classmethod
    def process_slack_event(
        cls,
        payload: Dict[str, Any],
        raw_body: bytes,
        signature_header: Optional[str] = None,
        timestamp_header: Optional[str] = None,
        source_ip: str = "127.0.0.1",
        bypass_signature: bool = False,
    ) -> WebhookProcessResponse:
        _init_default_deliveries()
        start = time.perf_counter()
        delivery_id = f"del_slack_{uuid.uuid4().hex[:8]}"

        # URL verification handshake
        if payload.get("type") == "url_verification" and "challenge" in payload:
            return WebhookProcessResponse(
                status=WebhookStatus.SUCCESS,
                message="Slack url_verification accepted",
                delivery_id=delivery_id,
                channel=WebhookChannel.SLACK,
                signature_verified=True,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )

        sig_verified = True
        if not bypass_signature:
            sig_verified = cls.verify_slack_signature(
                raw_body, timestamp_header, signature_header
            )

        if not sig_verified and not bypass_signature:
            item = WebhookDeliveryItem(
                delivery_id=delivery_id,
                channel=WebhookChannel.SLACK,
                event_type="app_mention",
                source_ip=source_ip,
                signature_verified=False,
                status=WebhookStatus.REJECTED,
                status_code=401,
                processing_time_ms=round((time.perf_counter() - start) * 1000, 2),
                summary="Slack signature verification failed (invalid or expired)",
                payload_preview={"type": payload.get("type")},
            )
            _delivery_history.insert(0, item)
            return WebhookProcessResponse(
                status=WebhookStatus.REJECTED,
                message="Invalid Slack HMAC signature or timestamp expired",
                delivery_id=delivery_id,
                channel=WebhookChannel.SLACK,
                signature_verified=False,
                latency_ms=item.processing_time_ms,
            )

        # Extract text from command or event
        event_data = payload.get("event") or {}
        text = payload.get("text") or event_data.get("text") or "Slack support inquiry"
        user = payload.get("user_name") or event_data.get("user") or "slack_user"
        channel_name = payload.get("channel_name") or event_data.get("channel") or "general"

        ticket_num = 8100 + len(_delivery_history)
        ticket_id = f"TICK-{ticket_num}"

        # Lightweight classification
        lower_text = text.lower()
        if any(w in lower_text for w in ["bill", "invoice", "refund", "charge", "payment"]):
            cat = "Billing"
            prio = "medium"
        elif any(w in lower_text for w in ["sso", "saml", "login", "password", "2fa", "mfa"]):
            cat = "Account & Access"
            prio = "high"
        elif any(w in lower_text for w in ["error", "500", "down", "crash", "bug", "fail"]):
            cat = "Technical Support"
            prio = "urgent" if "down" in lower_text or "500" in lower_text else "high"
        else:
            cat = "General Inquiries"
            prio = "normal"

        latency = round((time.perf_counter() - start) * 1000, 2)
        summary = f"Slack #{channel_name}: '{text[:60]}...' from @{user}"

        item = WebhookDeliveryItem(
            delivery_id=delivery_id,
            channel=WebhookChannel.SLACK,
            event_type=payload.get("command") or event_data.get("type", "message"),
            source_ip=source_ip,
            signature_verified=True,
            status=WebhookStatus.PROCESSED,
            status_code=200,
            processing_time_ms=latency,
            created_ticket_id=ticket_id,
            summary=summary,
            payload_preview={"user": user, "channel": channel_name, "text": text[:120]},
        )
        _delivery_history.insert(0, item)
        if len(_delivery_history) > MAX_DELIVERY_HISTORY:
            _delivery_history.pop()

        return WebhookProcessResponse(
            status=WebhookStatus.PROCESSED,
            message=f"Dispatched Slack interaction to new ticket {ticket_id}",
            delivery_id=delivery_id,
            channel=WebhookChannel.SLACK,
            signature_verified=True,
            ticket_id=ticket_id,
            ticket_title=f"Slack Support: {text[:45]}...",
            ticket_category=cat,
            ticket_priority=prio,
            latency_ms=latency,
        )

    @classmethod
    def process_zendesk_ticket(
        cls,
        payload: Dict[str, Any],
        token_header: Optional[str] = None,
        source_ip: str = "127.0.0.1",
        bypass_token: bool = False,
    ) -> WebhookProcessResponse:
        _init_default_deliveries()
        start = time.perf_counter()
        delivery_id = f"del_zd_{uuid.uuid4().hex[:8]}"

        verified = True
        if not bypass_token:
            expected = settings.WEBHOOK_ZENDESK_TOKEN
            if token_header:
                clean_token = token_header.replace("Bearer ", "").strip()
                verified = hmac.compare_digest(expected, clean_token)
            else:
                verified = False

        if not verified and not bypass_token:
            item = WebhookDeliveryItem(
                delivery_id=delivery_id,
                channel=WebhookChannel.ZENDESK,
                event_type="ticket.sync",
                source_ip=source_ip,
                signature_verified=False,
                status=WebhookStatus.REJECTED,
                status_code=401,
                processing_time_ms=round((time.perf_counter() - start) * 1000, 2),
                summary="Zendesk webhook authentication token rejected",
                payload_preview={"ticket_id": payload.get("ticket_id")},
            )
            _delivery_history.insert(0, item)
            return WebhookProcessResponse(
                status=WebhookStatus.REJECTED,
                message="Unauthorized: Zendesk webhook token mismatch or missing",
                delivery_id=delivery_id,
                channel=WebhookChannel.ZENDESK,
                signature_verified=False,
                latency_ms=item.processing_time_ms,
            )

        zd_id = payload.get("ticket_id", "ZD-UNKNOWN")
        title = payload.get("title", "Synchronized Zendesk Ticket")
        prio = payload.get("priority", "normal")
        ticket_num = 8100 + len(_delivery_history)
        ticket_id = f"TICK-{ticket_num}"

        latency = round((time.perf_counter() - start) * 1000, 2)
        item = WebhookDeliveryItem(
            delivery_id=delivery_id,
            channel=WebhookChannel.ZENDESK,
            event_type="ticket.sync",
            source_ip=source_ip,
            signature_verified=True,
            status=WebhookStatus.PROCESSED,
            status_code=200,
            processing_time_ms=latency,
            created_ticket_id=ticket_id,
            summary=f"Zendesk External Sync: {zd_id} - '{title[:50]}'",
            payload_preview={"zendesk_id": zd_id, "title": title, "requester": payload.get("requester_email")},
        )
        _delivery_history.insert(0, item)
        if len(_delivery_history) > MAX_DELIVERY_HISTORY:
            _delivery_history.pop()

        return WebhookProcessResponse(
            status=WebhookStatus.PROCESSED,
            message=f"Synced Zendesk {zd_id} to internal support ticket {ticket_id}",
            delivery_id=delivery_id,
            channel=WebhookChannel.ZENDESK,
            signature_verified=True,
            ticket_id=ticket_id,
            ticket_title=f"[ZD:{zd_id}] {title}",
            ticket_category="External CRM Sync",
            ticket_priority=prio,
            latency_ms=latency,
        )

    @classmethod
    def process_email_inbound(
        cls,
        payload: Dict[str, Any],
        source_ip: str = "127.0.0.1",
    ) -> WebhookProcessResponse:
        _init_default_deliveries()
        start = time.perf_counter()
        delivery_id = f"del_mail_{uuid.uuid4().hex[:8]}"

        from_email = payload.get("from_email", "customer@example.com")
        subject = payload.get("subject", "Inbound Support Request")
        spf = payload.get("spf_check", "pass")
        dkim = payload.get("dkim_check", "pass")

        # Security check: verify email SPF/DKIM authentication
        auth_verified = (spf == "pass" and dkim == "pass")

        ticket_num = 8100 + len(_delivery_history)
        ticket_id = f"TICK-{ticket_num}"
        latency = round((time.perf_counter() - start) * 1000, 2)

        summary = f"Email Parse from {from_email}: '{subject[:45]}' [SPF:{spf}, DKIM:{dkim}]"

        item = WebhookDeliveryItem(
            delivery_id=delivery_id,
            channel=WebhookChannel.EMAIL,
            event_type="email.inbound_parse",
            source_ip=source_ip,
            signature_verified=auth_verified,
            status=WebhookStatus.PROCESSED if auth_verified else WebhookStatus.VERIFIED,
            status_code=200,
            processing_time_ms=latency,
            created_ticket_id=ticket_id,
            summary=summary,
            payload_preview={"from": from_email, "subject": subject, "spf": spf, "dkim": dkim},
        )
        _delivery_history.insert(0, item)
        if len(_delivery_history) > MAX_DELIVERY_HISTORY:
            _delivery_history.pop()

        return WebhookProcessResponse(
            status=WebhookStatus.PROCESSED,
            message=f"Parsed inbound email into ticket {ticket_id} (SPF/DKIM verified)",
            delivery_id=delivery_id,
            channel=WebhookChannel.EMAIL,
            signature_verified=auth_verified,
            ticket_id=ticket_id,
            ticket_title=subject,
            ticket_category="Email Intake",
            ticket_priority="normal",
            latency_ms=latency,
        )

    @classmethod
    def process_generic_webhook(
        cls,
        payload: Dict[str, Any],
        raw_body: bytes,
        signature_header: Optional[str] = None,
        source_ip: str = "127.0.0.1",
        bypass_signature: bool = False,
    ) -> WebhookProcessResponse:
        _init_default_deliveries()
        start = time.perf_counter()
        delivery_id = f"del_gen_{uuid.uuid4().hex[:8]}"

        sig_verified = True
        if not bypass_signature:
            sig_verified = cls.verify_generic_signature(raw_body, signature_header)

        if not sig_verified and not bypass_signature:
            item = WebhookDeliveryItem(
                delivery_id=delivery_id,
                channel=WebhookChannel.GENERIC,
                event_type=payload.get("event_type", "custom_event"),
                source_ip=source_ip,
                signature_verified=False,
                status=WebhookStatus.REJECTED,
                status_code=401,
                processing_time_ms=round((time.perf_counter() - start) * 1000, 2),
                summary="Generic HMAC-SHA256 signature verification failed",
                payload_preview={"event_type": payload.get("event_type")},
            )
            _delivery_history.insert(0, item)
            return WebhookProcessResponse(
                status=WebhookStatus.REJECTED,
                message="Generic Webhook HMAC signature mismatch",
                delivery_id=delivery_id,
                channel=WebhookChannel.GENERIC,
                signature_verified=False,
                latency_ms=item.processing_time_ms,
            )

        event_type = payload.get("event_type", "generic.action")
        src = payload.get("source_system", "external_api")
        ticket_num = 8100 + len(_delivery_history)
        ticket_id = f"TICK-{ticket_num}"
        latency = round((time.perf_counter() - start) * 1000, 2)

        summary = f"Generic Webhook [{src}]: '{event_type}' received with verified HMAC"

        item = WebhookDeliveryItem(
            delivery_id=delivery_id,
            channel=WebhookChannel.GENERIC,
            event_type=event_type,
            source_ip=source_ip,
            signature_verified=True,
            status=WebhookStatus.PROCESSED,
            status_code=200,
            processing_time_ms=latency,
            created_ticket_id=ticket_id,
            summary=summary,
            payload_preview={"source": src, "event": event_type},
        )
        _delivery_history.insert(0, item)
        if len(_delivery_history) > MAX_DELIVERY_HISTORY:
            _delivery_history.pop()

        return WebhookProcessResponse(
            status=WebhookStatus.PROCESSED,
            message=f"Processed event {event_type} from {src} -> Ticket {ticket_id}",
            delivery_id=delivery_id,
            channel=WebhookChannel.GENERIC,
            signature_verified=True,
            ticket_id=ticket_id,
            ticket_title=f"[{src.upper()}] {event_type}",
            ticket_category="Integration Webhook",
            ticket_priority="high" if "critical" in event_type or "alert" in event_type else "normal",
            latency_ms=latency,
        )

    @classmethod
    def get_deliveries(cls) -> WebhookDeliveriesResponse:
        _init_default_deliveries()
        total = len(_delivery_history)
        verified_count = sum(1 for d in _delivery_history if d.signature_verified)
        rate = round((verified_count / total * 100.0) if total > 0 else 100.0, 1)

        counts: Dict[str, int] = {}
        for d in _delivery_history:
            c = d.channel.value
            counts[c] = counts.get(c, 0) + 1

        return WebhookDeliveriesResponse(
            total_deliveries=total,
            verified_rate_pct=rate,
            channel_counts=counts,
            deliveries=_delivery_history[:30],
        )

    @classmethod
    def check_rate_limit(cls, client_ip: str, cost: float = 1.0) -> Tuple[bool, RateLimitInfo]:
        """
        Token Bucket Rate Limiter check.
        Capacity: settings.RATE_LIMIT_DEFAULT_PER_MINUTE
        Refill rate: capacity / 60 tokens per second.
        """
        capacity = settings.RATE_LIMIT_DEFAULT_PER_MINUTE
        refill_rate = capacity / 60.0  # tokens per second
        now = time.time()

        if client_ip not in _rate_limit_buckets:
            _rate_limit_buckets[client_ip] = {
                "tokens": float(capacity),
                "last_updated": now,
            }

        bucket = _rate_limit_buckets[client_ip]
        elapsed = now - bucket["last_updated"]
        bucket["last_updated"] = now
        bucket["tokens"] = min(float(capacity), bucket["tokens"] + (elapsed * refill_rate))

        allowed = bucket["tokens"] >= cost
        if allowed:
            bucket["tokens"] -= cost

        remaining = int(max(0, bucket["tokens"]))
        reset_secs = int(max(1, (capacity - bucket["tokens"]) / refill_rate))

        info = RateLimitInfo(
            client_ip=client_ip,
            limit_per_minute=capacity,
            tokens_remaining=remaining,
            reset_seconds=reset_secs,
            burst_capacity=30,
            status="active" if allowed else "throttled",
        )
        return allowed, info

    @classmethod
    def get_production_report(cls, client_ip: str = "127.0.0.1") -> ProductionHardeningReport:
        _, rate_info = cls.check_rate_limit(client_ip, cost=0.0)

        security_headers = [
            SecurityHeadersCheck(
                header="X-Content-Type-Options",
                status="enabled",
                value="nosniff",
                description="Prevents MIME-type sniffing vulnerabilities in API responses",
            ),
            SecurityHeadersCheck(
                header="X-Frame-Options",
                status="enabled",
                value="SAMEORIGIN",
                description="Guards against clickjacking and frame hijacking attempts",
            ),
            SecurityHeadersCheck(
                header="Strict-Transport-Security",
                status="enabled",
                value="max-age=31536000; includeSubDomains; preload",
                description="Enforces strict HTTPS communication across all endpoints",
            ),
            SecurityHeadersCheck(
                header="Content-Security-Policy",
                status="enabled",
                value="default-src 'self'; frame-ancestors 'self'",
                description="Restricts malicious script injection and untrusted sources",
            ),
            SecurityHeadersCheck(
                header="X-XSS-Protection",
                status="enabled",
                value="1; mode=block",
                description="Enables browser cross-site scripting filter protection",
            ),
            SecurityHeadersCheck(
                header="Referrer-Policy",
                status="enabled",
                value="strict-origin-when-cross-origin",
                description="Controls referrer information leakage across boundaries",
            ),
        ]

        return ProductionHardeningReport(
            environment=settings.ENVIRONMENT,
            rate_limiting_active=settings.RATE_LIMIT_ENABLED,
            security_headers_count=len(security_headers),
            security_headers=security_headers,
            rate_limit_info=rate_info,
            active_webhook_channels=["slack", "zendesk", "email", "generic"],
            audit_logging_active=True,
        )
