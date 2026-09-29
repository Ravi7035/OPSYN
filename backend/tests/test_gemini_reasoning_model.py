"""Tests for the Gemini-backed reasoning layer.

The Gemini SDK is always faked in unit tests — no network, no API key.
No live-Gemini test exists here by design (quota discipline); live
verification is done manually via the API flow, never in the suite.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.agent_tools import ACTION_TOOLS, OBSERVATION_TOOLS
from app.services.gemini_reasoning_model import (
    DEFAULT_GEMINI_MODEL,
    GeminiNotConfiguredError,
    GeminiReasoningError,
    GeminiReasoningModel,
    _to_gemini_schema,
    reasoning_context_for_state,
)
from app.services.llm_reasoning_model import (
    LLMNotConfiguredError,
    LLMReasoningError,
    assert_no_hidden_state_in_prompt,
    audit_prompt_for_hidden_state,
)
from app.services.reasoning_model import AgentState, ReasoningDecision

# --- fake Gemini client --------------------------------------------------------


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeGeminiClient:
    """Stands in for genai.Client; records calls, replays canned payloads."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.models = self._Models(self)

    class _Models:
        def __init__(self, outer: "FakeGeminiClient") -> None:
            self._outer = outer

        def generate_content(self, **kwargs: Any) -> Any:
            self._outer.requests.append(kwargs)
            if not self._outer._responses:
                raise AssertionError("FakeGeminiClient ran out of responses")
            item = self._outer._responses.pop(0)
            if isinstance(item, Exception):
                raise item
            if isinstance(item, str):
                return _FakeResponse(item)
            import json as _json

            return _FakeResponse(_json.dumps(item))


# --- fixtures -----------------------------------------------------------------


def _decision_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "act",
        "tool": None,
        "action": "clear_db_connections",
        "target": None,
        "reasoning": "DB connections saturated with high latency; memory agrees.",
        "hypothesis": "DB pool exhaustion",
        "confidence": 0.87,
    }
    payload.update(overrides)
    return payload


def _hypotheses_payload() -> dict[str, Any]:
    return {
        "hypotheses": [
            {
                "statement": "DB pool exhaustion",
                "status": "supported",
                "confidence": 0.85,
                "supporting": ["db_connections saturated (100/100)"],
                "contradicting": [],
            },
            {
                "statement": "bad deployment",
                "status": "rejected",
                "confidence": 0.1,
                "supporting": [],
                "contradicting": ["no recent deployment (v1.4.2 healthy)"],
            },
            {
                "statement": "memory leak",
                "status": "rejected",
                "confidence": 0.05,
                "supporting": [],
                "contradicting": ["memory normal (47.8%)"],
            },
            {
                "statement": "redis failure",
                "status": "rejected",
                "confidence": 0.05,
                "supporting": [],
                "contradicting": ["redis healthy"],
            },
            {
                "statement": "dependency timeout",
                "status": "rejected",
                "confidence": 0.05,
                "supporting": [],
                "contradicting": ["dependency latency normal (35ms)"],
            },
            {
                "statement": "traffic spike",
                "status": "rejected",
                "confidence": 0.05,
                "supporting": [],
                "contradicting": ["request rate normal (120)"],
            },
            {
                "statement": "cache stampede",
                "status": "rejected",
                "confidence": 0.05,
                "supporting": [],
                "contradicting": ["cache healthy"],
            },
            {
                "statement": "disk exhaustion",
                "status": "rejected",
                "confidence": 0.05,
                "supporting": [],
                "contradicting": ["disk utilization normal (42%)"],
            },
        ]
    }


def _full_state() -> AgentState:
    return AgentState(
        incident_id="INC-TEST-1",
        observations={
            "get_health": {"service": "payment-api", "status": "degraded"},
            "get_metrics": {
                "db_connections": 100,
                "db_connection_limit": 100,
                "db_latency_ms": 900,
                "http_5xx_rate": 25.0,
                "cpu": 45.0,
                "memory": 47.8,
            },
            "get_state": {"status": "degraded"},
            "get_logs": {"logs": ["ERROR payment request failed"]},
        },
        observation_history=[],
        recalled_memories=[
            {
                "text": "Previous incident with saturated DB connections "
                "was resolved by clearing DB connections.",
                "score": 0.9,
            }
        ],
        investigation_count=4,
        action_count=0,
        failed_actions=[],
        successful_actions=[],
        tools_used=["get_health", "get_metrics", "get_state", "get_logs"],
        action_results=[
            {
                "action": "restart_redis",
                "status": "executed",
                "result": "no significant change observed",
            }
        ],
        verification={"improved": False, "status": "pending"},
    )


