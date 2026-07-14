from __future__ import annotations

from importlib import import_module

from agent_os.adapters.model_adapter import ModelAdapter
from agent_os.adapters.registry import AdapterRegistry


class DynamicAdapterLoader:
    """Loads adapter classes dynamically and optionally registers them."""

    def __init__(self, registry: AdapterRegistry) -> None:
        self._registry = registry

    def load_class(self, reference: str) -> type[ModelAdapter]:
        module_name, class_name = self._split_reference(reference)
        module = import_module(module_name)
        candidate = getattr(module, class_name)

        if not isinstance(candidate, type) or not issubclass(candidate, ModelAdapter):
            raise TypeError("Loaded object must be a ModelAdapter subclass.")

        return candidate

    def load_and_register(
        self,
        reference: str,
        *,
        alias: str | None = None,
        default_kwargs: dict[str, object] | None = None,
    ) -> type[ModelAdapter]:
        adapter_class = self.load_class(reference)
        self._registry.register(
            alias=alias or adapter_class.__name__,
            adapter_class=adapter_class,
            default_kwargs=default_kwargs,
        )
        return adapter_class

    def _split_reference(self, reference: str) -> tuple[str, str]:
        if ":" in reference:
            module_name, class_name = reference.rsplit(":", maxsplit=1)
            return module_name, class_name

        parts = reference.rsplit(".", maxsplit=1)
        if len(parts) != 2:
            raise ValueError("Adapter reference must use 'module:ClassName' or 'module.ClassName' format.")

        return parts[0], parts[1]
