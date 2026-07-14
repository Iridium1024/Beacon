from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from agent_os.domain.value_objects.enums import MessageRole


class ModelCapabilityKind(StrEnum):
    """Provider-neutral capability labels for model metadata."""

    TEXT_GENERATION = "text_generation"
    EMBEDDING = "embedding"
    VISION = "vision"
    TOOL_CALLING = "tool_calling"
    STREAMING = "streaming"
    REASONING = "reasoning"
    LOCAL_PRECISION = "local_precision"


@dataclass(frozen=True, slots=True)
class ModelCapability:
    """Capability metadata without implying the capability is executable."""

    kind: ModelCapabilityKind | str
    implemented: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = _model_capability_kind(self.kind)
        object.__setattr__(self, "kind", kind)

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "kind": self.kind.value,
            "implemented": self.implemented,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ModelGenerationOptions:
    """Provider-neutral generation options safe to map into adapters."""

    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    stop: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.temperature is not None and self.temperature < 0:
            raise ValueError("temperature must be non-negative.")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive.")
        if self.top_p is not None and not 0 < self.top_p <= 1:
            raise ValueError("top_p must be greater than 0 and at most 1.")
        _validate_unique_non_empty(self.stop, "stop")

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object] | None,
    ) -> "ModelGenerationOptions":
        if source is None:
            return cls()
        allowed = {"temperature", "max_tokens", "maxTokens", "top_p", "topP", "stop"}
        _reject_unknown_keys(source, allowed, "generation_options")
        return cls(
            temperature=_optional_float(source, "temperature"),
            max_tokens=_optional_int(source, "max_tokens", "maxTokens"),
            top_p=_optional_float(source, "top_p", "topP"),
            stop=_optional_string_tuple(source, "stop"),
        )

    def to_parameters(self) -> Mapping[str, object]:
        parameters: dict[str, object] = {}
        if self.temperature is not None:
            parameters["temperature"] = self.temperature
        if self.max_tokens is not None:
            parameters["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            parameters["top_p"] = self.top_p
        if self.stop:
            parameters["stop"] = list(self.stop)
        return parameters


@dataclass(frozen=True, slots=True)
class ModelReasoningOptions:
    """Provider-neutral reasoning knobs reserved for capable adapters."""

    reasoning_effort: str | None = None
    thinking_budget_tokens: int | None = None
    verbosity: str | None = None

    def __post_init__(self) -> None:
        if self.reasoning_effort is not None:
            _require_non_empty(self.reasoning_effort, "reasoning_effort")
        if self.thinking_budget_tokens is not None and self.thinking_budget_tokens <= 0:
            raise ValueError("thinking_budget_tokens must be positive.")
        if self.verbosity is not None:
            _require_non_empty(self.verbosity, "verbosity")

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object] | None,
    ) -> "ModelReasoningOptions":
        if source is None:
            return cls()
        allowed = {
            "reasoning_effort",
            "reasoningEffort",
            "thinking_budget_tokens",
            "thinkingBudgetTokens",
            "verbosity",
        }
        _reject_unknown_keys(source, allowed, "reasoning_options")
        return cls(
            reasoning_effort=_optional_text(
                source,
                "reasoning_effort",
                "reasoningEffort",
            ),
            thinking_budget_tokens=_optional_int(
                source,
                "thinking_budget_tokens",
                "thinkingBudgetTokens",
            ),
            verbosity=_optional_text(source, "verbosity"),
        )

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {}
        if self.reasoning_effort is not None:
            metadata["reasoning_effort"] = self.reasoning_effort
        if self.thinking_budget_tokens is not None:
            metadata["thinking_budget_tokens"] = self.thinking_budget_tokens
        if self.verbosity is not None:
            metadata["verbosity"] = self.verbosity
        return metadata


@dataclass(frozen=True, slots=True)
class ModelRuntimeConstraints:
    """Model runtime metadata that does not start a local model runtime."""

    context_window_tokens: int | None = None
    precision: str | None = None
    quantization: str | None = None

    def __post_init__(self) -> None:
        if self.context_window_tokens is not None and self.context_window_tokens <= 0:
            raise ValueError("context_window_tokens must be positive.")
        if self.precision is not None:
            _require_non_empty(self.precision, "precision")
        if self.quantization is not None:
            _require_non_empty(self.quantization, "quantization")

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object] | None,
    ) -> "ModelRuntimeConstraints":
        if source is None:
            return cls()
        allowed = {
            "context_window_tokens",
            "contextWindowTokens",
            "precision",
            "quantization",
        }
        _reject_unknown_keys(source, allowed, "runtime_constraints")
        return cls(
            context_window_tokens=_optional_int(
                source,
                "context_window_tokens",
                "contextWindowTokens",
            ),
            precision=_optional_text(source, "precision"),
            quantization=_optional_text(source, "quantization"),
        )

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {}
        if self.context_window_tokens is not None:
            metadata["context_window_tokens"] = self.context_window_tokens
        if self.precision is not None:
            metadata["precision"] = self.precision
        if self.quantization is not None:
            metadata["quantization"] = self.quantization
        return metadata


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """Provider-neutral model input message."""

    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    """Provider-neutral generation request."""

    provider_name: str
    model_name: str
    messages: tuple[ModelMessage, ...]
    system_prompt: str | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelOutput:
    """Provider-neutral generation response."""

    model_name: str
    content: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    """Provider-neutral embedding request."""

    provider_name: str
    model_name: str
    inputs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Provider-neutral embedding response."""

    model_name: str
    vectors: tuple[tuple[float, ...], ...]


def _model_capability_kind(value: ModelCapabilityKind | str) -> ModelCapabilityKind:
    if isinstance(value, ModelCapabilityKind):
        return value
    try:
        return ModelCapabilityKind(value)
    except ValueError as exc:
        valid = ", ".join(kind.value for kind in ModelCapabilityKind)
        raise ValueError(f"model capability kind must be one of: {valid}.") from exc


def _validate_unique_non_empty(values: tuple[str, ...], field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        _require_non_empty(value, field_name)
        if value in seen:
            raise ValueError(f"{field_name} must not contain duplicate values.")
        seen.add(value)


def _reject_unknown_keys(
    source: Mapping[str, object],
    allowed: set[str],
    logical_name: str,
) -> None:
    unknown = sorted(key for key in source if key not in allowed)
    if unknown:
        raise ValueError(
            f"{logical_name} contains unsupported field: {unknown[0]}."
        )


def _optional_text(source: Mapping[str, object], *keys: str) -> str | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{keys[0]} must be a non-empty string.")
    return value.strip()


def _optional_float(source: Mapping[str, object], *keys: str) -> float | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{keys[0]} must be a number.")
    return float(value)


def _optional_int(source: Mapping[str, object], *keys: str) -> int | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{keys[0]} must be an integer.")
    return value


def _optional_string_tuple(
    source: Mapping[str, object],
    *keys: str,
) -> tuple[str, ...]:
    value = _optional_value(source, *keys)
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{keys[0]} must be a string or list of strings.")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{keys[0]} must be a string or list of strings.")
    return tuple(item.strip() for item in value)


def _optional_value(source: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in source:
            return source[key]
    return None


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