def _model(*responses: Any, **kwargs: Any) -> GeminiReasoningModel:
    kwargs.setdefault("max_retries", 0)
    return GeminiReasoningModel(
        api_key="test-key", client=FakeGeminiClient(list(responses)), **kwargs
    )


# --- 1/2: valid responses map to domain objects --------------------------------


def test_valid_structured_hypotheses_response() -> None:
    model = _model(_hypotheses_payload())
    hypotheses = model.evaluate_hypotheses(
        {"get_metrics": {"db_connections": 100}}, [], [], []
    )
    assert len(hypotheses) == 8
    by_statement = {h.statement: h for h in hypotheses}
    assert by_statement["DB pool exhaustion"].status == "supported"
    assert by_statement["DB pool exhaustion"].confidence == pytest.approx(0.85)
    assert by_statement["bad deployment"].status == "rejected"


def test_decision_converted_to_reasoning_decision() -> None:
    model = _model(_decision_payload())
    decision = model.choose_next_step(_full_state())
    assert isinstance(decision, ReasoningDecision)
    assert decision.type == "act"
    assert decision.action == "clear_db_connections"
    assert decision.hypothesis == "DB pool exhaustion"
    assert decision.confidence == pytest.approx(0.87)
    assert "DB connections saturated" in decision.reasoning
    assert model.metrics["llm_calls"] == 1
    assert model.metrics["model_name"] == DEFAULT_GEMINI_MODEL


def test_investigate_decision_uses_registered_tool() -> None:
    model = _model(
        _decision_payload(type="investigate", tool="get_snapshot", action=None)
    )
    decision = model.choose_next_step(_full_state())
    assert decision.type == "investigate"
    assert decision.tool in OBSERVATION_TOOLS


def test_unknown_action_rejected_not_executed() -> None:
    model = _model(_decision_payload(action="reboot_everything"))
    # Shared payload validation raises the base error loudly; the harness
    # records it as an explicit reasoning failure either way.
    with pytest.raises(LLMReasoningError, match="unknown action"):
        model.choose_next_step(_full_state())


# --- 3: invalid response handling (fail loudly, no fabrication) ----------------


def test_malformed_json_response_raises() -> None:
    model = _model("this is not json {{{")
    with pytest.raises(GeminiReasoningError):
        model.choose_next_step(_full_state())
    assert model.metrics["llm_errors"] >= 1


def test_schema_violating_response_raises() -> None:
    model = _model({"type": "act"})  # missing reasoning; action not allowed
    with pytest.raises(LLMReasoningError, match="unknown action"):
        model.choose_next_step(_full_state())


def test_unknown_hypothesis_statement_raises() -> None:
    model = _model(
        {
            "hypotheses": [
                {
                    "statement": "alien invasion",
                    "status": "supported",
                    "confidence": 0.99,
                }
            ]
        }
    )
    with pytest.raises(LLMReasoningError, match="unknown hypothesis"):
        model.evaluate_hypotheses({}, [], [], [])


def test_repeated_failed_action_rejected() -> None:
    model = _model(_decision_payload(action="restart_redis"))
    state = _full_state()
    state.failed_actions = ["restart_redis"]
    with pytest.raises(LLMReasoningError, match="failed action"):
        model.choose_next_step(state)


def test_gemini_errors_are_llm_errors_for_harness() -> None:
    # The evaluation harness records isinstance(exc, LLMReasoningError) as an
    # explicit error outcome; anything else would surface as a harness bug.
    assert issubclass(GeminiReasoningError, LLMReasoningError)
    assert issubclass(GeminiNotConfiguredError, LLMNotConfiguredError)


# --- 4: missing configuration fails loudly -------------------------------------


def test_missing_api_key_raises() -> None:
    with pytest.raises(GeminiNotConfiguredError, match="GEMINI_API_KEY"):
        GeminiReasoningModel(api_key="  ", client=FakeGeminiClient([]))


def test_empty_model_raises() -> None:
    with pytest.raises(GeminiNotConfiguredError, match="GEMINI_MODEL"):
        GeminiReasoningModel(api_key="k", model="  ", client=FakeGeminiClient([]))


def test_gemini_mode_without_key_fails_loudly() -> None:
    from app.config.settings import Settings

    settings = Settings(_env_file=None, GEMINI_API_KEY="")  # type: ignore[call-arg]
    assert settings.is_gemini_configured is False
    with pytest.raises(GeminiNotConfiguredError):
        GeminiReasoningModel.from_settings(settings, client=FakeGeminiClient([]))


