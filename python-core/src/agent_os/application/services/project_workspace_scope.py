from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import json
import os
from pathlib import Path
from threading import RLock
import time
from typing import Iterator, Mapping
from uuid import uuid4


PROJECT_WORKSPACE_MARKER_SCHEMA = "beacon_project_workspace.v1"
PROJECT_WORKSPACE_MARKER_RELATIVE_PATH = Path(".beacon") / "workspace.json"
_PROJECT_WORKSPACE_MARKER_THREAD_LOCK = RLock()


@dataclass(frozen=True, slots=True)
class ProjectWorkspaceScope:
    marker_path: Path
    project_root: Path
    workspace_id: str
    profile_path: Path

    def to_metadata(self) -> Mapping[str, object]:
        return {
            "schema": PROJECT_WORKSPACE_MARKER_SCHEMA,
            "markerPath": str(self.marker_path),
            "projectRoot": str(self.project_root),
            "workspaceId": self.workspace_id,
            "profilePath": str(self.profile_path),
            "profileSource": "nearest_project_marker",
            "databaseScanned": False,
        }


def find_nearest_project_workspace_scope(
    start: str | Path | None = None,
) -> ProjectWorkspaceScope | None:
    current = Path(start or Path.cwd()).expanduser().resolve(strict=False)
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        marker_path = directory / PROJECT_WORKSPACE_MARKER_RELATIVE_PATH
        if marker_path.is_file():
            return read_project_workspace_scope(marker_path)
    return None


def read_project_workspace_scope(marker_path: str | Path) -> ProjectWorkspaceScope:
    path = Path(marker_path).expanduser().resolve(strict=False)
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("project workspace marker must be a JSON object.")
    if loaded.get("schema") != PROJECT_WORKSPACE_MARKER_SCHEMA:
        raise ValueError(
            "project workspace marker schema must be "
            f"{PROJECT_WORKSPACE_MARKER_SCHEMA}."
        )
    workspace_id = _required_text(loaded.get("workspaceId"), "workspaceId")
    raw_profile_path = _required_text(loaded.get("profilePath"), "profilePath")
    project_root = path.parent.parent.resolve(strict=False)
    profile_path = Path(raw_profile_path).expanduser()
    if not profile_path.is_absolute():
        profile_path = project_root / profile_path
    return ProjectWorkspaceScope(
        marker_path=path,
        project_root=project_root,
        workspace_id=workspace_id,
        profile_path=profile_path.resolve(strict=False),
    )


def project_workspace_marker_payload(
    *,
    project_root: str | Path,
    workspace_id: str,
    profile_path: str | Path,
) -> Mapping[str, object]:
    root = Path(project_root).expanduser().resolve(strict=False)
    profile = Path(profile_path).expanduser().resolve(strict=False)
    try:
        stored_profile = profile.relative_to(root).as_posix()
        profile_path_kind = "project_relative"
    except ValueError:
        stored_profile = str(profile)
        profile_path_kind = "local_absolute"
    return {
        "schema": PROJECT_WORKSPACE_MARKER_SCHEMA,
        "workspaceId": _required_text(workspace_id, "workspaceId"),
        "profilePath": stored_profile,
        "profilePathKind": profile_path_kind,
        "localOnly": True,
        "databaseScanned": False,
    }


def validate_project_workspace_marker_target(
    marker_path: str | Path,
    *,
    workspace_id: str,
    profile_path: str | Path,
) -> ProjectWorkspaceScope | None:
    path = Path(marker_path).expanduser().resolve(strict=False)
    if not path.exists():
        return None
    existing = read_project_workspace_scope(path)
    expected_profile = Path(profile_path).expanduser().resolve(strict=False)
    if (
        existing.workspace_id != _required_text(workspace_id, "workspaceId")
        or existing.profile_path != expected_profile
    ):
        raise ValueError(
            "workspace_scope_conflict: project marker is already bound to "
            f"workspaceId={existing.workspace_id} profilePath={existing.profile_path}."
        )
    return existing


def resolve_runtime_profile_from_project_scope(
    *,
    explicit_profile_path: str | None,
    environment_profile_path: str | None,
    start: str | Path | None = None,
) -> tuple[str | None, ProjectWorkspaceScope | None, str]:
    scope = find_nearest_project_workspace_scope(start)
    selected = _optional_resolved_path(explicit_profile_path)
    source = "explicit_cli" if selected is not None else "none"
    if selected is None:
        selected = _optional_resolved_path(environment_profile_path)
        if selected is not None:
            source = "environment"
    if selected is not None:
        if scope is not None and selected != scope.profile_path:
            raise ValueError(
                "workspace_scope_conflict: selected profile does not match the "
                f"nearest project marker ({scope.marker_path})."
            )
        return str(selected), scope, source
    if scope is not None:
        return str(scope.profile_path), scope, "nearest_project_marker"
    return None, None, "none"


def write_json_atomic(path: str | Path, payload: Mapping[str, object]) -> None:
    target = Path(path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_project_workspace_marker_atomic(
    marker_path: str | Path,
    *,
    workspace_id: str,
    profile_path: str | Path,
    payload: Mapping[str, object],
    lock_timeout_seconds: float = 10.0,
) -> ProjectWorkspaceScope:
    """Validate and replace one marker while holding a cross-process lock."""

    target = Path(marker_path).expanduser().resolve(strict=False)
    with _project_workspace_marker_lock(
        target,
        timeout_seconds=lock_timeout_seconds,
    ):
        validate_project_workspace_marker_target(
            target,
            workspace_id=workspace_id,
            profile_path=profile_path,
        )
        write_json_atomic(target, payload)
        return read_project_workspace_scope(target)


@contextmanager
def _project_workspace_marker_lock(
    marker_path: Path,
    *,
    timeout_seconds: float,
) -> Iterator[None]:
    if timeout_seconds <= 0:
        raise ValueError("lockTimeoutSeconds must be greater than zero.")
    lock_path = marker_path.with_name(f"{marker_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    with _PROJECT_WORKSPACE_MARKER_THREAD_LOCK:
        with lock_path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            acquired = False
            while not acquired:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "workspace_scope_lock_timeout: project marker is busy."
                        ) from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _optional_resolved_path(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    return Path(value).expanduser().resolve(strict=False)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()
