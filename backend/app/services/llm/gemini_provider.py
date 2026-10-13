"""
Hosted Google Gemini LLM Provider Adapter.
Uses Google Gemini API with timeout bounds and token tracking.
"""
import time
import logging
from typing import List, Dict, Any, Optional
import httpx

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)


class GeminiLLMProvider(BaseLLMProvider):
    """
    Adapter for Google Gemini models (e.g. gemini-1.5-flash, gemini-2.0-flash).
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.LLM_API_KEY
        self.model_name = model_name or settings.LLM_MODEL_NAME or "gemini-1.5-flash"
        self.provider_id = "gemini"
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_id,
            "model_name": self.model_name,
            "has_api_key": bool(self.api_key),
            "status": "configured" if self.api_key else "missing_key",
        }

    def health_check(self) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "status": "unhealthy",
                "provider": self.provider_id,
                "error": "LLM_API_KEY environment variable is not configured.",
            }
        return {
            "status": "healthy",
            "provider": self.provider_id,
            "model_name": self.model_name,
        }

    def generate_response(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> LLMResponse:
        start_time = time.perf_counter()

        if not self.api_key:
            logger.warning("Gemini API key missing. Returning fallback notice.")
            return LLMResponse(
                content="[Configuration Notice] Gemini API key is not configured in environment variables. Please set LLM_API_KEY or switch LLM_PROVIDER to 'mock'.",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=1.0,
                model_name=self.model_name,
                provider=self.provider_id,
            )

        # Convert messages to Gemini contents structure
        contents = []
        system_instruction = None

        for m in messages:
            if m.role == "system":
                system_instruction = {"parts": [{"text": m.content}]}
            else:
                role = "user" if m.role == "user" else "model"
                contents.append({"role": role, "parts": [{"text": m.content}]})

        request_body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_instruction:
            request_body["systemInstruction"] = system_instruction

        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key}

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(self.api_url, params=params, json=request_body, headers=headers)
                elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

                if res.status_code != 200:
                    logger.error("Gemini API returned HTTP %d: %s", res.status_code, res.text)
                    return LLMResponse(
                        content="We encountered an issue communicating with our generative AI service. Please try again shortly or request agent support.",
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        latency_ms=elapsed_ms,
                        model_name=self.model_name,
                        provider=self.provider_id,
                    )

                data = res.json()
                text_out = ""
                candidates = data.get("candidates", [])
                if candidates and "content" in candidates[0]:
                    parts = candidates[0]["content"].get("parts", [])
                    text_out = "".join(p.get("text", "") for p in parts)

                usage_meta = data.get("usageMetadata", {})
                p_tokens = usage_meta.get("promptTokenCount", 0)
                c_tokens = usage_meta.get("candidatesTokenCount", 0)

                return LLMResponse(
                    content=text_out.strip(),
                    prompt_tokens=p_tokens,
                    completion_tokens=c_tokens,
                    total_tokens=p_tokens + c_tokens,
                    latency_ms=elapsed_ms,
                    model_name=self.model_name,
                    provider=self.provider_id,
                )

        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            logger.error("Gemini request exception: %s", str(exc))
            return LLMResponse(
                content=f"An error occurred while contacting the AI provider ({str(exc)}). Escalating to support team.",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=elapsed_ms,
                model_name=self.model_name,
                provider=self.provider_id,
            )
