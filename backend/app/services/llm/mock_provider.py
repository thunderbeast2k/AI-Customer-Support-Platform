"""
Deterministic Mock LLM Provider Adapter.
Allows running the full platform, RAG pipelines, and automated test suites without external API keys.
"""
import time
from typing import List, Dict, Any
from app.services.llm.base import BaseLLMProvider, LLMMessage, LLMResponse


class MockLLMProvider(BaseLLMProvider):
    """
    Deterministic mock provider that adheres strictly to context and anti-hallucination rules.
    """

    def __init__(self, model_name: str = "gemini-1.5-flash-mock"):
        self.model_name = model_name
        self.provider_id = "mock"

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_id,
            "model_name": self.model_name,
            "is_mock": True,
            "status": "operational",
        }

    def health_check(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "provider": self.provider_id,
            "model_name": self.model_name,
            "latency_ms": 1.2,
        }

    def generate_response(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> LLMResponse:
        start_time = time.perf_counter()

        # Extract system prompt and user message
        system_content = ""
        user_content = ""
        for m in messages:
            if m.role == "system":
                system_content = m.content
            elif m.role == "user":
                user_content = m.content

        user_lower = user_content.lower()

        # Case A: Check if this is an Agent Co-Pilot request (drafting, refining, or summarizing)
        is_copilot = any(
            kw in system_content.lower() or kw in user_lower
            for kw in ["co-pilot", "copilot", "drafting assistant", "refine the following", "summarize the following", "canned response"]
        )

        if is_copilot:
            content = self._generate_copilot_mock(system_content, user_content)
        # Case B: Standard Grounded RAG with CONTEXT PASSAGES
        elif "CONTEXT PASSAGES:" in user_content or "CONTEXT PASSAGES:" in system_content:
            context_text = ""
            if "CONTEXT PASSAGES:" in user_content:
                context_text = user_content.split("CONTEXT PASSAGES:")[1]
            elif "CONTEXT PASSAGES:" in system_content:
                context_text = system_content.split("CONTEXT PASSAGES:")[1]

            # Subcase 1: Insufficient evidence indicator present in context
            if "[INSUFFICIENT_EVIDENCE]" in context_text or not context_text.strip():
                content = (
                    "Based on our currently available internal documentation, I could not find verified facts "
                    "to answer your specific question accurately. To prevent miscommunication, I recommend "
                    "escalating this inquiry to our human support team, who will investigate and follow up with you."
                )
            # Subcase 2: Billing / Refund Context Present
            elif "refund" in context_text.lower() or "billing" in context_text.lower():
                content = (
                    "Based on Section 3.2 of our Billing & Refund Policies:\n\n"
                    "• All subscriptions renew on the 1st of each calendar month.\n"
                    "• If you observe a duplicate charge, it is typically a temporary authorization hold that drops off within 72 hours.\n"
                    "• Confirmed duplicate payments are refunded to the original payment instrument within 3 to 5 business days.\n\n"
                    "Please let us know if you would like an agent to open a refund ticket for this transaction."
                )
            # Subcase 3: SAML / Okta SSO Context Present
            elif "okta" in context_text.lower() or "sso" in context_text.lower() or "acs" in context_text.lower():
                content = (
                    "According to our SAML and Okta SSO Configuration Guide:\n\n"
                    "1. The Assertion Consumer Service (ACS) URL must be set to https://api.support.ai/v1/auth/sso/callback with entity ID urn:support:ai:auth.\n"
                    "2. Ensure the IdP certificate uses SHA-256 signatures.\n"
                    "3. Gateway 504 timeouts are typically caused by clock drift exceeding 120 seconds between servers.\n\n"
                    "If issues persist, please confirm your IdP certificate validity."
                )
            # Subcase 4: General synthesized context
            else:
                first_sentence = context_text.strip().split(".")[0] if "." in context_text else context_text[:100]
                content = (
                    f"Based on our internal documentation: {first_sentence.strip()}.\n\n"
                    f"Please let me know if you would like more details or if you would like me to connect you with a specialist."
                )
        else:
            # Fallback general query
            content = (
                f"Thank you for contacting support. I have received your request and am reviewing the details to provide the best assistance."
            )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        prompt_tokens = max(10, len(system_content + user_content) // 4)
        completion_tokens = max(10, len(content) // 4)

        return LLMResponse(
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=elapsed_ms,
            model_name=self.model_name,
            provider=self.provider_id,
        )

    def _generate_copilot_mock(self, system_content: str, user_content: str) -> str:
        """Generates contextual, tone-differentiated co-pilot drafts, refinements, or thread summaries."""
        lower_sys = system_content.lower()
        lower_usr = user_content.lower()

        # 1. Summarization check
        if "summarize" in lower_sys or "summary" in lower_usr or "internal note" in lower_usr:
            return (
                "📋 **Ticket Thread Summary (Internal Handoff Note)**\n\n"
                "• **Customer Issue:** Inquired about service disruption and configuration error encountered during setup.\n"
                "• **Key Diagnostic Findings:** Client experienced authentication / timeout exceptions; verified against internal documentation.\n"
                "• **Current Status:** Drafted remediation steps and awaiting customer diagnostic confirmation.\n"
                "• **Next Recommended Action:** If unresolved within 24 hours, escalate to Tier 2 Technical Engineering."
            )

        # 2. Refinement check
        if "refine the following" in lower_usr or "refinement" in lower_sys:
            # Extract text to refine if possible
            draft_text = user_content
            if "DRAFT TEXT:" in user_content:
                draft_text = user_content.split("DRAFT TEXT:")[1].strip()

            if "empathetic" in lower_usr or "empathy" in lower_usr:
                return (
                    f"Dear Valued Customer,\n\n"
                    f"I sincerely apologize for the frustration and inconvenience this situation has caused you. "
                    f"I completely understand how critical this is to your day-to-day operations, and our team is fully committed to making things right.\n\n"
                    f"{draft_text}\n\n"
                    f"Please rest assured that we are monitoring this ticket closely. Don't hesitate to reach back out if there is anything else I can assist with."
                )
            elif "concise" in lower_usr or "short" in lower_usr or "brief" in lower_usr:
                return (
                    f"Hi,\n\n"
                    f"Here is a summary of the next steps to resolve your request:\n"
                    f"• Review your current configuration or billing status.\n"
                    f"• Follow the documented instructions provided in your portal.\n"
                    f"• Reply to this ticket if further assistance is required.\n\n"
                    f"Best regards,\nCustomer Support Team"
                )
            elif "bullet" in lower_usr:
                return (
                    f"Hello,\n\n"
                    f"Please follow these step-by-step instructions:\n"
                    f"1. Navigate to your Account Settings > Integration tab.\n"
                    f"2. Confirm your configuration parameters match the active credentials.\n"
                    f"3. Clear local cache and re-authenticate.\n"
                    f"4. Verify the connection status shows green.\n\n"
                    f"Let us know if you encounter any errors during these steps."
                )
            elif "technical" in lower_usr:
                return (
                    f"Hello,\n\n"
                    f"Diagnostic Analysis:\n"
                    f"1. Ensure port 443 connectivity to our gateway (`curl -Iv https://api.support.ai/health`).\n"
                    f"2. Validate that the JWT auth bearer token has not expired and clock skew is within 120s.\n"
                    f"3. Verify error logs for standard HTTP 4xx/5xx payload codes.\n\n"
                    f"Please attach the full cURL request and response headers if the issue persists."
                )
            else:
                # Grammar & polish
                return (
                    f"Dear Customer,\n\n"
                    f"Thank you for reaching out to our support team. We have carefully reviewed your inquiry "
                    f"and would like to share the verified steps below:\n\n"
                    f"{draft_text}\n\n"
                    f"Should you require further clarification, please feel free to contact us."
                )

        # 3. Drafting responses with tone selection
        # Extract customer name if in prompt
        customer_name = "there"
        if "CUSTOMER NAME:" in user_content:
            try:
                customer_name = user_content.split("CUSTOMER NAME:")[1].split("\n")[0].strip() or "there"
            except Exception:
                pass

        # Detect tone from prompt
        if "empathetic" in lower_sys or "empathetic" in lower_usr:
            return (
                f"Hello {customer_name},\n\n"
                f"I want to personally apologize for any disruption or stress this issue has caused you. "
                f"I completely understand how frustrating it is when things don't work as expected, and I am right here to help you get this sorted out.\n\n"
                f"I have reviewed your inquiry and our team is already taking action. If you noticed duplicate authorization holds or unexpected errors, "
                f"please be assured that these are promptly verified and corrected by our specialized team.\n\n"
                f"Please let me know if you have any questions along the way—I will be tracking your case until it is completely resolved.\n\n"
                f"Warm regards,\nSupport Co-Pilot Specialist"
            )
        elif "concise" in lower_sys or "concise" in lower_usr:
            return (
                f"Hi {customer_name},\n\n"
                f"Regarding your ticket:\n"
                f"• We have logged and reviewed your inquiry.\n"
                f"• Verified policies or fixes have been applied to your account.\n"
                f"• If a billing hold occurred, funds release automatically within 72 hours.\n\n"
                f"Let us know if you need anything else.\n\n"
                f"Best,\nCustomer Support"
            )
        elif "technical" in lower_sys or "technical" in lower_usr:
            return (
                f"Hello {customer_name},\n\n"
                f"Diagnostic review for your inquiry:\n"
                f"1. **Root Cause Analysis:** Connection timeout or credential verification error.\n"
                f"2. **Configuration Steps:** Validate that your callback URL matches `https://api.support.ai/v1/auth/sso/callback` and certificate uses SHA-256 signatures.\n"
                f"3. **Telemetry Check:** Confirm server clock drift does not exceed 120 seconds.\n\n"
                f"If the error continues, please provide the request correlation ID (`X-Request-ID`) and status code for further tracing.\n\n"
                f"Regards,\nSystems & Support Engineering"
            )
        elif "friendly" in lower_sys or "friendly" in lower_usr:
            return (
                f"Hey {customer_name}!\n\n"
                f"Thanks so much for reaching out to us today! I'd be more than happy to help you with this.\n\n"
                f"I took a look at the details in your ticket, and everything looks straightforward to get straightened out. "
                f"Feel free to reply back here as soon as you have a chance, and we'll have you back on track in no time!\n\n"
                f"Cheers,\nYour Support Friend"
            )
        else:
            # Professional (default)
            return (
                f"Dear {customer_name},\n\n"
                f"Thank you for contacting our customer support team. We have received your inquiry and reviewed the details provided.\n\n"
                f"Based on our internal policies and support standards, we are actively processing your request. "
                f"Any pending transactions or system configurations are being evaluated to ensure full operational compliance.\n\n"
                f"If you have additional context or relevant files to attach, please reply directly to this message.\n\n"
                f"Sincerely,\nCustomer Support Team"
            )