def test_settings_defaults_match() -> None:
    from app.config.settings import Settings

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.gemini_model == "gemini-3.5-flash"
    assert settings.gemini_max_output_tokens >= 4096
    assert settings.is_gemini_configured is False
    # Groq configuration untouched.
    assert settings.groq_model == "openai/gpt-oss-120b"
    assert settings.groq_reasoning_effort == "high"


def test_reasoning_selection_supports_gemini_without_fallback() -> None:
    import app.core.dependencies as dependencies
    from fastapi import HTTPException

    get_settings = dependencies.get_settings
    try:
        dependencies.get_settings = lambda: FakeGeminiSettings()  # type: ignore[assignment]
        dependencies.get_reasoning_model.cache_clear()
        with pytest.raises(HTTPException) as exc_info:
            dependencies.get_reasoning_model()
        assert exc_info.value.status_code == 503
    finally:
        dependencies.get_settings = get_settings
        dependencies.get_reasoning_model.cache_clear()


class FakeGeminiSettings:
    def __init__(self) -> None:
        self.reasoning_model = "gemini"
        self.gemini_api_key = ""
        self.gemini_model = "gemini-3.5-flash"
        self.gemini_timeout_s = 5.0
        self.gemini_max_retries = 0
        self.gemini_max_output_tokens = 1024


# --- 5: API error handling (bounded retries, no silent fallback) ----------------


def test_gemini_api_failure_raises_without_fabrication() -> None:
    model = _model(RuntimeError("boom"))
    with pytest.raises(GeminiReasoningError, match="Gemini call failed"):
        model.choose_next_step(_full_state())
    assert model.metrics["llm_calls"] == 0
    assert model.metrics["llm_errors"] == 1


def test_transient_failure_retries_then_succeeds() -> None:
    class OverloadedError(Exception):
        status_code = 503

    model = GeminiReasoningModel(
        api_key="test-key",
        client=FakeGeminiClient([OverloadedError("overloaded"), _decision_payload()]),
        max_retries=2,
    )
    decision = model.choose_next_step(_full_state())
    assert decision.type == "act"
    assert model.metrics["llm_retries"] == 1
    assert model.metrics["llm_calls"] == 1


def test_transient_failure_exhausts_bounded_retries() -> None:
    class OverloadedError(Exception):
        status_code = 503

    model = GeminiReasoningModel(
        api_key="test-key",
        client=FakeGeminiClient([OverloadedError("x")] * 5),
        max_retries=2,
    )
    with pytest.raises(GeminiReasoningError):
        model.choose_next_step(_full_state())
    assert model.metrics["llm_retries"] == 2


def test_non_transient_400_is_not_retried() -> None:
    class BadRequestError(Exception):
        status_code = 400

    model = GeminiReasoningModel(
        api_key="test-key",
        client=FakeGeminiClient([BadRequestError("invalid argument")] * 3),
        max_retries=2,
    )
    with pytest.raises(GeminiReasoningError, match="Gemini call failed"):
        model.choose_next_step(_full_state())
    assert model.metrics["llm_retries"] == 0


# --- 6/7: safety boundary + fallible memories ------------------------------------


def test_forbidden_tokens_cover_required_secrets() -> None:
    from app.services.llm_reasoning_model import FORBIDDEN_PROMPT_TOKENS

    for secret in ("active_fault", "expected_action", "root_cause", "fault_type"):
        assert secret in FORBIDDEN_PROMPT_TOKENS, secret


def test_audit_rejects_hidden_state() -> None:
    with pytest.raises(LLMReasoningError):
        assert_no_hidden_state_in_prompt("fault was active_fault=db_pool_exhaustion")
    assert audit_prompt_for_hidden_state("clean observable metrics") == []


def test_full_state_prompt_is_clean() -> None:
    prompt = reasoning_context_for_state(_full_state())
    assert audit_prompt_for_hidden_state(prompt) == []
    for secret in ("active_fault", "expected_action", "root_cause", "fault_type"):
        assert secret not in prompt.lower(), secret


def test_hidden_state_blocks_network_call() -> None:
    client = FakeGeminiClient([_decision_payload()])
    model = GeminiReasoningModel(api_key="k", client=client, max_retries=0)
    state = _full_state()
    state.observations["get_logs"] = {
        "logs": ["INFO scenario=db_pool_exhaustion injected for evaluation"]
    }
    with pytest.raises(LLMReasoningError, match="forbidden token"):
        model.choose_next_step(state)
    assert client.requests == [], "no request may be sent after audit failure"


