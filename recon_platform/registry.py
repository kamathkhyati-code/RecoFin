"""Tool registry: lets agents register and discover callable tools by name."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolSpec:
    name: str
    description: str
    func: Callable[..., Any]


class ToolRegistry:
    """Central registry of tools that agents can look up and call by name."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, description: str = ""):
        """Decorator to register a function as a named tool."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._tools[name] = ToolSpec(name=name, description=description, func=func)
            return func

        return decorator

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered")
        return self._tools[name]

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())


registry = ToolRegistry()


@registry.register(
    "dummy_echo_tool",
    description="Returns its input unchanged. Used to validate the registry works.",
)
def dummy_echo_tool(value: Any) -> Any:
    return value
