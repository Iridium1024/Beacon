from __future__ import annotations

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping, Sequence
from uuid import uuid4

from agent_os.application.services.agent_endpoint import (
    normalize_agent_endpoint_alias,
    normalize_agent_endpoint_provider,
)


SENSITIVE_KEY_PATTERN = re.compile(
    r"(credential|token|cookie|auth|authorization|api[_-]?key|secret|password)",
    re.IGNORECASE,
)

MANUAL_ONLY_ACTIVATION_POLICY = "manual_only_no_cross_workspace_lease"


@dataclass(frozen=True, slots=True)
class ProviderSessionRegistryPathResolution:
    """Resolved local registry path and the non-sensitive source that selected it."""

    registry_path: str
    registry_path_source: str
    registry_path_source_key: str | None
    exists: bool
    readable: bool
    writable: bool

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "registryPath": self.registry_path,
            "registryPathSource": self.registry_path_source,
            "registryPathSourceKey": self.registry_path_source_key,
            "registryPathStatus": {
                "schema": "provider_session_registry_path_status.v1",
                "exists": self.exists,
                "readable": self.readable,
                "writable": self.writable,
            },
        }


def resolve_provider_session_registry_path(
    *,
    explicit: str | None = None,
    profile: Mapping[str, object] | None = None,
    workspace_root: str | None = None,
    project_root: str | Path | None = None,
    base_directory: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> ProviderSessionRegistryPathResolution:
    """Resolve the registry once for every local-runtime entrypoint.

    Values, rather than their sources, may be local paths. The returned source
    key is therefore limited to CLI flag, profile key, environment variable, or
    derived-root label and never exposes environment values.
    """

    if explicit is not None and explicit.strip():
        return provider_session_registry_path_resolution(
            explicit,
            source="explicit_cli",
            source_key="--provider-session-registry",
        )
    source_profile = profile or {}
    for key in (
        "providerSessionRegistry",
        "providerSessionRegistryPath",
        "provider_session_registry",
    ):
        value = source_profile.get(key)
        if isinstance(value, str) and value.strip():
            return provider_session_registry_path_resolution(
                value,
                source="profile",
                source_key=key,
            )
        if value is not None:
            raise ValueError(f"profile {key} must be a string.")
    source_environment = environment if environment is not None else os.environ
    env_value = source_environment.get("AGENT_OS_PROVIDER_SESSION_REGISTRY")
    if env_value is not None and env_value.strip():
        return provider_session_registry_path_resolution(
            env_value,
            source="environment",
            source_key="AGENT_OS_PROVIDER_SESSION_REGISTRY",
        )
    if project_root is not None:
        return provider_session_registry_path_resolution(
            Path(project_root).expanduser() / ".beacon" / "provider-session-registry.json",
            source="project_default",
            source_key="projectRoot",
        )
    profile_project_root = source_profile.get("projectRoot")
    if isinstance(profile_project_root, str) and profile_project_root.strip():
        return provider_session_registry_path_resolution(
            Path(profile_project_root).expanduser()
            / ".beacon"
            / "provider-session-registry.json",
            source="project_default",
            source_key="projectRoot",
        )
    if base_directory is not None:
        return provider_session_registry_path_resolution(
            Path(base_directory).expanduser() / "provider-session-registry.json",
            source="workspace_derived",
            source_key="workspaceBaseDirectory",
        )
    if workspace_root is not None and workspace_root.strip():
        root = Path(workspace_root).expanduser().resolve(strict=False)
        registry = (
            root.parent.parent.parent / "provider-session-registry.json"
            if root.name == "workspace-root" and root.parent.parent.name == "workspaces"
            else root.parent / "provider-session-registry.json"
        )
        return provider_session_registry_path_resolution(
            registry,
            source="workspace_derived",
            source_key="workspaceRoot",
        )
    return provider_session_registry_path_resolution(
        Path(cwd or Path.cwd()).expanduser()
        / ".beacon"
        / "provider-session-registry.json",
        source="cwd_default",
        source_key="cwd",
    )


def provider_session_registry_path_resolution(
    path: str | Path,
    *,
    source: str,
    source_key: str | None,
) -> ProviderSessionRegistryPathResolution:
    registry_path = Path(path).expanduser().resolve(strict=False)
    exists = registry_path.exists()
    readable = exists and os.access(registry_path, os.R_OK)
    writable = (
        os.access(registry_path, os.W_OK)
        if exists
        else _nearest_existing_parent_writable(registry_path.parent)
    )
    return ProviderSessionRegistryPathResolution(
        registry_path=str(registry_path),
        registry_path_source=source,
        registry_path_source_key=source_key,
        exists=exists,
        readable=readable,
        writable=writable,
    )


def _nearest_existing_parent_writable(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK)


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_provider_session_registry(path: str | Path) -> dict[str, object]:
    registry_path = Path(path).expanduser().resolve(strict=False)
    if not registry_path.exists():
        return _empty_registry()
    loaded = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("provider session registry must be a JSON object.")
    profiles = loaded.get("profiles", [])
    memberships = loaded.get("memberships", [])
    if not isinstance(profiles, list) or not isinstance(memberships, list):
        raise ValueError("provider session registry profiles/memberships must be lists.")
    return {
        "schema": "provider_session_registry.v1",
        "profiles": [
            dict(item) for item in profiles if isinstance(item, MappingABC)
        ],
        "memberships": [
            dict(item) for item in memberships if isinstance(item, MappingABC)
        ],
    }


def save_provider_session_registry(path: str | Path, registry: Mapping[str, object]) -> None:
    registry_path = Path(path).expanduser().resolve(strict=False)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "provider_session_registry.v1",
        "profiles": list(registry.get("profiles", ())),
        "memberships": list(registry.get("memberships", ())),
    }
    # Atomic replace avoids partial JSON files on process crash. This registry
    # still does not provide a multi-process file lock; concurrent writers must
    # be serialized by the caller or a future lock layer.
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(registry_path.parent),
            prefix=f".{registry_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, registry_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


class ProviderSessionRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = str(Path(path).expanduser().resolve(strict=False))

    def register_profile(
        self,
        *,
        provider: str,
        provider_session_id: str,
        profile_alias: str,
        cwd: str,
        created_by: str,
        reason: str,
        profile_id: str | None = None,
        source_path: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        normalized_provider = _provider(provider)
        session_id = _required_text(provider_session_id, "providerSessionId")
        alias = _profile_alias(profile_alias)
        created_by = _required_text(created_by, "createdBy")
        reason = _required_text(reason, "reason")
        cwd_path = _existing_directory(cwd, "cwd")
        source_path_text = _optional_text(source_path)
        metadata = _safe_metadata(metadata)
        registry = load_provider_session_registry(self.path)
        profiles = list(registry["profiles"])
        existing_by_id = (
            _profile_by_id(profiles, profile_id) if profile_id is not None else None
        )
        existing_by_alias = _active_profile_by_alias(profiles, alias)
        if (
            existing_by_alias is not None
            and existing_by_id is not None
            and existing_by_alias.get("profileId") != existing_by_id.get("profileId")
        ):
            raise ValueError("profileAlias is already active for another profile.")
        if existing_by_alias is not None and existing_by_id is None:
            if (
                existing_by_alias.get("provider") != normalized_provider
                or existing_by_alias.get("providerSessionId") != session_id
            ):
                raise ValueError("profileAlias is already active for another provider session.")
            existing_by_id = existing_by_alias
        matching = existing_by_id or _active_profile_by_provider_session(
            profiles,
            provider=normalized_provider,
            provider_session_id=session_id,
        )
        timestamp = utc_now_text()
        if matching is not None:
            return {
                "schema": "provider_session_profile_register.v1",
                "ok": True,
                "created": False,
                "reused": True,
                "registryPath": self.path,
                "providerSessionProfile": dict(matching),
                "boundaries": _profile_boundaries(),
            }
        profile = {
            "schema": "local_provider_session_profile.v1",
            "profileId": profile_id or f"provider-session-profile-{uuid4()}",
            "provider": normalized_provider,
            "providerSessionId": session_id,
            _provider_session_field(normalized_provider): session_id,
            "profileAlias": alias,
            "cwd": str(cwd_path),
            "cwdSummary": _path_summary(cwd_path),
            "sourcePath": source_path_text,
            "sourcePathSummary": _path_summary(Path(source_path_text)) if source_path_text else None,
            "state": "active",
            "createdBy": created_by,
            "reason": reason,
            "metadata": metadata,
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "credentialStored": False,
            "providerAccountAuthenticated": False,
            "fullSessionHistoryRead": False,
            "activationPolicy": MANUAL_ONLY_ACTIVATION_POLICY,
            "activationGuardEnforced": False,
            "localOnly": True,
        }
        profiles.append(profile)
        registry["profiles"] = profiles
        save_provider_session_registry(self.path, registry)
        return {
            "schema": "provider_session_profile_register.v1",
            "ok": True,
            "created": True,
            "reused": False,
            "registryPath": self.path,
            "providerSessionProfile": profile,
            "boundaries": _profile_boundaries(),
        }

    def list_profiles(
        self,
        *,
        provider: str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        normalized_provider = (
            _provider(provider) if provider is not None else None
        )
        registry = load_provider_session_registry(self.path)
        profiles = [
            dict(profile)
            for profile in registry["profiles"]
            if (include_inactive or profile.get("state") == "active")
            and (
                normalized_provider is None
                or profile.get("provider") == normalized_provider
            )
        ]
        memberships = list(registry["memberships"])
        return {
            "schema": "provider_session_profile_list.v1",
            "registryPath": self.path,
            "count": len(profiles),
            "providerSessionProfiles": [
                _profile_with_memberships(profile, memberships)
                for profile in sorted(profiles, key=lambda item: str(item.get("profileAlias")))
            ],
            "boundaries": _profile_boundaries(),
        }

    def get_profile(
        self,
        *,
        profile_id: str | None = None,
        profile_alias: str | None = None,
        include_inactive_memberships: bool = True,
    ) -> Mapping[str, object]:
        registry = load_provider_session_registry(self.path)
        profile = _select_profile(
            registry["profiles"],
            profile_id=profile_id,
            profile_alias=profile_alias,
        )
        memberships = [
            dict(item)
            for item in registry["memberships"]
            if item.get("profileId") == profile.get("profileId")
            and (
                include_inactive_memberships
                or item.get("state") == "active"
            )
        ]
        return {
            "schema": "provider_session_profile_get.v1",
            "registryPath": self.path,
            "providerSessionProfile": {
                **dict(profile),
                "memberships": sorted(
                    memberships,
                    key=lambda item: str(item.get("workspaceId")),
                ),
            },
            "boundaries": _profile_boundaries(),
        }

    def deactivate_profile(
        self,
        *,
        profile_id: str,
        deactivated_by: str,
        reason: str,
        confirm: bool,
    ) -> Mapping[str, object]:
        registry = load_provider_session_registry(self.path)
        profile = _select_profile(registry["profiles"], profile_id=profile_id)
        affected = [
            dict(item)
            for item in registry["memberships"]
            if item.get("profileId") == profile.get("profileId")
            and item.get("state") == "active"
        ]
        if not confirm:
            return {
                "schema": "provider_session_profile_deactivate.v1",
                "ok": False,
                "requiresConfirmation": True,
                "confirmFlag": "--confirm-deactivate-profile",
                "profileId": profile_id,
                "affectedMemberships": affected,
                "impact": _deactivate_profile_impact(),
            }
        timestamp = utc_now_text()
        profiles = []
        for item in registry["profiles"]:
            current = dict(item)
            if current.get("profileId") == profile.get("profileId"):
                current.update(
                    {
                        "state": "inactive",
                        "updatedAt": timestamp,
                        "deactivatedBy": _required_text(deactivated_by, "deactivatedBy"),
                        "deactivationReason": _required_text(reason, "reason"),
                    }
                )
            profiles.append(current)
        memberships = []
        for item in registry["memberships"]:
            current = dict(item)
            if current.get("profileId") == profile.get("profileId") and current.get("state") == "active":
                current.update(
                    {
                        "state": "profile_deactivated",
                        "leftAt": timestamp,
                        "updatedAt": timestamp,
                        "leftBy": deactivated_by,
                        "leaveReason": reason,
                    }
                )
            memberships.append(current)
        registry["profiles"] = profiles
        registry["memberships"] = memberships
        save_provider_session_registry(self.path, registry)
        return {
            "schema": "provider_session_profile_deactivate.v1",
            "ok": True,
            "requiresConfirmation": False,
            "registryPath": self.path,
            "profileId": profile_id,
            "affectedMemberships": affected,
            "impact": _deactivate_profile_impact(),
        }

    def preflight_workspace_join(
        self,
        *,
        profile_id: str,
        workspace_id: str,
        agent_id: str,
        endpoint_alias: str,
    ) -> Mapping[str, object]:
        registry = load_provider_session_registry(self.path)
        profile = _select_profile(registry["profiles"], profile_id=profile_id)
        if profile.get("state") != "active":
            raise ValueError("provider session profile is not active.")
        membership = _active_membership(
            registry["memberships"],
            profile_id=profile_id,
            workspace_id=workspace_id,
        )
        if membership is None:
            return {
                "ok": True,
                "providerSessionProfile": dict(profile),
                "existingMembership": None,
            }
        mismatches = {
            key: {
                "expected": value,
                "actual": membership.get(key),
            }
            for key, value in {
                "agentId": agent_id,
                "endpointAlias": normalize_agent_endpoint_alias(endpoint_alias),
            }.items()
            if membership.get(key) != value
        }
        if mismatches:
            return {
                "ok": False,
                "providerSessionProfile": dict(profile),
                "existingMembership": dict(membership),
                "mismatches": mismatches,
            }
        return {
            "ok": True,
            "providerSessionProfile": dict(profile),
            "existingMembership": dict(membership),
        }

    def upsert_membership(
        self,
        *,
        profile: Mapping[str, object],
        workspace_id: str,
        agent_id: str,
        provider_handle_id: str,
        endpoint_alias: str,
        endpoint_id: str,
        joined_by: str,
        reason: str,
        endpoint_readiness: Mapping[str, object],
    ) -> Mapping[str, object]:
        registry = load_provider_session_registry(self.path)
        profile_id = str(profile["profileId"])
        workspace_id = _required_text(workspace_id, "workspaceId")
        endpoint_alias = normalize_agent_endpoint_alias(endpoint_alias)
        existing = _active_membership(
            registry["memberships"],
            profile_id=profile_id,
            workspace_id=workspace_id,
        )
        timestamp = utc_now_text()
        membership = {
            "schema": "provider_session_workspace_membership.v1",
            "membershipId": (
                existing.get("membershipId")
                if existing is not None
                else f"provider-session-membership-{uuid4()}"
            ),
            "profileId": profile_id,
            "profileAlias": profile.get("profileAlias"),
            "provider": profile.get("provider"),
            "providerSessionId": profile.get("providerSessionId"),
            "workspaceId": workspace_id,
            "agentId": _required_text(agent_id, "agentId"),
            "providerHandleId": _required_text(provider_handle_id, "providerHandleId"),
            "endpointAlias": endpoint_alias,
            "endpointId": _required_text(endpoint_id, "endpointId"),
            "state": "active",
            "joinedAt": existing.get("joinedAt") if existing is not None else timestamp,
            "updatedAt": timestamp,
            "joinedBy": _required_text(joined_by, "joinedBy"),
            "reason": _required_text(reason, "reason"),
            "endpointReadiness": dict(endpoint_readiness),
            "activationPolicy": MANUAL_ONLY_ACTIVATION_POLICY,
            "activationGuardEnforced": False,
        }
        memberships = []
        replaced = False
        for item in registry["memberships"]:
            current = dict(item)
            if current.get("membershipId") == membership["membershipId"]:
                memberships.append(membership)
                replaced = True
            else:
                memberships.append(current)
        if not replaced:
            memberships.append(membership)
        registry["memberships"] = memberships
        save_provider_session_registry(self.path, registry)
        return {
            "schema": "provider_session_workspace_membership_upsert.v1",
            "ok": True,
            "created": existing is None,
            "reused": existing is not None,
            "registryPath": self.path,
            "providerSessionMembership": membership,
        }

    def list_memberships(
        self,
        *,
        profile_id: str | None = None,
        workspace_id: str | None = None,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        registry = load_provider_session_registry(self.path)
        memberships = [
            dict(item)
            for item in registry["memberships"]
            if (include_inactive or item.get("state") == "active")
            and (profile_id is None or item.get("profileId") == profile_id)
            and (workspace_id is None or item.get("workspaceId") == workspace_id)
        ]
        return {
            "schema": "provider_session_membership_list.v1",
            "registryPath": self.path,
            "count": len(memberships),
            "memberships": sorted(
                memberships,
                key=lambda item: (
                    str(item.get("profileId")),
                    str(item.get("workspaceId")),
                ),
            ),
            "activationPolicy": MANUAL_ONLY_ACTIVATION_POLICY,
            "activationGuardEnforced": False,
        }

    def leave_membership(
        self,
        *,
        profile_id: str,
        workspace_id: str,
        left_by: str,
        reason: str,
        endpoint_deactivated: bool,
        provider_handle_deactivated: bool,
    ) -> Mapping[str, object]:
        registry = load_provider_session_registry(self.path)
        membership = _active_membership(
            registry["memberships"],
            profile_id=profile_id,
            workspace_id=workspace_id,
        )
        if membership is None:
            return {
                "schema": "provider_session_workspace_leave.v1",
                "ok": True,
                "left": False,
                "alreadyLeft": True,
                "profileId": profile_id,
                "workspaceId": workspace_id,
            }
        timestamp = utc_now_text()
        updated_membership = {
            **dict(membership),
            "state": "left",
            "leftAt": timestamp,
            "updatedAt": timestamp,
            "leftBy": _required_text(left_by, "leftBy"),
            "leaveReason": _required_text(reason, "reason"),
            "endpointDeactivated": endpoint_deactivated,
            "providerHandleDeactivated": provider_handle_deactivated,
        }
        registry["memberships"] = [
            updated_membership
            if item.get("membershipId") == membership.get("membershipId")
            else dict(item)
            for item in registry["memberships"]
        ]
        save_provider_session_registry(self.path, registry)
        return {
            "schema": "provider_session_workspace_leave.v1",
            "ok": True,
            "left": True,
            "alreadyLeft": False,
            "registryPath": self.path,
            "providerSessionMembership": updated_membership,
        }


def provider_session_profile_ref(
    source: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if not isinstance(source, MappingABC):
        return None
    metadata = source.get("metadata")
    if not isinstance(metadata, MappingABC):
        return None
    ref = metadata.get("providerSessionWorkspaceJoin")
    if not isinstance(ref, MappingABC):
        return None
    return {
        "schema": "provider_session_profile_ref.v1",
        "profileId": ref.get("profileId"),
        "profileAlias": ref.get("profileAlias"),
        "membershipId": ref.get("membershipId"),
        "activationPolicy": ref.get("activationPolicy", MANUAL_ONLY_ACTIVATION_POLICY),
        "activationGuardEnforced": bool(ref.get("activationGuardEnforced")),
    }


def synthetic_discovered_session_from_profile(
    profile: Mapping[str, object],
) -> Mapping[str, object]:
    record: dict[str, object] = {
        "schema": "agent_session_discovery_record.v1",
        "agentRuntime": profile["provider"],
        "provider": profile["provider"],
        "sessionId": profile["providerSessionId"],
        "cwd": profile["cwd"],
        "cwdSource": "local_provider_session_profile",
        "sourcePath": profile.get("sourcePath"),
        "sourceKind": "local_provider_session_profile",
        "updatedAt": profile.get("updatedAt"),
        "confidence": "explicit",
        "registrationReady": True,
        "missingFields": [],
        "fullSessionHistoryRead": False,
        "credentialStored": False,
    }
    metadata = profile.get("metadata")
    if isinstance(metadata, MappingABC):
        identity = metadata.get("hermesSessionIdentity")
        if isinstance(identity, MappingABC):
            record["providerSessionIdentity"] = dict(identity)
    return record


def _empty_registry() -> dict[str, object]:
    return {
        "schema": "provider_session_registry.v1",
        "profiles": [],
        "memberships": [],
    }


def _provider(value: str | None) -> str:
    provider = normalize_agent_endpoint_provider(value)
    if provider is None:
        raise ValueError("provider must be one of: claude, codex, hermes.")
    return provider


def _provider_session_field(provider: str) -> str:
    return {
        "claude": "claudeSessionUuid",
        "codex": "codexSessionId",
        "hermes": "hermesSessionId",
    }[provider]


def _required_text(value: object, logical_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{logical_name} is required.")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _profile_alias(value: str) -> str:
    alias = normalize_agent_endpoint_alias(value)
    return alias


def _existing_directory(value: str, logical_name: str) -> Path:
    path = Path(_required_text(value, logical_name)).expanduser().resolve(strict=False)
    if not path.exists() or not path.is_dir():
        raise ValueError(f"{logical_name} must be an existing directory.")
    return path


def _path_summary(path: Path) -> str:
    parts = path.parts
    if len(parts) <= 3:
        return str(path)
    return str(Path("...").joinpath(*parts[-3:]))


def _safe_metadata(value: Mapping[str, object] | None) -> Mapping[str, object]:
    metadata = dict(value or {})
    _reject_sensitive_mapping(metadata)
    return metadata


def _reject_sensitive_mapping(value: object, path: str = "metadata") -> None:
    if isinstance(value, MappingABC):
        for key, item in value.items():
            if SENSITIVE_KEY_PATTERN.search(str(key)):
                raise ValueError(f"{path}.{key} must not contain credential values.")
            _reject_sensitive_mapping(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_mapping(item, f"{path}[{index}]")


def _profile_by_id(
    profiles: Sequence[Mapping[str, object]],
    profile_id: str | None,
) -> Mapping[str, object] | None:
    if profile_id is None:
        return None
    for profile in profiles:
        if profile.get("profileId") == profile_id:
            return dict(profile)
    return None


def _active_profile_by_alias(
    profiles: Sequence[Mapping[str, object]],
    alias: str,
) -> Mapping[str, object] | None:
    for profile in profiles:
        if profile.get("profileAlias") == alias and profile.get("state") == "active":
            return dict(profile)
    return None


def _active_profile_by_provider_session(
    profiles: Sequence[Mapping[str, object]],
    *,
    provider: str,
    provider_session_id: str,
) -> Mapping[str, object] | None:
    for profile in profiles:
        if (
            profile.get("provider") == provider
            and profile.get("providerSessionId") == provider_session_id
            and profile.get("state") == "active"
        ):
            return dict(profile)
    return None


def _select_profile(
    profiles: Sequence[Mapping[str, object]],
    *,
    profile_id: str | None = None,
    profile_alias: str | None = None,
) -> Mapping[str, object]:
    if profile_id is None and profile_alias is None:
        raise ValueError("profileId or profileAlias is required.")
    if profile_id is not None:
        profile = _profile_by_id(profiles, profile_id)
        if profile is not None:
            return profile
        raise ValueError("provider session profile not found.")
    alias = _profile_alias(str(profile_alias))
    profile = _active_profile_by_alias(profiles, alias)
    if profile is not None:
        return profile
    raise ValueError("provider session profile not found.")


def _active_membership(
    memberships: Sequence[Mapping[str, object]],
    *,
    profile_id: str,
    workspace_id: str,
) -> Mapping[str, object] | None:
    for membership in memberships:
        if (
            membership.get("profileId") == profile_id
            and membership.get("workspaceId") == workspace_id
            and membership.get("state") == "active"
        ):
            return dict(membership)
    return None


def _profile_with_memberships(
    profile: Mapping[str, object],
    memberships: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    profile_memberships = [
        dict(item)
        for item in memberships
        if item.get("profileId") == profile.get("profileId")
    ]
    return {
        **dict(profile),
        "joinedWorkspaceCount": len(
            [item for item in profile_memberships if item.get("state") == "active"]
        ),
        "memberships": sorted(
            profile_memberships,
            key=lambda item: str(item.get("workspaceId")),
        ),
    }


def _profile_boundaries() -> Mapping[str, object]:
    return {
        "schema": "provider_session_profile_boundaries.v1",
        "providerAccountLogin": False,
        "providerCredentialStored": False,
        "credentialStored": False,
        "providerAccountAuthenticated": False,
        "fullSessionHistoryRead": False,
        "globalDispatchAliasCreated": False,
        "workspaceLocalAgentReplaced": False,
    }


def _deactivate_profile_impact() -> Mapping[str, object]:
    return {
        "schema": "provider_session_profile_deactivate_impact.v1",
        "profileStateChanges": True,
        "membershipsMarkedInactive": True,
        "workspaceEndpointsAutomaticallyDeleted": False,
        "providerHandlesAutomaticallyDeleted": False,
        "otherProviderSessionsAffected": False,
    }
