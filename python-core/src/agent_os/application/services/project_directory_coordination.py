from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Mapping, Sequence
from uuid import uuid4


class ProjectDirectoryAccessIntent(StrEnum):
    """Declared project-directory activity state for an external agent."""

    READ_ONLY = "read_only"
    EDIT_PLANNED = "edit_planned"
    EDITING = "editing"
    HANDOFF_READY = "handoff_ready"
    REVIEW_REQUESTED = "review_requested"
    DONE_REPORTED = "done_reported"


class ProjectDirectoryOverlapStatus(StrEnum):
    """Advisory overlap labels over declared path scopes."""

    NONE = "none"
    SHARED_READ = "shared_read"
    SHARED_WRITE_RISK = "shared_write_risk"
    CONFLICT_DECLARED = "conflict_declared"


class ProjectDirectoryCoordinationStrength(StrEnum):
    """Coordination records are advisory only, never hard filesystem locks."""

    ADVISORY_ONLY = "advisory_only"


class ProjectDirectoryDirtyState(StrEnum):
    """Caller-reported git/worktree dirtiness summary."""

    UNKNOWN = "unknown"
    CLEAN = "clean"
    DIRTY_REPORTED = "dirty_reported"


class ProjectDirectoryCommitPolicy(StrEnum):
    """Caller recommendation for git provenance after directory work."""

    COMMIT_AFTER_TASK = "commit_after_task"
    REPORT_UNCOMMITTED_CHANGES = "report_uncommitted_changes"
    NO_COMMIT_NEEDED = "no_commit_needed"


_WRITE_INTENTS = {
    ProjectDirectoryAccessIntent.EDIT_PLANNED,
    ProjectDirectoryAccessIntent.EDITING,
    ProjectDirectoryAccessIntent.HANDOFF_READY,
    ProjectDirectoryAccessIntent.REVIEW_REQUESTED,
}


