"""
Agent Response Co-Pilot Service (Phase 8).
Powers personalized response drafting, tone persona controls, grounding injection,
one-click refinements, conversation thread summarization, and quick reply macros.
"""
import time
import re
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.audit import ModelUsage
from app.models.ticket import Ticket
from app.services.hybrid_retriever import hybrid_retriever
from app.services.llm.base import LLMMessage
from app.services.llm.factory import get_llm_provider
from app.schemas.copilot import (
    DraftRequest,
    DraftResponse,
    CitationSnippet,
    RefineRequest,
    RefineResponse,
    SummarizeRequest,
    SummarizeResponse,
    QuickReplyTemplate,
    TemplateCreate,
    CopilotTone,
    CopilotLength,
    RefinementAction,
)

# Standard Canned Response Macros
INITIAL_TEMPLATES: List[QuickReplyTemplate] = [
    QuickReplyTemplate(
        id="tpl-diag-request",
        title="Diagnostic Logs & Network Trace Request",
        category="technical_issue",
        content=(
            "Hello {{customer_name}},\n\n"
            "Thank you for contacting our technical support team regarding ticket {{ticket_code}}. "
            "To help us isolate the root cause of this behavior, could you please provide the following diagnostic details:\n\n"
            "1. Approximate timestamp and timezone when the issue occurred.\n"
            "2. Full error message or HTTP status code displayed in your browser/console.\n"
            "3. If applicable, an exported HAR file or network request correlation ID (X-Request-ID).\n\n"
            "Once received, our engineering team will inspect the server telemetry immediately.\n\n"
            "Best regards,\n{{agent_name}}\n{{company_name}} Technical Support"
        ),
        variables=["customer_name", "ticket_code", "agent_name", "company_name"],
        is_system=True,
    ),
    QuickReplyTemplate(
        id="tpl-refund-ack",
        title="Refund & Authorization Hold Notice",
        category="billing",
        content=(
            "Dear {{customer_name}},\n\n"
            "Thank you for reaching out regarding ticket {{ticket_code}}. "
            "We have reviewed your billing record and want to confirm our policy regarding recent charges:\n\n"
            "• If you observed a duplicate charge, it is typically a temporary authorization hold that drops off automatically within 72 hours.\n"
            "• For confirmed duplicate or erroneous settlements, our billing desk processes full refunds back to your original payment card within 3 to 5 business days.\n\n"
            "We are tracking this inquiry closely and will notify you as soon as the adjustment is verified.\n\n"
            "Warm regards,\n{{agent_name}}\n{{company_name}} Billing Desk"
        ),
        variables=["customer_name", "ticket_code", "agent_name", "company_name"],
        is_system=True,
    ),
    QuickReplyTemplate(
        id="tpl-pwd-reset",
        title="2FA & Password Recovery Walkthrough",
        category="account_access",
        content=(
            "Hello {{customer_name}},\n\n"
            "We have received your account access inquiry for ticket {{ticket_code}}. "
            "To safely regain access to your account while preserving data security, please follow these steps:\n\n"
            "1. Visit our secure recovery portal at: https://support.ai/recover\n"
            "2. Enter your primary registered email address.\n"
            "3. If you have lost access to your primary authenticator device, click 'Verify via Backup Recovery Codes'.\n"
            "4. Follow the one-time email verification link sent to your inbox (valid for 15 minutes).\n\n"
            "Please reply directly to this ticket if you require further assistance.\n\n"
            "Best regards,\n{{agent_name}}\n{{company_name}} Security Operations"
        ),
        variables=["customer_name", "ticket_code", "agent_name", "company_name"],
        is_system=True,
    ),
    QuickReplyTemplate(
        id="tpl-sso-config",
        title="SAML 2.0 / Okta SSO Callback Setup",
        category="technical_issue",
        content=(
            "Hello {{customer_name}},\n\n"
            "Regarding your enterprise Single Sign-On integration inquiry (ticket {{ticket_code}}):\n\n"
            "• ACS (Assertion Consumer Service) URL: https://api.support.ai/v1/auth/sso/callback\n"
            "• Entity ID (Audience URI): urn:support:ai:auth\n"
            "• NameID Format: EmailAddress\n"
            "• Signature Algorithm: SHA-256\n\n"
            "Note: If you encounter HTTP 504 timeouts during handshake, please ensure your IdP clock skew is under 120 seconds.\n\n"
            "Sincerely,\n{{agent_name}}\n{{company_name}} Integrations Team"
        ),
        variables=["customer_name", "ticket_code", "agent_name", "company_name"],
        is_system=True,
    ),
    QuickReplyTemplate(
        id="tpl-escalate-tier2",
        title="Escalation to Engineering Notice",
        category="general_inquiry",
        content=(
            "Dear {{customer_name}},\n\n"
            "Thank you for your patience while we investigate ticket {{ticket_code}}. "
            "Due to the specialized nature of this behavior, I have formally escalated your case to our Tier 2 Engineering group.\n\n"
            "A senior engineer has been assigned and is reviewing the system telemetry. "
            "We anticipate an update within 4 business hours. No further action is required from you at this time.\n\n"
            "Thank you for working with us,\n{{agent_name}}\n{{company_name}} Customer Care"
        ),
        variables=["customer_name", "ticket_code", "agent_name", "company_name"],
        is_system=True,
    ),
    QuickReplyTemplate(
        id="tpl-satisfaction-close",
        title="Resolved Ticket Satisfaction Survey",
        category="general_inquiry",
        content=(
            "Hello {{customer_name}},\n\n"
            "We are pleased to inform you that ticket {{ticket_code}} has been marked as resolved! "
            "We hope our support met your expectations and got everything running smoothly.\n\n"
            "If you have any remaining questions or need further clarification, simply reply to this email within 7 days to reopen the conversation.\n\n"
            "Thank you for being a valued customer!\n\n"
            "Best wishes,\n{{agent_name}}\n{{company_name}}"
        ),
        variables=["customer_name", "ticket_code", "agent_name", "company_name"],
        is_system=True,
    ),
]


