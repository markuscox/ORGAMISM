"""Google Gemini API provider using GEMINI_API_KEY, retry backoff, and secret redaction."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from organism.safety.policy import SecurityPolicy
from .provider import (
    MissingCredentialsError,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderError,
    QuotaExhaustedError,
)


class GeminiProvider(ModelProvider):
    """Minimal stdlib REST adapter for Google Gemini API (free-tier safe)."""

    provider_name = "gemini"
    ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(
        self,
        model_name: str = "gemini-4-hydrogen",
        timeout_seconds: int = 20,
        max_retries: int = 2,
        backoff_base_seconds: float = 1.0,
    ) -> None:
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds

    @staticmethod
    def _api_key() -> str:
        return os.environ.get("GEMINI_API_KEY", "").strip()

    def is_configured(self) -> bool:
        key = self._api_key()
        return bool(key) and key != "MY_GEMINI_API_KEY"

    def generate(self, request: ModelRequest) -> ModelResponse:
        api_key = self._api_key()
        if not api_key or api_key == "MY_GEMINI_API_KEY":
            raise MissingCredentialsError("GEMINI_API_KEY is not configured in the server/runner environment.")

        safe_prompt, _ = SecurityPolicy.redact_secrets(request.prompt)
        safe_system, _ = SecurityPolicy.redact_secrets(request.system_instruction)

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": safe_prompt}]}],
            "generationConfig": {"maxOutputTokens": request.max_output_tokens},
        }
        if safe_system:
            body["systemInstruction"] = {"parts": [{"text": safe_system}]}

        url = self.ENDPOINT_TEMPLATE.format(model=self.model_name)
        encoded = json.dumps(body).encode("utf-8")

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(
                url,
                data=encoded,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                    "User-Agent": "aistudio-build",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                return self._parse_response(raw)
            except urllib.error.HTTPError as exc:
                status = exc.code
                detail = exc.read().decode("utf-8", errors="replace")[:240]
                detail_safe, _ = SecurityPolicy.redact_secrets(detail)
                if status == 429:
                    last_err = QuotaExhaustedError(f"Gemini HTTP 429 rate/quota limit: {detail_safe}")
                    if attempt < self.max_retries:
                        time.sleep(self.backoff_base_seconds * (2**attempt))
                        continue
                    raise last_err
                if status >= 500 and attempt < self.max_retries:
                    last_err = ProviderError(f"Gemini HTTP {status}: {detail_safe}")
                    time.sleep(self.backoff_base_seconds * (2**attempt))
                    continue
                raise ProviderError(f"Gemini HTTP {status}: {detail_safe}") from exc
            except urllib.error.URLError as exc:
                last_err = ProviderError(f"Gemini network error: {exc.reason}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base_seconds * (2**attempt))
                    continue
                raise last_err from exc

        raise ProviderError(f"Gemini request failed after retries: {last_err}")

    def _parse_response(self, raw: dict[str, Any]) -> ModelResponse:
        candidates = raw.get("candidates", [])
        text_parts: list[str] = []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for p in parts:
                if "text" in p:
                    text_parts.append(str(p["text"]))

        usage = raw.get("usageMetadata", {})
        prompt_tokens = int(usage.get("promptTokenCount", 0))
        completion_tokens = int(usage.get("candidatesTokenCount", 0))
        total_tokens = int(usage.get("totalTokenCount", prompt_tokens + completion_tokens))

        return ModelResponse(
            text="\n".join(text_parts).strip(),
            provider=self.provider_name,
            model_name=self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