@dataclass(frozen=True, slots=True)
class ProjectDirectoryCoordinationRecord:
    """Advisory coordination state for agents sharing a project directory."""

    workspace_id: str
    declared_agent_id: str
    project_root: str
    directory_coordination_id: str = field(
        default_factory=lambda: f"directory-coordination-{uuid4()}"
    )
    git_repository_id: str | None = None
    linked_task_id: str | None = None
    linked_conversation_id: str | None = None
    declared_path_scopes: tuple[str, ...] = (".",)
    directory_access_intent: ProjectDirectoryAccessIntent | str = (
        ProjectDirectoryAccessIntent.EDIT_PLANNED
    )
    overlap_status: ProjectDirectoryOverlapStatus | str = (
        ProjectDirectoryOverlapStatus.NONE
    )
    overlapping_coordination_ids: tuple[str, ...] = ()
    coordination_strength: ProjectDirectoryCoordinationStrength | str = (
        ProjectDirectoryCoordinationStrength.ADVISORY_ONLY
    )
    last_known_git_head: str | None = None
    last_known_branch: str | None = None
    dirty_state: ProjectDirectoryDirtyState | str = ProjectDirectoryDirtyState.UNKNOWN
    uncommitted_change_summary: str | None = None
    test_summary: str | None = None
    recommended_commit_policy: ProjectDirectoryCommitPolicy | str = (
        ProjectDirectoryCommitPolicy.COMMIT_AFTER_TASK
    )
    handoff_note: str | None = None
    requires_user_review: bool = False
    not_security_boundary: bool = True
    advisory_only: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, object] = field(default_factory=dict)
    source_event_sequence: int | None = None

    @classmethod
    def from_mapping(
        cls,
        source: Mapping[str, object],
    ) -> "ProjectDirectoryCoordinationRecord":
        config = dict(source)
        _reject_sensitive_config(config, "projectDirectoryCoordination")
        created_at = _optional_datetime(config, "created_at", "createdAt") or _utc_now()
        return cls(
            workspace_id=_required_text(config, "workspace_id", "workspaceId"),
            declared_agent_id=_required_text(
                config,
                "declared_agent_id",
                "declaredAgentId",
            ),
            project_root=_required_text(config, "project_root", "projectRoot"),
            directory_coordination_id=(
                _optional_text(
                    config,
                    "directory_coordination_id",
                    "directoryCoordinationId",
                )
                or f"directory-coordination-{uuid4()}"
            ),
            git_repository_id=_optional_text(
                config,
                "git_repository_id",
                "gitRepositoryId",
            ),
            linked_task_id=_optional_text(config, "linked_task_id", "linkedTaskId"),
            linked_conversation_id=_optional_text(
                config,
                "linked_conversation_id",
                "linkedConversationId",
            ),
            declared_path_scopes=_path_scope_tuple(
                _optional_value(
                    config,
                    "declared_path_scopes",
                    "declaredPathScopes",
                ),
                "declaredPathScopes",
            ),
            directory_access_intent=(
                _optional_text(
                    config,
                    "directory_access_intent",
                    "directoryAccessIntent",
                )
                or ProjectDirectoryAccessIntent.EDIT_PLANNED
            ),
            overlap_status=(
                _optional_text(config, "overlap_status", "overlapStatus")
                or ProjectDirectoryOverlapStatus.NONE
            ),
            overlapping_coordination_ids=_text_tuple(
                _optional_value(
                    config,
                    "overlapping_coordination_ids",
                    "overlappingCoordinationIds",
                ),
                "overlappingCoordinationIds",
            ),
            coordination_strength=(
                _optional_text(
                    config,
                    "coordination_strength",
                    "coordinationStrength",
                )
                or ProjectDirectoryCoordinationStrength.ADVISORY_ONLY
            ),
            last_known_git_head=_optional_text(
                config,
                "last_known_git_head",
                "lastKnownGitHead",
            ),
            last_known_branch=_optional_text(
                config,
                "last_known_branch",
                "lastKnownBranch",
            ),
            dirty_state=(
                _optional_text(config, "dirty_state", "dirtyState")
                or ProjectDirectoryDirtyState.UNKNOWN
            ),
            uncommitted_change_summary=_optional_text(
                config,
                "uncommitted_change_summary",
                "uncommittedChangeSummary",
            ),
            test_summary=_optional_text(config, "test_summary", "testSummary"),
            recommended_commit_policy=(
                _optional_text(
                    config,
                    "recommended_commit_policy",
                    "recommendedCommitPolicy",
                )
                or ProjectDirectoryCommitPolicy.COMMIT_AFTER_TASK
            ),
            handoff_note=_optional_text(config, "handoff_note", "handoffNote"),
            requires_user_review=_optional_bool(
                config,
                "requires_user_review",
                "requiresUserReview",
                default=False,
            )
            or False,
            not_security_boundary=_optional_bool(
                config,
                "not_security_boundary",
                "notSecurityBoundary",
                default=True,
            )
            if _optional_value(config, "not_security_boundary", "notSecurityBoundary")
            is not None
            else True,
            advisory_only=_optional_bool(
                config,
                "advisory_only",
                "advisoryOnly",
                default=True,
            )
            if _optional_value(config, "advisory_only", "advisoryOnly") is not None
            else True,
            created_at=created_at,
            updated_at=(
                _optional_datetime(config, "updated_at", "updatedAt") or created_at
            ),
            metadata=dict(_optional_mapping(config, "metadata") or {}),
            source_event_sequence=_optional_int(
                config,
                "source_event_sequence",
                "sourceEventSequence",
            ),
        )

    def __post_init__(self) -> None:
        _validate_text(self.workspace_id, "workspaceId")
        _validate_text(self.declared_agent_id, "declaredAgentId")
        _validate_text(self.project_root, "projectRoot")
        _validate_text(self.directory_coordination_id, "directoryCoordinationId")
        _validate_optional_text(self.git_repository_id, "gitRepositoryId")
        _validate_optional_text(self.linked_task_id, "linkedTaskId")
        _validate_optional_text(self.linked_conversation_id, "linkedConversationId")
        _validate_optional_text(self.last_known_git_head, "lastKnownGitHead")
        _validate_optional_text(self.last_known_branch, "lastKnownBranch")
        _validate_optional_text(
            self.uncommitted_change_summary,
            "uncommittedChangeSummary",
        )
        _validate_optional_text(self.test_summary, "testSummary")
        _validate_optional_text(self.handoff_note, "handoffNote")
        _require_utc_aware(self.created_at, "createdAt")
        _require_utc_aware(self.updated_at, "updatedAt")
        _reject_sensitive_config(dict(self.metadata), "projectDirectoryCoordination.metadata")

        intent = _enum_value(
            ProjectDirectoryAccessIntent,
            self.directory_access_intent,
            "directoryAccessIntent",
        )
        overlap = _enum_value(
            ProjectDirectoryOverlapStatus,
            self.overlap_status,
            "overlapStatus",
        )
        strength = _enum_value(
            ProjectDirectoryCoordinationStrength,
            self.coordination_strength,
            "coordinationStrength",
        )
        dirty_state = _enum_value(
            ProjectDirectoryDirtyState,
            self.dirty_state,
            "dirtyState",
        )
        commit_policy = _enum_value(
            ProjectDirectoryCommitPolicy,
            self.recommended_commit_policy,
            "recommendedCommitPolicy",
        )
        path_scopes = _validate_path_scopes(self.declared_path_scopes)
        _validate_text_tuple(
            self.overlapping_coordination_ids,
            "overlappingCoordinationIds",
        )

        object.__setattr__(self, "directory_access_intent", intent)
        object.__setattr__(self, "overlap_status", overlap)
        object.__setattr__(self, "coordination_strength", strength)
        object.__setattr__(self, "dirty_state", dirty_state)
        object.__setattr__(self, "recommended_commit_policy", commit_policy)
        object.__setattr__(self, "declared_path_scopes", path_scopes)
        object.__setattr__(
            self,
            "overlapping_coordination_ids",
            tuple(self.overlapping_coordination_ids),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "not_security_boundary", True)
        object.__setattr__(self, "advisory_only", True)
        object.__setattr__(
            self,
            "coordination_strength",
            ProjectDirectoryCoordinationStrength.ADVISORY_ONLY,
        )

    def is_active(self) -> bool:
        return self.directory_access_intent is not ProjectDirectoryAccessIntent.DONE_REPORTED

    def has_write_intent(self) -> bool:
        return self.directory_access_intent in _WRITE_INTENTS

    def updated_copy(
        self,
        *,
        updated_at: datetime | None = None,
        **updates: object,
    ) -> "ProjectDirectoryCoordinationRecord":
        return ProjectDirectoryCoordinationRecord.from_mapping(
            {
                **self.to_metadata(),
                **{
                    key: value
                    for key, value in updates.items()
                    if value is not None
                },
                "updatedAt": (updated_at or _utc_now()).isoformat(),
            }
        )

    def with_overlap(
        self,
        *,
        overlap_status: ProjectDirectoryOverlapStatus | str,
        overlapping_coordination_ids: tuple[str, ...] = (),
    ) -> "ProjectDirectoryCoordinationRecord":
        return self.updated_copy(
            overlapStatus=(
                overlap_status.value
                if isinstance(overlap_status, ProjectDirectoryOverlapStatus)
                else overlap_status
            ),
            overlappingCoordinationIds=overlapping_coordination_ids,
            updated_at=self.updated_at,
        )

    def to_metadata(self) -> Mapping[str, object]:
        metadata: dict[str, object] = {
            "schema": "project_directory_coordination.v1",
            "directoryCoordinationId": self.directory_coordination_id,
            "workspaceId": self.workspace_id,
            "declaredAgentId": self.declared_agent_id,
            "projectRoot": self.project_root,
            "declaredPathScopes": list(self.declared_path_scopes),
            "directoryAccessIntent": self.directory_access_intent.value,
            "overlapStatus": self.overlap_status.value,
            "overlappingCoordinationIds": list(self.overlapping_coordination_ids),
            "coordinationStrength": self.coordination_strength.value,
            "dirtyState": self.dirty_state.value,
            "recommendedCommitPolicy": self.recommended_commit_policy.value,
            "requiresUserReview": self.requires_user_review,
            "notSecurityBoundary": self.not_security_boundary,
            "advisoryOnly": self.advisory_only,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "fileBodiesRead": False,
            "recursiveFileScanExecuted": False,
            "gitOperationExecuted": False,
            "destructiveGitOperationExecuted": False,
            "realRuntimeConnected": False,
            "providerPromptInjected": False,
            "credentialStored": False,
        }
        for key, value in (
            ("gitRepositoryId", self.git_repository_id),
            ("linkedTaskId", self.linked_task_id),
            ("linkedConversationId", self.linked_conversation_id),
            ("lastKnownGitHead", self.last_known_git_head),
            ("lastKnownBranch", self.last_known_branch),
            ("uncommittedChangeSummary", self.uncommitted_change_summary),
            ("testSummary", self.test_summary),
            ("handoffNote", self.handoff_note),
            ("sourceEventSequence", self.source_event_sequence),
        ):
            if value is not None:
                metadata[key] = value
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


