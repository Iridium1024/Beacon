from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Sequence


class AgentDispatchDeliveryMode(StrEnum):
    WORKER_EXECUTE = "worker_execute"
    QUEUED = "queued"


class AgentDispatchExternalOperation(StrEnum):
    SEND = "send"
    QUEUE = "queue"
    SUPPLEMENT = "supplement"
    STATUS = "status"


class AgentDispatchExecutionStrategy(StrEnum):
    INLINE = "inline"
    QUEUE = "queue"
    DRY_RUN = "dry_run"
    ASYNC_SUBMIT = "async_submit"


class AgentDispatchImmediateBusyPolicy(StrEnum):
    RETURN_TO_SENDER = "return_to_sender"
    QUEUE_NEXT_TURN = "queue_next_turn"


@dataclass(frozen=True, slots=True)
class AgentDispatchControlSelection:
    value: str
    source: str

    def to_metadata(self) -> Mapping[str, object]:
        return {"value": self.value, "source": self.source}


@dataclass(frozen=True, slots=True)
class AgentDispatchControlConfig:
    default_delivery_mode: AgentDispatchControlSelection
    immediate_busy_policy: AgentDispatchControlSelection

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "schema": "agent_dispatch_control_config.v1",
            "defaultDeliveryMode": self.default_delivery_mode.to_metadata(),
            "immediateBusyPolicy": self.immediate_busy_policy.to_metadata(),
            "precedence": [
                "explicit_cli",
                "localRuntime.dispatchControl",
                "default",
            ],
        }


@dataclass(frozen=True, slots=True)
class AgentDispatchSemanticMapping:
    external_operation: AgentDispatchExternalOperation
    execution_strategy: AgentDispatchExecutionStrategy
    legacy_delivery_mode: str | None
    compatibility_alias: bool = False

    def to_metadata(self) -> Mapping[str, object]:
        result: dict[str, object] = {
            "schema": "agent_dispatch_semantic_mapping.v1",
            "externalOperation": self.external_operation.value,
            "executionStrategy": self.execution_strategy.value,
            "compatibilityAlias": self.compatibility_alias,
        }
        if self.legacy_delivery_mode is not None:
            result["legacyDeliveryMode"] = self.legacy_delivery_mode
        return result


_DELIVERY_MODE_MAPPINGS: Mapping[str, AgentDispatchSemanticMapping] = {
    AgentDispatchDeliveryMode.WORKER_EXECUTE.value: AgentDispatchSemanticMapping(
        external_operation=AgentDispatchExternalOperation.SEND,
        execution_strategy=AgentDispatchExecutionStrategy.INLINE,
        legacy_delivery_mode=AgentDispatchDeliveryMode.WORKER_EXECUTE.value,
        compatibility_alias=True,
    ),
    AgentDispatchDeliveryMode.QUEUED.value: AgentDispatchSemanticMapping(
        external_operation=AgentDispatchExternalOperation.QUEUE,
        execution_strategy=AgentDispatchExecutionStrategy.QUEUE,
        legacy_delivery_mode=AgentDispatchDeliveryMode.QUEUED.value,
        compatibility_alias=True,
    ),
    "worker_dry_run": AgentDispatchSemanticMapping(
        external_operation=AgentDispatchExternalOperation.SEND,
        execution_strategy=AgentDispatchExecutionStrategy.DRY_RUN,
        legacy_delivery_mode="worker_dry_run",
        compatibility_alias=True,
    ),
}


def agent_dispatch_semantic_mapping(
    delivery_mode: object,
) -> AgentDispatchSemanticMapping:
    if not isinstance(delivery_mode, str):
        raise ValueError("deliveryMode must be a string.")
    mapping = _DELIVERY_MODE_MAPPINGS.get(delivery_mode.strip())
    if mapping is None:
        raise ValueError(
            "deliveryMode must be one of: worker_execute, queued, worker_dry_run."
        )
    return mapping


