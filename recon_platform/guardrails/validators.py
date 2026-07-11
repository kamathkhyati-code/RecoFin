"""Pydantic-based output validation with retry-on-invalid."""

from __future__ import annotations

from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class GuardrailError(Exception):
    """Raised when an agent's output still fails validation after all retries."""


def validate_with_retry(
    model: type[T],
    generate_fn: Callable[[], str],
    max_retries: int = 2,
) -> T:
    """Call generate_fn(), validate its output against `model`, retrying on failure.

    generate_fn should return a JSON string. If validation fails, generate_fn
    is called again up to max_retries times before raising GuardrailError
    with the last validation error attached.
    """
    last_error: Exception | None = None

    for _ in range(max_retries + 1):
        raw = generate_fn()
        try:
            return model.model_validate_json(raw)
        except ValidationError as exc:
            last_error = exc
            continue

    raise GuardrailError(
        f"Agent output failed validation after {max_retries + 1} attempts: {last_error}"
    )