def project_directory_coordination_interface_metadata(
    *,
    workspace_id: str | None = None,
) -> Mapping[str, object]:
    """Agent-facing metadata-only project-directory coordination contract."""

    return {
        "projectDirectoryCoordinationInterface": {
            "schema": "project_directory_coordination_interface.v1",
            "workspaceId": workspace_id,
            "status": "contract_only",
            "accessIntents": [item.value for item in ProjectDirectoryAccessIntent],
            "overlapStatuses": [item.value for item in ProjectDirectoryOverlapStatus],
            "dirtyStates": [item.value for item in ProjectDirectoryDirtyState],
            "recommendedCommitPolicies": [
                item.value for item in ProjectDirectoryCommitPolicy
            ],
            "coordinationStrength": ProjectDirectoryCoordinationStrength.ADVISORY_ONLY.value,
            "metadataKey": "projectDirectoryCoordination",
            "defaults": {
                "coordinationStrength": ProjectDirectoryCoordinationStrength.ADVISORY_ONLY.value,
                "notSecurityBoundary": True,
                "advisoryOnly": True,
                "fileBodiesRead": False,
                "recursiveFileScanExecuted": False,
                "gitOperationExecuted": False,
                "destructiveGitOperationExecuted": False,
                "realRuntimeConnected": False,
                "providerPromptInjected": False,
                "credentialStored": False,
            },
            "rules": [
                "directory coordination records are advisory audit signals, not OS locks",
                "agents should declare project root, path scopes, task scope, branch/head, and dirty-state summaries before editing",
                "shared write risk should pause work and request user review before overlapping edits continue",
                "agents should commit after completing a directory task or report uncommitted files and the reason",
                "records must not contain file bodies, full prompts, full model replies, credentials, Authorization headers, cookies, or session tokens",
                "the platform does not execute git commit, push, reset, checkout, rebase, or conflict resolution through this contract",
            ],
            "localRuntimeCommands": {
                "instructions": "project-directory-coordination-instructions",
                "declare": "project-directory-coordination-declare",
                "status": "project-directory-coordination-status",
                "update": "project-directory-coordination-update",
                "complete": "project-directory-coordination-complete",
            },
        }
    }


