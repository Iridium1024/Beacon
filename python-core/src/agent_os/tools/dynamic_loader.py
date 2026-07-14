from __future__ import annotations

from importlib import import_module

from agent_os.tools.registry import ToolRegistry
from agent_os.tools.tool_interface import Tool


class DynamicToolLoader:
    """Loads pluggable tool classes dynamically and optionally registers them."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def load_class(self, reference: str) -> type[Tool]:
        module_name, class_name = self._split_reference(reference)
        module = import_module(module_name)
        candidate = getattr(module, class_name)

        if not isinstance(candidate, type) or not issubclass(candidate, Tool):
            raise TypeError("Loaded tool reference must resolve to a Tool subclass.")

        return candidate

    def load_and_register(
        self,
        reference: str,
        *,
        alias: str | None = None,
        default_kwargs: dict[str, object] | None = None,
    ) -> type[Tool]:
        tool_class = self.load_class(reference)
        self._registry.register(
            alias=alias or tool_class.__name__,
            tool_class=tool_class,
            default_kwargs=default_kwargs,
        )
        return tool_class

    def _split_reference(self, reference: str) -> tuple[str, str]:
        if ":" in reference:
            module_name, class_name = reference.rsplit(":", maxsplit=1)
            return module_name, class_name

        parts = reference.rsplit(".", maxsplit=1)
        if len(parts) != 2:
            raise ValueError("Tool reference must use 'module:ClassName' or 'module.ClassName' format.")

        return parts[0], parts[1]
