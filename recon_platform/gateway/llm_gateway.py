"""LLM gateway abstraction.

Agents call generate() against this interface, never a provider SDK
directly. That's what makes the provider swappable and makes tests able
to use a canned mock instead of hitting a real API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class UsageStats:
    """Running token/cost totals for a gateway instance."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.calls += 1


class LLMGateway(ABC):
    """Common interface every LLM provider integration must implement."""

    def __init__(self) -> None:
        self.usage = UsageStats()

    @abstractmethod
    def _call(self, prompt: str) -> tuple[str, int, int]:
        """Return (response_text, prompt_tokens, completion_tokens)."""

    def generate(self, prompt: str) -> str:
        text, prompt_tokens, completion_tokens = self._call(prompt)
        self.usage.record(prompt_tokens, completion_tokens)
        return text


class MockLLMGateway(LLMGateway):
    """Returns a canned response. Used in tests so agents never hit a real API."""

    def __init__(self, canned_response: str = '{"result": "ok"}') -> None:
        super().__init__()
        self.canned_response = canned_response

    def _call(self, prompt: str) -> tuple[str, int, int]:
        return (
            self.canned_response,
            len(prompt.split()),
            len(self.canned_response.split()),
        )


class GroqLLMGateway(LLMGateway):
    """Real provider gateway backed by langchain-groq. Requires GROQ_API_KEY.

    Imported lazily inside __init__ so mock-only tests never need credentials
    or the langchain-groq client loaded.
    """

    def __init__(self, model: str = "llama-3.1-8b-instant") -> None:
        super().__init__()
        from langchain_groq import ChatGroq

        self._client = ChatGroq(model=model)

    def _call(self, prompt: str) -> tuple[str, int, int]:
        response = self._client.invoke(prompt)
        usage = response.response_metadata.get("token_usage", {})
        return (
            response.content,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )
