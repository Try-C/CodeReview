"""DeepSeek LLM client with usage tracking per spec §12.5.

Provides LLMClient (production, calls DeepSeek API) and FakeLLMClient
(tests, returns pre-configured responses).
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.llm.usage import (
    LLMCallResult,
    PricingSnapshot,
    calculate_estimated_cost,
)

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    """Provider-neutral generation boundary used by structured callers."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMCallResult:
        """Return generated content together with immutable usage metadata."""


class UnavailableLLMProvider:
    """Fail with a stable error when generation credentials are not configured."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMCallResult:
        del messages, temperature, max_tokens, json_mode
        raise LLMClientError("LLM_PROVIDER_UNAVAILABLE")


# ── Production client ────────────────────────────────────────────────────────


class LLMClient:
    """Async client for the DeepSeek chat-completions API.

    Every call captures a PricingSnapshot so historical costs survive supplier
    price changes.  Cost is unavailable when the pricing version is unconfigured.
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        input_price_per_million: Decimal = Decimal("0"),
        output_price_per_million: Decimal = Decimal("0"),
        pricing_currency: str = "USD",
        pricing_version: str = "unconfigured",
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._pricing = PricingSnapshot(
            model=model,
            input_price_per_million=input_price_per_million,
            output_price_per_million=output_price_per_million,
            currency=pricing_currency,
            version=pricing_version,
        )
        self._cost_available = pricing_version != "unconfigured"
        self._timeout = timeout

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMCallResult:
        """Send a chat-completion request and return the LLMCallResult.

        Set json_mode=True to request JSON output from the model (adds
        response_format={'type': 'json_object'} to the payload).  DeepSeek's
        API is OpenAI-compatible and respects this parameter.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._temperature,
            "max_tokens": max_tokens if max_tokens is not None else self._max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        started = time.monotonic()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)

        if response.status_code != 200:
            logger.error("llm_api_error status=%d", response.status_code)
            raise LLMClientError(f"DeepSeek API returned status {response.status_code}")

        body = response.json()
        choices = body.get("choices", [])
        if not choices:
            logger.error("llm_api_empty_choices status=%d body_keys=%s", response.status_code, list(body.keys()))
            raise LLMClientError(f"DeepSeek API returned {response.status_code} with empty choices array")
        choice = choices[0]
        usage = body.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        cost_status: str = "available" if self._cost_available else "unavailable"
        estimated_cost = (
            calculate_estimated_cost(input_tokens, output_tokens, self._pricing)
            if self._cost_available
            else None
        )

        return LLMCallResult(
            content=choice["message"]["content"],
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_status=cost_status,
            estimated_cost=estimated_cost,
            latency_ms=elapsed_ms,
            pricing=self._pricing,
        )


# ── Fake client for tests ────────────────────────────────────────────────────


class FakeLLMClient:
    """Test double that returns a fixed response without making API calls.

    Usage:
        fake = FakeLLMClient(response_text='{"items": []}')
        result = await fake.chat([{"role": "user", "content": "test"}])
    """

    def __init__(
        self,
        response_text: str = "{}",
        *,
        model: str = "fake",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self._response = response_text
        self._model = model
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._pricing = PricingSnapshot(
            model=model,
            input_price_per_million=Decimal("0"),
            output_price_per_million=Decimal("0"),
            currency="USD",
            version="test",
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> LLMCallResult:
        return LLMCallResult(
            content=self._response,
            provider="fake",
            model=self._model,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cost_status="unavailable",
            estimated_cost=None,
            latency_ms=1,
            pricing=self._pricing,
        )


# ── Errors ───────────────────────────────────────────────────────────────────


class LLMClientError(RuntimeError):
    """Raised when the LLM API returns a non-200 or network error."""
