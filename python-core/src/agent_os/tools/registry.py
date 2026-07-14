from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_os.tools.tool_interface import Tool


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    """Registry entry describing a named pluggable tool type."""

    alias: str
    tool_class: type[Tool]
    default_kwargs: Mapping[str, object] = field(default_factory=dict)


class ToolRegistry:
    """Maps tool aliases to concrete pluggable tool classes."""

    def __init__(self) -> None:
        self._registrations: dict[str, ToolRegistration] = {}

    def register(
        self,
        alias: str,
        tool_class: type[Tool],
        *,
        default_kwargs: Mapping[str, object] | None = None,
    ) -> None:
        if not issubclass(tool_class, Tool):
            raise TypeError("Registered tool class must implement Tool.")

        self._registrations[alias] = ToolRegistration(
            alias=alias,
            tool_class=tool_class,
            default_kwargs=dict(default_kwargs or {}),
        )

    def unregister(self, alias: str) -> None:
        self._registrations.pop(alias, None)

    def get(self, alias: str) -> ToolRegistration:
        try:
            return self._registrations[alias]
        except KeyError as exc:
            raise KeyError(f"Tool alias '{alias}' is not registered.") from exc

    def list(self) -> tuple[ToolRegistration, ...]:
        return tuple(self._registrations.values())

    def create(self, alias: str, **overrides: object) -> Tool:
        registration = self.get(alias)
        kwargs = dict(registration.default_kwargs)
        kwargs.update(overrides)
        return registration.tool_class(**kwargs)