def calculate_project_directory_overlap(
    candidate: ProjectDirectoryCoordinationRecord,
    records: Sequence[ProjectDirectoryCoordinationRecord],
) -> tuple[ProjectDirectoryOverlapStatus, tuple[str, ...]]:
    overlapping: list[ProjectDirectoryCoordinationRecord] = []
    for record in records:
        if record.directory_coordination_id == candidate.directory_coordination_id:
            continue
        if not record.is_active() or not candidate.is_active():
            continue
        if not _same_project_directory(candidate, record):
            continue
        if _path_scopes_overlap(candidate.declared_path_scopes, record.declared_path_scopes):
            overlapping.append(record)
    if not overlapping:
        return ProjectDirectoryOverlapStatus.NONE, ()
    if candidate.has_write_intent() or any(record.has_write_intent() for record in overlapping):
        return (
            ProjectDirectoryOverlapStatus.SHARED_WRITE_RISK,
            tuple(record.directory_coordination_id for record in overlapping),
        )
    return (
        ProjectDirectoryOverlapStatus.SHARED_READ,
        tuple(record.directory_coordination_id for record in overlapping),
    )


def _same_project_directory(
    left: ProjectDirectoryCoordinationRecord,
    right: ProjectDirectoryCoordinationRecord,
) -> bool:
    if _normalize_root(left.project_root) == _normalize_root(right.project_root):
        return True
    if left.git_repository_id and right.git_repository_id:
        return left.git_repository_id == right.git_repository_id
    return False


def _path_scopes_overlap(
    left_scopes: tuple[str, ...],
    right_scopes: tuple[str, ...],
) -> bool:
    for left in left_scopes:
        for right in right_scopes:
            if _path_scope_overlaps(left, right):
                return True
    return False


def _path_scope_overlaps(left: str, right: str) -> bool:
    if "." in {left, right}:
        return True
    return (
        left == right
        or left.startswith(f"{right}/")
        or right.startswith(f"{left}/")
    )


def _normalize_root(value: str) -> str:
    return re.sub(r"/+", "/", value.strip().replace("\\", "/")).rstrip("/").lower()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _required_text(source: Mapping[str, object], *keys: str) -> str:
    value = _optional_text(source, *keys)
    if value is None:
        raise ValueError(f"{keys[0]} is required.")
    return value


def _optional_text(source: Mapping[str, object], *keys: str) -> str | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{keys[0]} must be a non-empty string.")
    if "\x00" in value:
        raise ValueError(f"{keys[0]} must not contain null bytes.")
    return value.strip()


