"""Shared pure contact and reply-reachability policies; no runtime assembly."""
from __future__ import annotations
from typing import Mapping, Sequence
from collections.abc import Mapping as MappingABC
from agent_os.application.services.agent_endpoint import normalize_agent_endpoint_alias


def dispatch_backend_capture(provider, backend, reply_writeback=None):
    """Existing CLI capture defaults shared with other application entries."""
    if provider == "deepseek_harness":
        backend, capture = "sdk_stdio", "provider_final_capture"
    elif provider in {"claude", "hermes"}:
        capture = reply_writeback or ("provider_final_capture" if backend == "cli" else "explicit_only")
    elif provider == "codex":
        capture = reply_writeback
    else:
        raise ValueError("core dispatch target provider is unsupported")
    if capture not in {"explicit_only", "provider_final_capture"}:
        raise ValueError("invalid provider reply writeback mode")
    return backend, capture

def _required_list_text(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("contact policy values must be non-empty strings.")
    return stripped


def _text_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("contact policy lists must be arrays of strings.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("contact policy lists must be arrays of strings.")
        result.append(item)
    return tuple(result)


def _contact_policy_profile(
    endpoint: Mapping[str, object],
) -> Mapping[str, tuple[str, ...]]:
    metadata = endpoint.get("metadata")
    profiles: list[Mapping[str, object]] = []
    if isinstance(metadata, MappingABC):
        for key in ("contactPolicyProfile", "contactAllowlist"):
            value = metadata.get(key)
            if isinstance(value, MappingABC):
                profiles.append(value)
        profiles.append(metadata)
    merged: dict[str, tuple[str, ...]] = {}
    for output_key, input_keys, normalize_alias in (
        (
            "allowedSourceEndpointAliases",
            ("allowedSourceEndpointAliases", "allowSourceEndpointAliases"),
            True,
        ),
        (
            "allowedSourceAgentIds",
            ("allowedSourceAgentIds", "allowSourceAgentIds"),
            False,
        ),
        (
            "allowedSourceProviderHandleIds",
            (
                "allowedSourceProviderHandleIds",
                "allowedSourceHandleIds",
                "allowSourceProviderHandleIds",
                "allowSourceHandleIds",
            ),
            False,
        ),
        (
            "blockedSourceEndpointAliases",
            ("blockedSourceEndpointAliases", "blockSourceEndpointAliases"),
            True,
        ),
        (
            "blockedSourceAgentIds",
            ("blockedSourceAgentIds", "blockSourceAgentIds"),
            False,
        ),
        (
            "blockedSourceProviderHandleIds",
            (
                "blockedSourceProviderHandleIds",
                "blockedSourceHandleIds",
                "blockSourceProviderHandleIds",
                "blockSourceHandleIds",
            ),
            False,
        ),
    ):
        values: list[str] = []
        for profile in profiles:
            for key in input_keys:
                for value in _text_tuple(profile.get(key)):
                    normalized = (
                        normalize_agent_endpoint_alias(value)
                        if normalize_alias
                        else _required_list_text(value)
                    )
                    if normalized not in values:
                        values.append(normalized)
        merged[output_key] = tuple(values)
    return merged


def _contact_policy_source_facts(
    source_endpoint: Mapping[str, object] | None,
) -> Mapping[str, object]:
    if source_endpoint is None:
        return {
            "sourceEndpointAlias": None,
            "sourceAgentId": None,
            "sourceProviderHandleId": None,
        }
    return {
        "sourceEndpointAlias": source_endpoint.get("alias"),
        "sourceAgentId": source_endpoint.get("agentId"),
        "sourceProviderHandleId": source_endpoint.get("providerHandleId"),
    }


def _contact_policy_has_rules(
    profile: Mapping[str, tuple[str, ...]],
    prefix: str,
) -> bool:
    return any(values for key, values in profile.items() if key.startswith(prefix))


def _matched_contact_policy_rules(
    profile: Mapping[str, tuple[str, ...]],
    *,
    source_facts: Mapping[str, object],
    prefix: str,
) -> tuple[Mapping[str, object], ...]:
    mappings = (
        ("SourceEndpointAliases", "sourceEndpointAlias"),
        ("SourceAgentIds", "sourceAgentId"),
        ("SourceProviderHandleIds", "sourceProviderHandleId"),
    )
    matches: list[Mapping[str, object]] = []
    for suffix, fact_key in mappings:
        profile_key = f"{prefix}{suffix}"
        source_value = source_facts.get(fact_key)
        if not isinstance(source_value, str):
            continue
        if source_value in profile.get(profile_key, ()):
            matches.append(
                {
                    "field": profile_key,
                    "sourceFact": fact_key,
                    "value": source_value,
                }
            )
    return tuple(matches)


def _dispatch_contact_policy_decision(
    *,
    source_endpoint: Mapping[str, object] | None,
    target_endpoint: Mapping[str, object] | None,
    reply_policy: str,
) -> Mapping[str, object]:
    source_facts = _contact_policy_source_facts(source_endpoint)
    if target_endpoint is None:
        return {
            "schema": "agent_dispatch_contact_policy_decision.v1",
            "targetEndpointAliasResolved": False,
            "targetContactPolicy": None,
            "decision": "not_applicable",
            "requiresSourceEndpoint": False,
            "sourceEndpointAliasResolved": source_endpoint is not None,
            "sourceFacts": source_facts,
        }
    contact_policy = str(target_endpoint.get("contactPolicy") or "open")
    if contact_policy == "block_all":
        raise ValueError("target endpoint contactPolicy blocks incoming dispatch.")
    contact_profile = _contact_policy_profile(target_endpoint)
    matched_block = _matched_contact_policy_rules(
        contact_profile,
        source_facts=source_facts,
        prefix="blocked",
    )
    if matched_block:
        raise ValueError("target endpoint contactPolicy blocks source endpoint.")
    requires_source_endpoint = contact_policy == "contacts_only"
    if requires_source_endpoint and source_endpoint is None:
        raise ValueError(
            "target endpoint contactPolicy=contacts_only requires a source "
            "endpoint alias."
        )
    matched_allow = _matched_contact_policy_rules(
        contact_profile,
        source_facts=source_facts,
        prefix="allowed",
    )
    allowlist_configured = _contact_policy_has_rules(contact_profile, "allowed")
    blocklist_configured = _contact_policy_has_rules(contact_profile, "blocked")
    if requires_source_endpoint and allowlist_configured and not matched_allow:
        raise ValueError(
            "target endpoint contactPolicy=contacts_only does not allow source "
            "endpoint."
        )
    if reply_policy != "message_only" and source_endpoint is None:
        raise ValueError(
            "source endpoint alias is required for reply-reachable endpoint dispatch."
        )
    return {
        "schema": "agent_dispatch_contact_policy_decision.v1",
        "targetEndpointAliasResolved": True,
        "targetContactPolicy": contact_policy,
        "decision": "allowed",
        "requiresSourceEndpoint": requires_source_endpoint,
        "sourceEndpointAliasResolved": source_endpoint is not None,
        "allowlistConfigured": allowlist_configured,
        "blocklistConfigured": blocklist_configured,
        "matchedAllowlistRules": matched_allow,
        "matchedBlocklistRules": matched_block,
        "sourceFacts": source_facts,
    }


def _dispatch_reply_reachability(
    *,
    source_endpoint: Mapping[str, object] | None,
    target_endpoint: Mapping[str, object] | None,
    source_handle_id: str | None,
    reply_policy: str,
) -> Mapping[str, object]:
    reply_required = reply_policy != "message_only"
    reply_reachable = (
        not reply_required
        or (source_endpoint is not None and source_handle_id is not None)
    )
    return {
        "schema": "agent_dispatch_reply_reachability.v1",
        "replyPolicy": reply_policy,
        "replyRequired": reply_required,
        "replyReachable": reply_reachable,
        "sourceEndpointAliasResolved": source_endpoint is not None,
        "sourceHandleResolved": source_handle_id is not None,
        "targetEndpointAliasResolved": target_endpoint is not None,
    }
