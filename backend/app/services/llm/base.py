"""
Abstract Base Class and Data Models for LLM Provider Adapters.
Ensures the platform is completely decoupled from any single generative AI vendor.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str = Field(..., description="Role: system, user, or assistant")
    content: str = Field(..., description="Message text content")


class LLMResponse(BaseModel):
    content: str = Field(..., description="Generated text completion")
    prompt_tokens: int = Field(default=0, description="Input tokens consumed")
    completion_tokens: int = Field(default=0, description="Generated tokens")
    total_tokens: int = Field(default=0, description="Total tokens consumed")
    latency_ms: float = Field(default=0.0, description="Round-trip latency in milliseconds")
    model_name: str = Field(..., description="Exact model version used")
    provider: str = Field(..., description="Provider identifier (e.g. mock, gemini, openai)")


class BaseLLMProvider(ABC):
    """Abstract interface that all hosted and mock LLM provider adapters must implement."""

    @abstractmethod
    def generate_response(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> LLMResponse:
        """Generates a text completion for a sequence of chat messages."""
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Verifies provider credentials and connectivity."""
        pass

    @abstractmethod
    def get_provider_info(self) -> Dict[str, Any]:
        """Returns provider metadata, model name, and configuration."""
        pass
