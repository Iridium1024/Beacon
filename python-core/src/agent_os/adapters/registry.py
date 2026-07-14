from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_os.adapters.model_adapter import ModelAdapter


@dataclass(frozen=True, slots=True)
class AdapterRegistration:
    """Registry entry describing a named model adapter type."""

    alias: str
    adapter_class: type[ModelAdapter]
    default_kwargs: Mapping[str, object] = field(default_factory=dict)


class AdapterRegistry:
    """Maps adapter aliases to concrete adapter classes."""

    def __init__(self) -> None:
        self._registrations: dict[str, AdapterRegistration] = {}

    def register(
        self,
        alias: str,
        adapter_class: type[ModelAdapter],
        *,
        default_kwargs: Mapping[str, object] | None = None,
    ) -> None:
        if not issubclass(adapter_class, ModelAdapter):
            raise TypeError("Registered adapter class must inherit from ModelAdapter.")

        self._registrations[alias] = AdapterRegistration(
            alias=alias,
            adapter_class=adapter_class,
            default_kwargs=dict(default_kwargs or {}),
        )

    def unregister(self, alias: str) -> None:
        self._registrations.pop(alias, None)

    def get(self, alias: str) -> AdapterRegistration:
        try:
            return self._registrations[alias]
        except KeyError as exc:
            raise KeyError(f"Adapter alias '{alias}' is not registered.") from exc

    def list(self) -> tuple[AdapterRegistration, ...]:
        return tuple(self._registrations.values())

    def create(self, alias: str, **overrides: object) -> ModelAdapter:
        registration = self.get(alias)
        kwargs = dict(registration.default_kwargs)
        kwargs.update(overrides)
        return registration.adapter_class(**kwargs)
