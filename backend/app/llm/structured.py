"""Structured LLM output helper — validates JSON responses against Pydantic models.

Per spec §14: all LLM outputs must pass Pydantic validation.  A single JSON
repair retry is attempted when the initial parse fails (§5: MAX_JSON_REPAIR_RETRIES=1).
"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

from pydantic import BaseModel

from app.llm.client import LLMProvider
from app.llm.usage import LLMCallResult, combine_call_results

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)

# Maximum JSON repair retries per spec §5.
_MAX_JSON_REPAIR_RETRIES = 1


class StructuredLLM:
    """Wraps an LLM client (real or fake) and returns validated Pydantic models."""

    def __init__(self, client: LLMProvider) -> None:
        self._client = client

    async def invoke(
        self,
        messages: list[dict[str, str]],
        response_model: type[_T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[_T, LLMCallResult]:
        """Call the LLM, parse and validate JSON, return (model, call_result).

        On parse failure, retries once with a repair prompt.  If both attempts
        fail a StructuredOutputError is raised.
        """
        result = await self._client.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )

        parsed = self._parse_with_repair(result.content, response_model)
        if parsed is not None:
            return parsed, result

        # One repair retry.
        logger.warning("structured_output_repair_attempt raw=%s", result.content[:500])
        repair_messages = [
            *messages,
            {"role": "assistant", "content": result.content},
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON that matches the "
                    f"expected schema ({response_model.__name__}).  Please fix any "
                    "syntax errors (trailing commas, unescaped strings, missing "
                    "brackets) and output only the corrected JSON object."
                ),
            },
        ]
        result2 = await self._client.chat(
            repair_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        parsed = self._parse_with_repair(result2.content, response_model)
        if parsed is not None:
            return parsed, combine_call_results(result, result2)

        raise StructuredOutputError(
            (
                f"Failed to parse {response_model.__name__} after "
                f"{_MAX_JSON_REPAIR_RETRIES + 1} attempts"
            ),
            result=combine_call_results(result, result2),
        )

    @staticmethod
    def extract_json(text: str) -> str:
        """Extract the outermost JSON object or array from text.

        Handles cases where the model wraps JSON in markdown code fences
        or prefixes with explanatory text.
        """
        # Try to find JSON inside ```json ... ``` fences.
        start = text.find("```json")
        if start != -1:
            start = text.find("\n", start) + 1
            end = text.find("```", start)
            if end != -1:
                return text[start:end].strip()

        # Try to find the outermost { } or [ ].
        for opener, closer in (("{", "}"), ("[", "]")):
            s = text.find(opener)
            if s != -1:
                e = text.rfind(closer)
                if e > s:
                    return text[s : e + 1]
        return text.strip()

    @staticmethod
    def _parse_with_repair(
        raw: str,
        model: type[_T],
    ) -> _T | None:
        """Attempt JSON extraction + Pydantic parse; return None on failure."""
        cleaned = StructuredLLM.extract_json(raw)
        try:
            data = json.loads(cleaned)
            return model.model_validate(data)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("structured_output_parse_failed %s", exc)
            return None


class StructuredOutputError(RuntimeError):
    """Raised when structured output parsing fails after all retries."""

    def __init__(self, message: str, *, result: LLMCallResult) -> None:
        super().__init__(message)
        self.result = result
