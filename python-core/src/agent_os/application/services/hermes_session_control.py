from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Sequence


class HermesActivationBackend(StrEnum):
    CLI = "cli"
    TUI_GATEWAY = "tui_gateway"


class HermesReplyWritebackMode(StrEnum):
    EXPLICIT_ONLY = "explicit_only"
    PROVIDER_FINAL_CAPTURE = "provider_final_capture"


@dataclass(frozen=True, slots=True)
class HermesControlSelection:
    value: str
    source: str
    legacy_alias: str | None = None

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {"value": self.value, "source": self.source}
        if self.legacy_alias is not None:
            result["legacyAlias"] = self.legacy_alias
        return result


@dataclass(frozen=True, slots=True)
class HermesControlConfig:
    activation_backend: HermesControlSelection
    reply_writeback_mode: HermesControlSelection
    gateway_python: HermesControlSelection | None = None

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": "hermes_control_config.v1",
            "activationBackend": self.activation_backend.to_metadata(),
            "replyWritebackMode": self.reply_writeback_mode.to_metadata(),
            "precedence": [
                "explicit_cli",
                "localRuntime.hermesControl",
                "profile (flat alias reported separately)",
                "backend_specific_default",
            ],
            "backendDefaults": {
                "cli": HermesReplyWritebackMode.PROVIDER_FINAL_CAPTURE.value,
                "tui_gateway": HermesReplyWritebackMode.EXPLICIT_ONLY.value,
            },
        }
        if self.gateway_python is not None:
            result["gatewayPython"] = self.gateway_python.to_metadata()
        return result


def resolve_hermes_control_config(
    profile: Mapping[str, object],
    *,
    activation_backend: object | None = None,
    reply_writeback_mode: object | None = None,
    gateway_python: object | None = None,
) -> HermesControlConfig:
    nested = profile.get("hermesControl")
    if nested is None:
        nested_mapping: Mapping[str, object] = {}
    elif isinstance(nested, Mapping):
        nested_mapping = nested
    else:
        raise ValueError("localRuntime.hermesControl must be a JSON object.")

    activation = _resolve_selection(
        explicit=activation_backend,
        nested=nested_mapping,
        nested_keys=("activationBackend", "activation_backend"),
        profile=profile,
        legacy_keys=("hermesActivationBackend", "hermes_activation_backend"),
        allowed=tuple(item.value for item in HermesActivationBackend),
        default=HermesActivationBackend.CLI.value,
        default_source="default",
        field_name="activationBackend",
    )
    reply_default = (
        HermesReplyWritebackMode.PROVIDER_FINAL_CAPTURE.value
        if activation.value == HermesActivationBackend.CLI.value
        else HermesReplyWritebackMode.EXPLICIT_ONLY.value
    )
    reply_source = (
        "default_for_cli_compatibility"
        if activation.value == HermesActivationBackend.CLI.value
        else "default_for_tui_gateway"
    )
    python_selection = _resolve_optional_text_selection(
        explicit=gateway_python,
        nested=nested_mapping,
        nested_keys=("gatewayPython", "gateway_python"),
        profile=profile,
        legacy_keys=("hermesGatewayPython", "hermes_gateway_python"),
        field_name="gatewayPython",
    )
    return HermesControlConfig(
        activation_backend=activation,
        reply_writeback_mode=_resolve_selection(
            explicit=reply_writeback_mode,
            nested=nested_mapping,
            nested_keys=("replyWritebackMode", "reply_writeback_mode"),
            profile=profile,
            legacy_keys=("hermesReplyWritebackMode", "hermes_reply_writeback_mode"),
            allowed=tuple(item.value for item in HermesReplyWritebackMode),
            default=reply_default,
            default_source=reply_source,
            field_name="replyWritebackMode",
        ),
        gateway_python=python_selection,
    )


def normalize_hermes_activation_backend(
    value: HermesActivationBackend | str,
) -> HermesActivationBackend:
    if isinstance(value, HermesActivationBackend):
        return value
    try:
        return HermesActivationBackend(str(value).strip())
    except ValueError as exc:
        raise ValueError("activationBackend must be one of: cli, tui_gateway.") from exc


def normalize_hermes_reply_writeback_mode(
    value: HermesReplyWritebackMode | str,
) -> HermesReplyWritebackMode:
    if isinstance(value, HermesReplyWritebackMode):
        return value
    try:
        return HermesReplyWritebackMode(str(value).strip())
    except ValueError as exc:
        raise ValueError(
            "replyWritebackMode must be one of: explicit_only, "
            "provider_final_capture."
        ) from exc


def _resolve_selection(
    *,
    explicit: object | None,
    nested: Mapping[str, object],
    nested_keys: Sequence[str],
    profile: Mapping[str, object],
    legacy_keys: Sequence[str],
    allowed: Sequence[str],
    default: str,
    default_source: str,
    field_name: str,
) -> HermesControlSelection:
    if explicit is not None:
        return HermesControlSelection(
            value=_validated_choice(explicit, allowed, field_name),
            source="explicit_cli",
        )
    for key in nested_keys:
        if nested.get(key) is not None:
            return HermesControlSelection(
                value=_validated_choice(nested[key], allowed, field_name),
                source="localRuntime.hermesControl",
            )
    for key in legacy_keys:
        if profile.get(key) is not None:
            return HermesControlSelection(
                value=_validated_choice(profile[key], allowed, field_name),
                source="profile",
                legacy_alias=key,
            )
    return HermesControlSelection(value=default, source=default_source)


def _resolve_optional_text_selection(
    *,
    explicit: object | None,
    nested: Mapping[str, object],
    nested_keys: Sequence[str],
    profile: Mapping[str, object],
    legacy_keys: Sequence[str],
    field_name: str,
) -> HermesControlSelection | None:
    if explicit is not None:
        return HermesControlSelection(
            value=_validated_text(explicit, field_name), source="explicit_cli"
        )
    for key in nested_keys:
        if nested.get(key) is not None:
            return HermesControlSelection(
                value=_validated_text(nested[key], field_name),
                source="localRuntime.hermesControl",
            )
    for key in legacy_keys:
        if profile.get(key) is not None:
            return HermesControlSelection(
                value=_validated_text(profile[key], field_name),
                source="profile",
                legacy_alias=key,
            )
    return None


def _validated_choice(value: object, allowed: Sequence[str], field_name: str) -> str:
    if not isinstance(value, str) or value.strip() not in allowed:
        raise ValueError(f"{field_name} must be one of: {', '.join(allowed)}.")
    return value.strip()


def _validated_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text.")
    return value.strip()