def effective_agent_dispatch_semantic_mapping(
    delivery_mode: object,
    *,
    dry_run: bool = False,
) -> AgentDispatchSemanticMapping:
    mapping = agent_dispatch_semantic_mapping(delivery_mode)
    if not dry_run:
        return mapping
    return AgentDispatchSemanticMapping(
        external_operation=AgentDispatchExternalOperation.SEND,
        execution_strategy=AgentDispatchExecutionStrategy.DRY_RUN,
        legacy_delivery_mode=mapping.legacy_delivery_mode,
        compatibility_alias=mapping.compatibility_alias,
    )


def resolve_agent_dispatch_delivery_mode(
    *,
    delivery_mode: object | None,
    wait_mode: object | None,
    queued: bool,
    default_selection: AgentDispatchControlSelection,
) -> AgentDispatchControlSelection:
    if wait_mode == "once" and queued:
        raise ValueError("--wait once cannot be combined with --queued.")
    if wait_mode == "once":
        if delivery_mode is not None and delivery_mode != "worker_execute":
            raise ValueError(
                "--wait once requires --delivery-mode worker_execute when both "
                "are provided."
            )
        return AgentDispatchControlSelection(
            value=AgentDispatchDeliveryMode.WORKER_EXECUTE.value,
            source="explicit_cli",
        )
    if queued:
        if delivery_mode is not None and delivery_mode != "queued":
            raise ValueError(
                "--queued requires --delivery-mode queued when both are provided."
            )
        return AgentDispatchControlSelection(
            value=AgentDispatchDeliveryMode.QUEUED.value,
            source="explicit_cli",
        )
    if delivery_mode is not None:
        mapping = agent_dispatch_semantic_mapping(delivery_mode)
        return AgentDispatchControlSelection(
            value=str(mapping.legacy_delivery_mode),
            source="explicit_cli",
        )
    return default_selection


def resolve_agent_dispatch_control_config(
    profile: Mapping[str, object],
    *,
    default_delivery_mode: object | None = None,
    immediate_busy_policy: object | None = None,
) -> AgentDispatchControlConfig:
    nested = profile.get("dispatchControl")
    if nested is None:
        nested_mapping: Mapping[str, object] = {}
    elif isinstance(nested, Mapping):
        nested_mapping = nested
    else:
        raise ValueError("localRuntime.dispatchControl must be a JSON object.")

    return AgentDispatchControlConfig(
        default_delivery_mode=_resolve_selection(
            explicit=default_delivery_mode,
            nested=nested_mapping,
            nested_keys=("defaultDeliveryMode", "default_delivery_mode"),
            allowed=tuple(item.value for item in AgentDispatchDeliveryMode),
            default=AgentDispatchDeliveryMode.WORKER_EXECUTE.value,
            field_name="defaultDeliveryMode",
        ),
        immediate_busy_policy=_resolve_selection(
            explicit=immediate_busy_policy,
            nested=nested_mapping,
            nested_keys=("immediateBusyPolicy", "immediate_busy_policy"),
            allowed=tuple(item.value for item in AgentDispatchImmediateBusyPolicy),
            default=AgentDispatchImmediateBusyPolicy.RETURN_TO_SENDER.value,
            field_name="immediateBusyPolicy",
        ),
    )


def _resolve_selection(
    *,
    explicit: object | None,
    nested: Mapping[str, object],
    nested_keys: Sequence[str],
    allowed: Sequence[str],
    default: str,
    field_name: str,
) -> AgentDispatchControlSelection:
    if explicit is not None:
        return AgentDispatchControlSelection(
            value=_validated_choice(explicit, allowed, field_name),
            source="explicit_cli",
        )
    for key in nested_keys:
        if nested.get(key) is not None:
            return AgentDispatchControlSelection(
                value=_validated_choice(nested[key], allowed, field_name),
                source="localRuntime.dispatchControl",
            )
    return AgentDispatchControlSelection(value=default, source="default")


def _validated_choice(value: object, allowed: Sequence[str], field_name: str) -> str:
    if not isinstance(value, str) or value.strip() not in allowed:
        raise ValueError(f"{field_name} must be one of: {', '.join(allowed)}.")
    return value.strip()
