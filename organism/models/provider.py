"""Provider-independent LLM interface so Gemini can be replaced without kernel rewrites."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderError(RuntimeError):
    """Base error for model provider failures."""


class QuotaExhaustedError(ProviderError):
    """Raised when provider or local budget quota is exhausted."""


class MissingCredentialsError(ProviderError):
    """Raised when required provider credentials are unavailable."""


@dataclass(frozen=True)
class ModelRequest:
    system_instruction: str
    prompt: str
    max_output_tokens: int = 512
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    raw_status: str = "ok"


class ModelProvider(ABC):
    """Abstract interface allowing drop-in replacement of Gemini with local/other models."""

    provider_name: str = "abstract"

    @abstractmethod
    def generate(self, request: ModelRequest) -> ModelResponse:
        """Execute inference and return structured token accounting."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials or local engine are ready."""
