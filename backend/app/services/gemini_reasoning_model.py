"""Gemini-backed LLM reasoning layer for OPSYN.

``GeminiReasoningModel`` subclasses the Groq ``LLMReasoningModel`` so the two
providers share everything except transport:

* same ``ReasoningModel`` protocol (``evaluate_hypotheses`` /
  ``choose_next_step``) — the agent cannot tell providers apart;
* same prompts and context builder (``SYSTEM_PROMPT``,
  ``build_reasoning_context``), including the existing prompt-compaction
  limits (top 3 memories, truncated) and the "memories are fallible
  historical evidence" framing;
* same hidden-state audit (fail closed before any network call);
* same payload validation and guardrails (unknown actions/tools rejected,
  failed actions never repeated, low-confidence actions downgraded).

Only the network call differs: Gemini's ``generate_content`` with a JSON
response schema instead of Groq's chat-completions endpoint.

Error taxonomy mirrors Groq on purpose: ``GeminiReasoningError`` subclasses
``LLMReasoningError`` (and ``GeminiNotConfiguredError`` subclasses
``LLMNotConfiguredError``), so the agent and the evaluation harness record
Gemini failures as explicit reasoning failures — never as fabricated
decisions, and never via silent fallback to another provider.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.llm_reasoning_model import (
    LLMNotConfiguredError,
    LLMReasoningError,
    LLMReasoningModel,
    SYSTEM_PROMPT,
    assert_no_hidden_state_in_prompt,
    build_reasoning_context,
)
from app.services.reasoning_model import AgentState

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_TEMPERATURE = 0.0


class GeminiNotConfiguredError(LLMNotConfiguredError):
    """Raised when Gemini reasoning is selected without a usable API key."""


class GeminiReasoningError(LLMReasoningError):
    """Raised when Gemini cannot produce a valid reasoning decision.

    Subclasses ``LLMReasoningError`` so existing agent/harness handling
    applies unchanged. Never converted into a fabricated decision.
    """


def _to_gemini_schema(node: Any) -> Any:
    """Convert a Groq-style JSON-schema dict to Gemini's schema subset.

    Gemini response schemas do not support ``type`` unions (``["string",
    "null"]``), ``additionalProperties``, or ``null`` enum members. The
    conversion is lossy only where the code-level Pydantic validation
    (``ReasoningDecision`` / ``Hypothesis``) already enforces the real
    contract on the parsed payload.
    """
    if isinstance(node, dict):
        converted: dict[str, Any] = {}
        for key, value in node.items():
            if key == "additionalProperties":
                continue
            if key == "type" and isinstance(value, list):
                non_null = [t for t in value if t != "null" and t is not None]
                converted["type"] = non_null[0] if non_null else "string"
                continue
            if key == "enum" and isinstance(value, list):
                converted["enum"] = [entry for entry in value if entry is not None]
                continue
            converted[key] = _to_gemini_schema(value)
        return converted
    if isinstance(node, (list, tuple)):
        return [_to_gemini_schema(item) for item in node]
    return node


def _is_transient(error: Exception) -> bool:
    message = str(error).lower()
    if any(
        marker in message
        for marker in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "overloaded",
            "unavailable",
            "resource_exhausted",
            "resourceexhausted",
            "deadline_exceeded",
            "deadlineexceeded",
            "temporarily",
            "try again",
        )
    ):
        return True
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "code", None)
    if status in (408, 409, 429) or (isinstance(status, int) and status >= 500):
        return True
    name = type(error).__name__.lower()
    return any(
        marker in name
        for marker in (
            "timeout",
            "overloaded",
            "unavailable",
            "retry",
            "ratelimit",
            "rate_limit",
            "serviceunavailable",
            "internal",
        )
    )


class GeminiReasoningModel(LLMReasoningModel):
    """Gemini-backed implementation of the ``ReasoningModel`` protocol.

    Synchronous (the agent calls reasoning synchronously). Accepts an
    injected client for tests; otherwise builds ``genai.Client`` from the
    API key. The injected client only needs
    ``client.models.generate_content(model=..., contents=...,
    config=...)`` returning an object with a ``.text`` attribute.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
        timeout_s: float = 60.0,
        max_retries: int = 2,
        max_output_tokens: int = 4096,
        temperature: float = DEFAULT_TEMPERATURE,
        client: Any | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise GeminiNotConfiguredError(
                "GEMINI_API_KEY is not set. Configure it to use "
                "REASONING_MODEL=gemini; refusing to silently fall back to "
                "another provider."
            )
        if not model or not model.strip():
            raise GeminiNotConfiguredError("GEMINI_MODEL must not be empty.")
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key)
        # Reuse the shared counters/metrics/validation plumbing. The Groq
        # transport is never used: this class overrides _structured_call.
        super().__init__(
            api_key=api_key,
            model=model,
            timeout_s=timeout_s,
            max_retries=max_retries,
            max_completion_tokens=max_output_tokens,
            client=client,
        )
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._reasoning_effort = "n/a"

    @classmethod
    def from_settings(
        cls, settings: Any, client: Any | None = None
    ) -> "GeminiReasoningModel":
        return cls(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_s=settings.gemini_timeout_s,
            max_retries=settings.gemini_max_retries,
            max_output_tokens=getattr(settings, "gemini_max_output_tokens", 4096),
            client=client,
        )

    @property
    def temperature(self) -> float:
        return self._temperature

    # -- Gemini transport --------------------------------------------------

    def _structured_call(
        self,
        context: str,
        instruction: str,
        json_schema: dict[str, Any],
        task: str,
    ) -> dict[str, Any]:
        user_prompt = f"{instruction}\n\n{context}"
        full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"
        # Fail closed BEFORE any network call.
        assert_no_hidden_state_in_prompt(full_prompt)

        response_schema = _to_gemini_schema(json_schema.get("schema", {}))
        attempts = 1 + self._max_retries
        last_error: Exception | None = None
        contents = user_prompt
        for attempt in range(attempts):
            try:
                started = time.perf_counter()
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=self._generation_config(response_schema),
                )
                self._llm_latency_ms += (time.perf_counter() - started) * 1000.0
                self._llm_calls += 1
                return self._parse_payload(self._extract_text(response), task)
            except LLMReasoningError as exc:
                # Malformed/validation failures: one clarifying retry, then stop.
                last_error = exc
                self._llm_errors += 1
                logger.warning("Gemini malformed response (task=%s): %s", task, exc)
                if attempt < attempts - 1:
                    self._llm_retries += 1
                    contents = (
                        "Your previous response was not valid for the "
                        "required JSON schema. Return ONLY a JSON "
                        "object matching the schema, no prose.\n\n" + user_prompt
                    )
                    # Re-audit: the repair wrapper adds no ground truth, but
                    # verify anyway before retrying.
                    assert_no_hidden_state_in_prompt(
                        SYSTEM_PROMPT + "\n\n" + contents
                    )
                continue
            except Exception as exc:
                last_error = exc
                self._llm_errors += 1
                logger.warning("Gemini call failed (task=%s): %r", task, exc)
                if _is_transient(exc) and attempt < attempts - 1:
                    self._llm_retries += 1
                    continue
                raise GeminiReasoningError(f"Gemini call failed: {exc}") from exc
        raise GeminiReasoningError(
            f"Gemini produced no valid response after {attempts} attempt(s): "
            f"{last_error}"
        )

    def _generation_config(self, response_schema: dict[str, Any]) -> Any:
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=response_schema,
            max_output_tokens=self._max_output_tokens,
            temperature=self._temperature,
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        try:
            text = response.text
        except Exception as exc:
            raise GeminiReasoningError(
                f"Gemini response had no usable text: {exc}"
            ) from exc
        if not text or not str(text).strip():
            raise GeminiReasoningError("Gemini response had no usable text.")
        return str(text)


def reasoning_context_for_state(state: AgentState) -> str:
    """Build and audit the Gemini prompt for a state. Test/audit entrypoint.

    Identical construction to the Groq path by design: same observable
    context, same compaction, same audit.
    """
    prompt = f"{SYSTEM_PROMPT}\n\n{build_reasoning_context(state)}"
    assert_no_hidden_state_in_prompt(prompt)
    return prompt
