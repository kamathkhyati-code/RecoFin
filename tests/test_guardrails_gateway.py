from pydantic import BaseModel

from recon_platform.guardrails.validators import GuardrailError, validate_with_retry
from recon_platform.gateway.llm_gateway import MockLLMGateway


class DummyOutput(BaseModel):
    result: str


def test_valid_output_returns_immediately():
    gateway = MockLLMGateway(canned_response='{"result": "ok"}')
    result = validate_with_retry(DummyOutput, lambda: gateway.generate("hi"))
    assert result.result == "ok"


def test_invalid_then_valid_retries_and_succeeds():
    responses = iter(["not json", '{"result": "ok"}'])

    def flaky_generate():
        return next(responses)

    result = validate_with_retry(DummyOutput, flaky_generate, max_retries=2)
    assert result.result == "ok"


def test_always_invalid_raises_guardrail_error_cleanly():
    def always_broken():
        return "still not json"

    try:
        validate_with_retry(DummyOutput, always_broken, max_retries=1)
        assert False, "expected GuardrailError"
    except GuardrailError:
        pass


def test_mock_gateway_returns_canned_response_and_tracks_usage():
    gateway = MockLLMGateway(canned_response='{"result": "ok"}')
    text = gateway.generate("hello world")
    assert text == '{"result": "ok"}'
    assert gateway.usage.calls == 1
    assert gateway.usage.prompt_tokens > 0