def _optional_int(source: Mapping[str, object], *keys: str) -> int | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{keys[0]} must be an integer.")
    return value


def _optional_bool(
    source: Mapping[str, object],
    *keys: str,
    default: bool | None = None,
) -> bool | None:
    value = _optional_value(source, *keys)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{keys[0]} must be a boolean.")
    return value


def _optional_mapping(
    source: Mapping[str, object],
    *keys: str,
) -> Mapping[str, object] | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{keys[0]} must be an object.")
    return dict(value)


def _optional_value(source: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in source:
            return source[key]
    return None


def _optional_datetime(source: Mapping[str, object], *keys: str) -> datetime | None:
    value = _optional_value(source, *keys)
    if value is None:
        return None
    if isinstance(value, datetime):
        _require_utc_aware(value, keys[0])
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{keys[0]} must be an ISO datetime string.")
    parsed = datetime.fromisoformat(value.strip())
    _require_utc_aware(parsed, keys[0])
    return parsed


def _text_tuple(value: object | None, logical_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (_require_text_value(value, logical_name),)
    if not isinstance(value, Sequence):
        raise ValueError(f"{logical_name} must be a string or array of strings.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{logical_name} must contain non-empty strings.")
        result.append(item.strip())
    return tuple(result)


def _path_scope_tuple(value: object | None, logical_name: str) -> tuple[str, ...]:
    scopes = _text_tuple(value, logical_name)
    return _validate_path_scopes(scopes or (".",))


def _validate_path_scopes(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        scope = _normalize_path_scope(value)
        if scope in seen:
            raise ValueError("declaredPathScopes must not contain duplicate values.")
        seen.add(scope)
        normalized.append(scope)
    if not normalized:
        raise ValueError("declaredPathScopes must not be empty.")
    return tuple(normalized)


def _normalize_path_scope(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("declaredPathScopes must contain non-empty strings.")
    if "\x00" in value:
        raise ValueError("declaredPathScopes must not contain null bytes.")
    normalized = re.sub(r"/+", "/", value.strip().replace("\\", "/"))
    normalized = normalized.strip("/")
    if normalized in {"", "."}:
        return "."
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise ValueError("declaredPathScopes must not contain parent traversal.")
    return "/".join(parts)


def _require_text_value(value: str, logical_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")
    return value.strip()


def _validate_text(value: str, logical_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")
    if "\x00" in value:
        raise ValueError(f"{logical_name} must not contain null bytes.")


def _validate_optional_text(value: str | None, logical_name: str) -> None:
    if value is not None:
        _validate_text(value, logical_name)


def _validate_text_tuple(values: tuple[str, ...], logical_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        _validate_text(value, logical_name)
        if value in seen:
            raise ValueError(f"{logical_name} must not contain duplicate values.")
        seen.add(value)


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")


def _enum_value(enum_type, value, logical_name: str):
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")
    normalized = value.strip().lower().replace("-", "_")
    try:
        return enum_type(normalized)
    except ValueError as exc:
        valid = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{logical_name} must be one of: {valid}.") from exc


_SENSITIVE_KEYS = {
    "apikey",
    "authorization",
    "bearertoken",
    "cookie",
    "credential",
    "credentialenvvar",
    "credentialref",
    "credentialreference",
    "password",
    "secret",
    "sessiontoken",
    "token",
}

_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|Bearer\s+sk-|Authorization:\s*Bearer|Cookie:)",
    re.IGNORECASE,
)


def _reject_sensitive_config(source: Mapping[str, object], logical_name: str) -> None:
    for key, value in source.items():
        normalized_key = re.sub(r"[^a-zA-Z0-9]", "", str(key)).lower()
        if normalized_key in _SENSITIVE_KEYS:
            raise ValueError(f"{logical_name}.{key} must not contain credential values.")
        if isinstance(value, str) and _SENSITIVE_TEXT_PATTERN.search(value):
            raise ValueError(f"{logical_name}.{key} must not contain credential values.")
        if isinstance(value, Mapping):
            _reject_sensitive_config(value, f"{logical_name}.{key}")
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    _reject_sensitive_config(item, f"{logical_name}.{key}[{index}]")
                elif isinstance(item, str) and _SENSITIVE_TEXT_PATTERN.search(item):
                    raise ValueError(
                        f"{logical_name}.{key}[{index}] must not contain credential values."
                    )
