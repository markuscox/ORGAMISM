"""Google Gemini API provider using GEMINI_API_KEY, retry backoff, error handling, and secret redaction."""

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
        model_name: str = "gemini-3.8-flash",
        timeout_seconds: int = 20,
        max_retries: int = 2,
        backoff_base_seconds: float = 1.0,
        opener: Any = None,
    ) -> None:
        self.model_name = (model_name or "gemini-3.8-flash").strip()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self._opener = opener or urllib.request.urlopen

    @staticmethod
    def _api_key() -> str:
        return os.environ.get("GEMINI_API_KEY", "").strip()

    def is_configured(self) -> bool:
        key = self._api_key()
        return bool(key) and key != "MY_GEMINI_API_KEY"

    @staticmethod
    def _sanitize_error_text(raw_text: str, api_key: str) -> str:
        cleaned = raw_text.replace(api_key, "[REDACTED_GEMINI_API_KEY]") if api_key else raw_text
        cleaned, _ = SecurityPolicy.redact_secrets(cleaned)
        return cleaned

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
                with self._opener(req, timeout=self.timeout_seconds) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                return self._parse_response(raw, api_key=api_key)
            except urllib.error.HTTPError as exc:
                status = exc.code
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                detail_safe = self._sanitize_error_text(detail, api_key)
                if status == 429:
                    last_err = QuotaExhaustedError(f"Gemini HTTP 429 rate/quota limit: {detail_safe}")
                    if attempt < self.max_retries:
                        time.sleep(self.backoff_base_seconds * (2**attempt))
                        continue
                    raise last_err from None
                if status >= 500 and attempt < self.max_retries:
                    last_err = ProviderError(f"Gemini HTTP {status}: {detail_safe}")
                    time.sleep(self.backoff_base_seconds * (2**attempt))
                    continue
                raise ProviderError(f"Gemini HTTP {status} ({self.model_name}): {detail_safe}") from None
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                msg = self._sanitize_error_text(str(getattr(exc, "reason", exc)), api_key)
                last_err = ProviderError(f"Gemini network/parse error ({self.model_name}): {msg}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base_seconds * (2**attempt))
                    continue
                raise last_err from None

        raise ProviderError(f"Gemini request failed after retries: {last_err}")

    def _parse_response(self, raw: dict[str, Any], api_key: str = "") -> ModelResponse:
        if isinstance(raw, dict) and "error" in raw:
            err_msg = self._sanitize_error_text(json.dumps(raw["error"])[:240], api_key)
            raise ProviderError(f"Gemini API returned error payload: {err_msg}")

        candidates = raw.get("candidates", []) if isinstance(raw, dict) else []
        text_parts: list[str] = []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for p in parts:
                if "text" in p:
                    text_parts.append(str(p["text"]))

        text = "\n".join(text_parts).strip()
        if not text:
            finish_reason = candidates[0].get("finishReason", "UNKNOWN") if candidates else "NO_CANDIDATES"
            raise ProviderError(
                f"Gemini returned empty text for model '{self.model_name}' (finishReason={finish_reason})."
            )

        usage = raw.get("usageMetadata", {})
        prompt_tokens = int(usage.get("promptTokenCount", 0))
        completion_tokens = int(usage.get("candidatesTokenCount", 0))
        total_tokens = int(usage.get("totalTokenCount", prompt_tokens + completion_tokens))

        return ModelResponse(
            text=text,
            provider=self.provider_name,
            model_name=self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
