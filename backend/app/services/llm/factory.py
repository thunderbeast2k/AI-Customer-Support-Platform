"""
LLM Provider Factory.
Instantiates the configured LLM adapter based on environment settings.
"""
from app.core.config import settings
from app.services.llm.base import BaseLLMProvider
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.gemini_provider import GeminiLLMProvider


def get_llm_provider(provider_override: str = None) -> BaseLLMProvider:
    """
    Returns the configured LLM provider instance.
    Defaults to MockLLMProvider if LLM_PROVIDER is 'mock' or if keys are missing.
    """
    provider_type = (provider_override or settings.LLM_PROVIDER).lower().strip()

    if provider_type == "gemini":
        return GeminiLLMProvider()
    elif provider_type == "mock":
        return MockLLMProvider(model_name=settings.LLM_MODEL_NAME)
    else:
        # Fallback to mock provider
        return MockLLMProvider()