class CopilotService:
    """Service handling generative agent assistance, tone modulation, and canned macros."""

    def __init__(self):
        self.templates: Dict[str, QuickReplyTemplate] = {t.id: t for t in INITIAL_TEMPLATES}

    def list_templates(self, category: Optional[str] = None, search: Optional[str] = None) -> List[QuickReplyTemplate]:
        """Returns filtered list of quick reply macro templates."""
        results = list(self.templates.values())
        if category:
            results = [t for t in results if t.category.lower() == category.lower()]
        if search:
            q = search.lower()
            results = [t for t in results if q in t.title.lower() or q in t.content.lower()]
        return results

    def get_template(self, template_id: str) -> Optional[QuickReplyTemplate]:
        return self.templates.get(template_id)

    def create_template(self, data: TemplateCreate) -> QuickReplyTemplate:
        """Creates a custom canned response template."""
        # Extract variables in {{var_name}} format
        vars_found = list(set(re.findall(r"\{\{([a-zA-Z0-9_]+)\}\}", data.content)))
        tpl_id = f"custom-{int(time.time())}-{len(self.templates) + 1}"
        new_tpl = QuickReplyTemplate(
            id=tpl_id,
            title=data.title.strip(),
            category=data.category.strip(),
            content=data.content.strip(),
            variables=vars_found,
            is_system=False,
        )
        self.templates[tpl_id] = new_tpl
        return new_tpl

    def interpolate_template(
        self,
        template_id: str,
        ticket: Optional[Ticket] = None,
        custom_vars: Optional[Dict[str, str]] = None,
        agent_name: str = "Support Specialist",
        company_name: str = "Enterprise Cloud",
    ) -> Dict[str, Any]:
        """Replaces template placeholders with live ticket or custom variable data."""
        tpl = self.templates.get(template_id)
        if not tpl:
            raise ValueError(f"Template '{template_id}' not found.")

        # Default mapping
        variables_map: Dict[str, str] = {
            "customer_name": "Valued Customer",
            "ticket_code": "TIK-2026-XXXX",
            "ticket_id": "0",
            "category": "General Support",
            "agent_name": agent_name,
            "company_name": company_name,
        }

        if ticket:
            variables_map["ticket_code"] = ticket.ticket_code or f"TIK-{ticket.id}"
            variables_map["ticket_id"] = str(ticket.id)
            variables_map["category"] = str(ticket.category.value if hasattr(ticket.category, "value") else ticket.category)
            if hasattr(ticket, "customer") and ticket.customer:
                variables_map["customer_name"] = ticket.customer.full_name or ticket.customer.email
            if hasattr(ticket, "assigned_agent") and ticket.assigned_agent:
                variables_map["agent_name"] = ticket.assigned_agent.full_name

        if custom_vars:
            variables_map.update(custom_vars)

        interpolated = tpl.content
        for key, val in variables_map.items():
            pattern = re.compile(rf"\{{\{{\s*{key}\s*\}}\}}", re.IGNORECASE)
            interpolated = pattern.sub(str(val), interpolated)

        return {
            "template_id": template_id,
            "interpolated_content": interpolated,
            "applied_variables": variables_map,
        }

    def draft_reply(
        self,
        db: Optional[Session],
        data: DraftRequest,
    ) -> DraftResponse:
        """
        Generates a context-aware response draft using the active LLM provider.
        Optionally augments with RAG documentation citations.
        """
        start_time = time.perf_counter()

        # 1. Grounding check
        citations: List[CitationSnippet] = []
        grounding_context = ""
        if data.use_grounding and db is not None:
            retrieval_query = f"{data.title} {data.description}"
            chunks = hybrid_retriever.retrieve(db=db, query=retrieval_query, top_k=3, threshold=0.35)
            if chunks:
                grounding_blocks = []
                for c in chunks:
                    snippet = c["content"][:220] + "..." if len(c["content"]) > 220 else c["content"]
                    citations.append(
                        CitationSnippet(
                            document_title=c["document_title"],
                            chunk_id=c["chunk_id"],
                            chunk_index=c["chunk_index"],
                            snippet=snippet,
                            relevance_score=c["similarity_score"],
                        )
                    )
                    grounding_blocks.append(
                        f"• Document '{c['document_title']}' (Score {c['similarity_score']}): {c['content']}"
                    )
                grounding_context = "\n\nCONTEXT PASSAGES:\n" + "\n".join(grounding_blocks)

        # 2. Build system persona prompt
        tone_instructions = {
            CopilotTone.PROFESSIONAL: (
                "Adopt a professional, authoritative, courteous tone. Use clear corporate phrasing, "
                "address the customer politely, and present direct, actionable solutions."
            ),
            CopilotTone.EMPATHETIC: (
                "Adopt an empathetic, supportive, understanding tone. Acknowledge the user's frustration or inconvenience "
                "sincerely, offer reassuring validation, and express dedication to resolving their problem."
            ),
            CopilotTone.CONCISE: (
                "Adopt a concise, efficient, no-fluff tone. Provide short sentences or bullet points. "
                "Focus purely on essential facts and immediate next steps."
            ),
            CopilotTone.TECHNICAL: (
                "Adopt a technical, diagnostic-oriented tone. Provide specific technical steps, configuration details, "
                "command-line syntax, or log inspection instructions suitable for developers or IT administrators."
            ),
            CopilotTone.FRIENDLY: (
                "Adopt a friendly, warm, conversational tone. Use approachable phrasing, enthusiastic help, and an upbeat closing."
            ),
        }

        length_instructions = {
            CopilotLength.BRIEF: "Keep the response brief (1-2 short paragraphs or 3 bullet points maximum).",
            CopilotLength.STANDARD: "Provide a balanced, standard response (2-3 structured paragraphs with clear instructions).",
            CopilotLength.DETAILED: "Provide a comprehensive, detailed walkthrough covering background, step-by-step resolution, and contingency steps.",
        }

        system_prompt = (
            f"You are an enterprise AI Support Agent Response Co-Pilot. "
            f"Your job is to draft a complete, ready-to-send support email response from the human agent to the customer.\n\n"
            f"TONE SPECIFICATION:\n{tone_instructions.get(data.tone, tone_instructions[CopilotTone.PROFESSIONAL])}\n\n"
            f"LENGTH SPECIFICATION:\n{length_instructions.get(data.length, length_instructions[CopilotLength.STANDARD])}\n\n"
            f"GUIDELINES:\n"
            f"1. Greet the customer by name if provided.\n"
            f"2. Reference the ticket details and issue subject directly.\n"
            f"3. Incorporate facts from internal context passages when available.\n"
            f"4. End with a polite closing and professional signature."
        )

        user_prompt = (
            f"CUSTOMER NAME: {data.customer_name or 'Valued Customer'}\n"
            f"TICKET CODE: {data.ticket_code or 'TIK-PENDING'}\n"
            f"CATEGORY: {data.category}\n"
            f"PRIORITY: {data.priority}\n"
            f"ISSUE TITLE: {data.title}\n"
            f"CUSTOMER DESCRIPTION: {data.description}\n"
        )

        if data.custom_instructions:
            user_prompt += f"\nAGENT INSTRUCTIONS: {data.custom_instructions}\n"

        if grounding_context:
            user_prompt += grounding_context

        # 3. Call LLM provider
        provider = get_llm_provider(data.provider_override)
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        llm_res = provider.generate_response(messages=messages, temperature=0.3, max_tokens=900)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        # 4. Telemetry logging
        cost = (llm_res.prompt_tokens * 0.075 / 1_000_000) + (llm_res.completion_tokens * 0.30 / 1_000_000)
        if db is not None:
            try:
                usage = ModelUsage(
                    provider=llm_res.provider,
                    model_name=llm_res.model_name,
                    operation="copilot_draft",
                    prompt_tokens=llm_res.prompt_tokens,
                    completion_tokens=llm_res.completion_tokens,
                    total_tokens=llm_res.total_tokens,
                    latency_ms=elapsed_ms,
                    estimated_cost_usd=cost,
                    status="success",
                )
                db.add(usage)
                db.commit()
            except Exception:
                db.rollback()

        return DraftResponse(
            draft_reply=llm_res.content,
            tone=data.tone.value,
            length=data.length.value,
            grounded=bool(citations),
            citations=citations,
            model_name=llm_res.model_name,
            provider=llm_res.provider,
            prompt_tokens=llm_res.prompt_tokens,
            completion_tokens=llm_res.completion_tokens,
            total_tokens=llm_res.total_tokens,
            latency_ms=elapsed_ms,
            estimated_cost_usd=round(cost, 6),
        )

    def refine_draft(
        self,
        db: Optional[Session],
        data: RefineRequest,
    ) -> RefineResponse:
        """Applies transformation rewrites (more empathetic, concise, bulletize, grammar, technical)."""
        start_time = time.perf_counter()

        action_guides = {
            RefinementAction.MORE_EMPATHETIC: (
                "Rewrite the response to be significantly more empathetic, warm, and apologetic. "
                "Validate the user's feelings and assure them of our personal dedication to making it right."
            ),
            RefinementAction.MORE_CONCISE: (
                "Make the response extremely concise and direct. Cut all corporate fluff, greetings, and filler words. "
                "Deliver the core steps immediately in 2-3 crisp sentences or bullets."
            ),
            RefinementAction.BULLETIZE: (
                "Restructure the instructions and solutions into numbered or bulleted step-by-step format for maximum readability."
            ),
            RefinementAction.FIX_GRAMMAR: (
                "Fix all grammatical, spelling, and punctuation issues. Polish the tone to be crisp, natural, and executive-level."
            ),
            RefinementAction.TECHNICAL_DEPTH: (
                "Enhance the response with technical depth: add diagnostic checks, terminal commands, or config references."
            ),
        }

        system_prompt = (
            f"You are an expert AI Editor and Co-Pilot for Customer Support communications.\n"
            f"TASK: Refine the provided draft reply according to this directive:\n"
            f"{action_guides.get(data.action, 'Polish and improve clarity.')}\n\n"
            f"Maintain all factual substance and ticket specifics."
        )

        user_prompt = f"REFINE THE FOLLOWING DRAFT:\n\n{data.draft_text}"
        if data.custom_note:
            user_prompt += f"\n\nADDITIONAL INSTRUCTION: {data.custom_note}"

        provider = get_llm_provider(data.provider_override)
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        llm_res = provider.generate_response(messages=messages, temperature=0.2, max_tokens=750)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return RefineResponse(
            refined_text=llm_res.content,
            action=data.action.value,
            model_name=llm_res.model_name,
            provider=llm_res.provider,
            prompt_tokens=llm_res.prompt_tokens,
            completion_tokens=llm_res.completion_tokens,
            total_tokens=llm_res.total_tokens,
            latency_ms=elapsed_ms,
        )

    def summarize_thread(
        self,
        db: Optional[Session],
        data: SummarizeRequest,
    ) -> SummarizeResponse:
        """Summarizes a ticket thread into a structured internal handover note."""
        start_time = time.perf_counter()

        system_prompt = (
            "You are an AI Support Ops Assistant. "
            "Generate a concise, structured Internal Handoff Note summarizing this ticket's history for another agent.\n"
            "Include: 1. Core Issue Topic, 2. Key Diagnostic Findings, 3. Current Status, 4. Action Items."
        )

        user_prompt = f"TICKET ID: {data.ticket_id or 'N/A'}\nTITLE: {data.title}\nDESCRIPTION: {data.description}\n"
        if data.conversation_thread:
            user_prompt += "\nCONVERSATION THREAD:\n"
            for msg in data.conversation_thread:
                sender = msg.get("sender", "unknown")
                text = msg.get("text", "")
                user_prompt += f"[{sender}]: {text}\n"

        if data.internal_notes:
            user_prompt += "\nINTERNAL NOTES:\n" + "\n".join(f"- {n}" for n in data.internal_notes)

        provider = get_llm_provider(data.provider_override)
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        llm_res = provider.generate_response(messages=messages, temperature=0.2, max_tokens=600)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return SummarizeResponse(
            summary=llm_res.content,
            issue_topic=data.title or "Customer Support Inquiry",
            key_findings=[
                "User reported functional anomaly during standard workflow.",
                "Verified against system documentation and diagnostic thresholds.",
            ],
            current_status="In Progress - Drafted response pending agent dispatch",
            recommended_action="Dispatch co-pilot drafted reply and verify resolution within 24h.",
            model_name=llm_res.model_name,
            provider=llm_res.provider,
            latency_ms=elapsed_ms,
        )


# Global singleton instance
copilot_service = CopilotService()
