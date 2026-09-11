from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Sequence


class ClaudeActivationBackend(StrEnum):
    CLI = "cli"
    AGENT_SDK = "agent_sdk"


class ClaudeReplyWritebackMode(StrEnum):
    EXPLICIT_ONLY = "explicit_only"
    PROVIDER_FINAL_CAPTURE = "provider_final_capture"


@dataclass(frozen=True, slots=True)
class ClaudeControlSelection:
    value: str
    source: str
    legacy_alias: str | None = None

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "value": self.value,
            "source": self.source,
        }
        if self.legacy_alias is not None:
            result["legacyAlias"] = self.legacy_alias
        return result


@dataclass(frozen=True, slots=True)
class ClaudeControlConfig:
    activation_backend: ClaudeControlSelection
    reply_writeback_mode: ClaudeControlSelection

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "schema": "claude_control_config.v1",
            "activationBackend": self.activation_backend.to_metadata(),
            "replyWritebackMode": self.reply_writeback_mode.to_metadata(),
            "precedence": [
                "explicit_cli",
                "localRuntime.claudeControl",
                "profile (flat alias reported separately)",
                "backend_specific_default",
            ],
            "backendDefaults": {
                "cli": ClaudeReplyWritebackMode.PROVIDER_FINAL_CAPTURE.value,
                "agent_sdk": ClaudeReplyWritebackMode.EXPLICIT_ONLY.value,
            },
        }


def resolve_claude_control_config(
    profile: Mapping[str, object],
    *,
    activation_backend: object | None = None,
    reply_writeback_mode: object | None = None,
) -> ClaudeControlConfig:
    nested = profile.get("claudeControl")
    if nested is None:
        nested_mapping: Mapping[str, object] = {}
    elif isinstance(nested, Mapping):
        nested_mapping = nested
    else:
        raise ValueError("localRuntime.claudeControl must be a JSON object.")

    activation = _resolve_selection(
        explicit=activation_backend,
        nested=nested_mapping,
        nested_keys=("activationBackend", "activation_backend"),
        profile=profile,
        legacy_keys=("claudeActivationBackend", "claude_activation_backend"),
        allowed=tuple(item.value for item in ClaudeActivationBackend),
        default=ClaudeActivationBackend.CLI.value,
        default_source="default",
        field_name="activationBackend",
    )
    reply_default = (
        ClaudeReplyWritebackMode.PROVIDER_FINAL_CAPTURE.value
        if activation.value == ClaudeActivationBackend.CLI.value
        else ClaudeReplyWritebackMode.EXPLICIT_ONLY.value
    )
    reply_default_source = (
        "default_for_cli_compatibility"
        if activation.value == ClaudeActivationBackend.CLI.value
        else "default_for_agent_sdk"
    )
    return ClaudeControlConfig(
        activation_backend=activation,
        reply_writeback_mode=_resolve_selection(
            explicit=reply_writeback_mode,
            nested=nested_mapping,
            nested_keys=("replyWritebackMode", "reply_writeback_mode"),
            profile=profile,
            legacy_keys=("claudeReplyWritebackMode", "claude_reply_writeback_mode"),
            allowed=tuple(item.value for item in ClaudeReplyWritebackMode),
            default=reply_default,
            default_source=reply_default_source,
            field_name="replyWritebackMode",
        ),
    )


def normalize_claude_activation_backend(
    value: ClaudeActivationBackend | str,
) -> ClaudeActivationBackend:
    if isinstance(value, ClaudeActivationBackend):
        return value
    try:
        return ClaudeActivationBackend(str(value).strip())
    except ValueError as exc:
        raise ValueError("activationBackend must be one of: cli, agent_sdk.") from exc


def normalize_claude_reply_writeback_mode(
    value: ClaudeReplyWritebackMode | str,
) -> ClaudeReplyWritebackMode:
    if isinstance(value, ClaudeReplyWritebackMode):
        return value
    try:
        return ClaudeReplyWritebackMode(str(value).strip())
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
) -> ClaudeControlSelection:
    if explicit is not None:
        return ClaudeControlSelection(
            value=_validated_choice(explicit, allowed, field_name),
            source="explicit_cli",
        )
    for key in nested_keys:
        if nested.get(key) is not None:
            return ClaudeControlSelection(
                value=_validated_choice(nested[key], allowed, field_name),
                source="localRuntime.claudeControl",
            )
    for key in legacy_keys:
        if profile.get(key) is not None:
            return ClaudeControlSelection(
                value=_validated_choice(profile[key], allowed, field_name),
                source="profile",
                legacy_alias=key,
            )
    return ClaudeControlSelection(value=default, source=default_source)


def _validated_choice(value: object, allowed: Sequence[str], field_name: str) -> str:
    if not isinstance(value, str) or value.strip() not in allowed:
        raise ValueError(f"{field_name} must be one of: {', '.join(allowed)}.")
    return value.strip()
