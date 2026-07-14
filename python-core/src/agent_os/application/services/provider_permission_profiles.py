from __future__ import annotations

from typing import Mapping, Sequence


DEFAULT_PERMISSION_PROFILE_FREEZE_NOTE = (
    "No provider permission, sandbox, approval, allowed-tools, settings, or "
    "dangerous-bypass arguments are injected unless explicitly supplied."
)


def claude_permission_profile_metadata(
    *,
    add_dirs: Sequence[str] = (),
    allowed_tools: Sequence[str] = (),
    permission_mode: str | None = None,
    settings_path: str | None = None,
    default_platform_workspace_add_dir: bool = False,
) -> Mapping[str, object]:
    permission_args: list[dict[str, object]] = []
    for tool in allowed_tools:
        permission_args.append(
            {
                "name": "--allowedTools",
                "value": tool,
                "kind": "allowed_tools",
                "source": "explicit_activation_arguments",
            }
        )
    if permission_mode is not None:
        permission_args.append(
            {
                "name": "--permission-mode",
                "value": permission_mode,
                "kind": "permission_mode",
                "source": "explicit_activation_arguments",
            }
        )
    if settings_path is not None:
        permission_args.append(
            {
                "name": "--settings",
                "value": settings_path,
                "kind": "settings_path",
                "source": "explicit_activation_arguments",
            }
        )
    return _permission_profile_metadata(
        provider="claude",
        selected=bool(permission_args),
        selection_source=(
            "explicit_activation_arguments"
            if permission_args
            else "default_no_permission_profile"
        ),
        permission_args=permission_args,
        path_reachability_args=_add_dir_path_args(
            add_dirs,
            default_platform_workspace_add_dir=default_platform_workspace_add_dir,
        ),
        retained_default_disabled_args=(
            "--allowedTools",
            "--permission-mode",
            "--settings",
            "--dangerously-skip-permissions",
            "--allow-dangerously-skip-permissions",
        ),
        dangerous_bypass_args=(
            "--dangerously-skip-permissions",
            "--allow-dangerously-skip-permissions",
        ),
    )


def codex_permission_profile_metadata(
    *,
    add_dirs: Sequence[str] = (),
    sandbox_mode: str | None = None,
    approval_policy: str | None = None,
    default_platform_workspace_add_dir: bool = False,
) -> Mapping[str, object]:
    permission_args: list[dict[str, object]] = []
    if sandbox_mode is not None:
        permission_args.append(
            {
                "name": "--sandbox",
                "value": sandbox_mode,
                "kind": "sandbox",
                "source": "explicit_activation_arguments",
            }
        )
    if approval_policy is not None:
        permission_args.append(
            {
                "name": "--ask-for-approval",
                "value": approval_policy,
                "kind": "approval_policy",
                "source": "explicit_activation_arguments",
            }
        )
    return _permission_profile_metadata(
        provider="codex",
        selected=bool(permission_args),
        selection_source=(
            "explicit_activation_arguments"
            if permission_args
            else "default_no_permission_profile"
        ),
        permission_args=permission_args,
        path_reachability_args=_add_dir_path_args(
            add_dirs,
            default_platform_workspace_add_dir=default_platform_workspace_add_dir,
        ),
        retained_default_disabled_args=(
            "--sandbox",
            "--ask-for-approval",
            "--dangerously-bypass-approvals-and-sandbox",
            "--dangerously-bypass-hook-trust",
        ),
        dangerous_bypass_args=(
            "--dangerously-bypass-approvals-and-sandbox",
            "--dangerously-bypass-hook-trust",
        ),
    )


def hermes_permission_profile_metadata(
    *,
    max_turns: int | None = None,
) -> Mapping[str, object]:
    metadata = _permission_profile_metadata(
        provider="hermes",
        selected=False,
        selection_source="default_no_permission_profile",
        permission_args=(),
        path_reachability_args=(),
        retained_default_disabled_args=("--yolo",),
        dangerous_bypass_args=("--yolo",),
    )
    if max_turns is not None:
        metadata = {
            **metadata,
            "executionLimitArgs": [
                {
                    "name": "--max-turns",
                    "value": max_turns,
                    "kind": "execution_limit",
                    "source": "explicit_activation_arguments",
                }
            ],
        }
    return metadata


def default_provider_permission_profile_metadata(provider: str) -> Mapping[str, object]:
    normalized = provider.strip().lower()
    if normalized == "claude":
        return claude_permission_profile_metadata()
    if normalized == "codex":
        return codex_permission_profile_metadata()
    if normalized == "hermes":
        return hermes_permission_profile_metadata()
    return _permission_profile_metadata(
        provider=normalized,
        selected=False,
        selection_source="default_no_permission_profile",
        permission_args=(),
        path_reachability_args=(),
        retained_default_disabled_args=(),
        dangerous_bypass_args=(),
    )


def _permission_profile_metadata(
    *,
    provider: str,
    selected: bool,
    selection_source: str,
    permission_args: Sequence[Mapping[str, object]],
    path_reachability_args: Sequence[Mapping[str, object]],
    retained_default_disabled_args: Sequence[str],
    dangerous_bypass_args: Sequence[str],
) -> dict[str, object]:
    return {
        "schema": "provider_permission_profile_selection.v1",
        "provider": provider,
        "selected": selected,
        "selectionSource": selection_source,
        "permissionPostureChangingArgsInjected": bool(permission_args),
        "permissionArgs": [dict(item) for item in permission_args],
        "pathReachabilityArgs": [dict(item) for item in path_reachability_args],
        "dangerousBypassArgs": list(dangerous_bypass_args),
        "dangerousBypassEnabled": False,
        "retainedDefaultDisabledArgs": list(retained_default_disabled_args),
        "defaultFreeze": DEFAULT_PERMISSION_PROFILE_FREEZE_NOTE,
    }


def _add_dir_path_args(
    add_dirs: Sequence[str],
    *,
    default_platform_workspace_add_dir: bool,
) -> tuple[Mapping[str, object], ...]:
    result: list[Mapping[str, object]] = []
    for index, value in enumerate(add_dirs):
        result.append(
            {
                "name": "--add-dir",
                "value": value,
                "kind": "path_reachability",
                "source": (
                    "default_platform_workspace_root"
                    if index == 0 and default_platform_workspace_add_dir
                    else "explicit_activation_arguments"
                ),
            }
        )
    return tuple(result)