def _sent_user_content(client: FakeGeminiClient) -> str:
    assert client.requests, "expected at least one Gemini request"
    return str(client.requests[0]["contents"])


def test_observable_evidence_reaches_model() -> None:
    client = FakeGeminiClient([_decision_payload()])
    GeminiReasoningModel(api_key="k", client=client, max_retries=0).choose_next_step(
        _full_state()
    )
    prompt = _sent_user_content(client)
    for token in ("100", "900", "25.0", "payment-api", "ERROR payment request failed"):
        assert token in prompt, token


def test_hindsight_memories_reach_model_as_fallible_evidence() -> None:
    client = FakeGeminiClient([_decision_payload()])
    GeminiReasoningModel(api_key="k", client=client, max_retries=0).choose_next_step(
        _full_state()
    )
    prompt = _sent_user_content(client)
    assert "Previous incident with saturated DB connections" in prompt
    assert "NOT ground truth" in prompt


def test_request_uses_structured_output_and_model() -> None:
    client = FakeGeminiClient([_decision_payload()])
    GeminiReasoningModel(api_key="k", client=client, max_retries=0).choose_next_step(
        _full_state()
    )
    request = client.requests[0]
    assert request["model"] == "gemini-3.5-flash"
    config = request["config"]
    assert config.response_mime_type == "application/json"
    assert "hypothesis" in str(config.response_schema)


def test_gemini_schema_conversion_drops_unsupported_keywords() -> None:
    converted = _to_gemini_schema(
        {
            "type": "object",
            "properties": {
                "tool": {"type": ["string", "null"], "enum": ["get_logs", None]},
                "confidence": {"type": ["number", "null"]},
            },
            "required": ["type"],
            "additionalProperties": False,
        }
    )
    assert converted["properties"]["tool"]["type"] == "string"
    assert converted["properties"]["tool"]["enum"] == ["get_logs"]
    assert converted["properties"]["confidence"]["type"] == "number"
    assert "additionalProperties" not in converted


# --- 8: failed-action context preserved ------------------------------------------


def test_failed_actions_reach_model() -> None:
    client = FakeGeminiClient([_decision_payload()])
    GeminiReasoningModel(api_key="k", client=client, max_retries=0).choose_next_step(
        _full_state()
    )
    prompt = _sent_user_content(client)
    assert "restart_redis" in prompt
    assert "no significant change observed" in prompt


def test_low_confidence_action_downgraded_to_investigation() -> None:
    model = _model(_decision_payload(confidence=0.1))
    decision = model.choose_next_step(_full_state())
    assert decision.type == "investigate"
    assert decision.tool == "get_snapshot"


# --- 9: both protocol operations --------------------------------------------------


def test_evaluate_hypotheses_and_choose_next_step_share_transport() -> None:
    client = FakeGeminiClient([_hypotheses_payload(), _decision_payload()])
    model = GeminiReasoningModel(api_key="k", client=client, max_retries=0)
    hypotheses = model.evaluate_hypotheses({"get_metrics": {}}, [], [], [])
    assert len(hypotheses) == 8
    decision = model.choose_next_step(_full_state())
    assert isinstance(decision, ReasoningDecision)
    assert len(client.requests) == 2
    assert model.metrics["llm_calls"] == 2


# --- 10: agent consumes Gemini decisions -------------------------------------------


@pytest.mark.asyncio
async def test_agent_consumes_gemini_decision_end_to_end() -> None:
    from app.models.incident import Incident, IncidentSource
    from app.services.agent import IncidentResponseAgent, InMemoryHindsight
    from app.services.agent_tools import AgentTools
    from app.services.payment_simulator import PaymentSimulator

    simulator = PaymentSimulator()
    simulator.inject_fault("db_pool_exhaustion")
    client = FakeGeminiClient([_hypotheses_payload(), _decision_payload()])
    model = GeminiReasoningModel(api_key="k", client=client, max_retries=0)
    agent = IncidentResponseAgent(
        reasoning_model=model,  # type: ignore[arg-type]
        tools=AgentTools(simulator),
        hindsight=InMemoryHindsight(),
    )
    result = await agent.run(
        Incident(
            incident_id="INC-GEMINI-E2E",
            service="payment-api",
            source=IncidentSource.SIMULATOR,
        )
    )
    assert result.learning is not None
    assert result.learning.outcome == "resolved"
    assert "clear_db_connections" in result.learning.successful_actions
    for request in client.requests:
        blob = str(request["contents"]).lower()
        for secret in ("active_fault", "expected_action", "root_cause", "fault_type"):
            assert secret not in blob, secret
