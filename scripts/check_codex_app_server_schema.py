from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Mapping, Sequence


REQUIRED_METHODS: Mapping[str, tuple[str, ...]] = {
    "ClientRequest.json": (
        "initialize",
        "thread/read",
        "thread/resume",
        "turn/start",
        "turn/steer",
        "turn/interrupt",
    ),
    "ClientNotification.json": ("initialized",),
    "ServerNotification.json": (
        "thread/status/changed",
        "item/started",
        "item/completed",
        "turn/started",
        "turn/completed",
        "turn/diff/updated",
        "serverRequest/resolved",
        "error",
        "deprecationNotice",
    ),
    "ServerRequest.json": (
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "mcpServer/elicitation/request",
        "item/tool/requestUserInput",
    ),
}


SHAPE_CHECKS = (
    ("v1/InitializeParams.json", (), ("clientInfo",), ("capabilities",)),
    (
        "v1/InitializeResponse.json",
        (),
        ("codexHome", "platformFamily", "platformOs", "userAgent"),
        (),
    ),
    ("v2/ThreadReadParams.json", (), ("threadId",), ("includeTurns",)),
    ("v2/ThreadReadResponse.json", (), ("thread",), ()),
    (
        "v2/ThreadResumeParams.json",
        (),
        ("threadId",),
        ("cwd", "sandbox", "approvalPolicy", "config"),
    ),
    (
        "v2/ThreadResumeResponse.json",
        (),
        (
            "thread",
            "cwd",
            "sandbox",
            "approvalPolicy",
            "approvalsReviewer",
            "model",
            "modelProvider",
        ),
        (),
    ),
    ("v2/TurnStartParams.json", (), ("threadId", "input"), ()),
    ("v2/TurnStartResponse.json", (), ("turn",), ()),
    (
        "v2/TurnSteerParams.json",
        (),
        ("threadId", "input", "expectedTurnId"),
        (),
    ),
    ("v2/TurnSteerResponse.json", (), ("turnId",), ()),
    ("v2/TurnInterruptParams.json", (), ("threadId", "turnId"), ()),
    ("v2/TurnInterruptResponse.json", (), (), ()),
    (
        "CommandExecutionRequestApprovalParams.json",
        (),
        ("threadId", "turnId", "itemId", "startedAtMs"),
        ("command", "cwd"),
    ),
    ("CommandExecutionRequestApprovalResponse.json", (), ("decision",), ()),
    (
        "FileChangeRequestApprovalParams.json",
        (),
        ("threadId", "turnId", "itemId", "startedAtMs"),
        ("reason",),
    ),
    ("FileChangeRequestApprovalResponse.json", (), ("decision",), ()),
    (
        "PermissionsRequestApprovalParams.json",
        (),
        ("threadId", "turnId", "itemId", "startedAtMs", "cwd", "permissions"),
        (),
    ),
    (
        "PermissionsRequestApprovalResponse.json",
        (),
        ("permissions",),
        ("scope",),
    ),
    (
        "McpServerElicitationRequestParams.json",
        (),
        ("threadId", "serverName"),
        ("turnId",),
    ),
    (
        "McpServerElicitationRequestResponse.json",
        (),
        ("action",),
        ("content",),
    ),
    (
        "ToolRequestUserInputParams.json",
        (),
        ("threadId", "turnId", "itemId", "questions"),
        (),
    ),
    ("ToolRequestUserInputResponse.json", (), ("answers",), ()),
    (
        "v2/ServerRequestResolvedNotification.json",
        (),
        ("threadId", "requestId"),
        (),
    ),
    (
        "v2/ItemCompletedNotification.json",
        (),
        ("threadId", "turnId", "item"),
        ("completedAtMs",),
    ),
    (
        "v2/TurnCompletedNotification.json",
        (),
        ("threadId", "turn"),
        (),
    ),
    (
        "v2/TurnCompletedNotification.json",
        ("definitions", "Turn"),
        ("id", "items", "status"),
        ("itemsView", "error"),
    ),
    (
        "v2/ErrorNotification.json",
        (),
        ("threadId", "turnId", "error", "willRetry"),
        (),
    ),
    (
        "v2/ErrorNotification.json",
        ("definitions", "TurnError"),
        ("message",),
        ("codexErrorInfo", "additionalDetails"),
    ),
    (
        "v2/DeprecationNoticeNotification.json",
        (),
        ("summary",),
        ("details",),
    ),
)


REFERENCE_CHECKS = (
    ("v2/ThreadResumeParams.json", ("properties", "sandbox"), "SandboxMode"),
    (
        "v2/ThreadResumeParams.json",
        ("properties", "approvalPolicy"),
        "AskForApproval",
    ),
    (
        "v2/ThreadResumeResponse.json",
        ("properties", "sandbox"),
        "SandboxPolicy",
    ),
    (
        "v2/ThreadResumeResponse.json",
        ("properties", "approvalPolicy"),
        "AskForApproval",
    ),
    (
        "v2/ThreadResumeResponse.json",
        ("properties", "cwd"),
        "AbsolutePathBuf",
    ),
    (
        "CommandExecutionRequestApprovalResponse.json",
        ("properties", "decision"),
        "CommandExecutionApprovalDecision",
    ),
    (
        "FileChangeRequestApprovalResponse.json",
        ("properties", "decision"),
        "FileChangeApprovalDecision",
    ),
    (
        "PermissionsRequestApprovalResponse.json",
        ("properties", "permissions"),
        "GrantedPermissionProfile",
    ),
    (
        "PermissionsRequestApprovalParams.json",
        ("properties", "permissions"),
        "RequestPermissionProfile",
    ),
    (
        "PermissionsRequestApprovalParams.json",
        ("properties", "cwd"),
        "AbsolutePathBuf",
    ),
    (
        "PermissionsRequestApprovalResponse.json",
        ("properties", "scope"),
        "PermissionGrantScope",
    ),
    (
        "McpServerElicitationRequestResponse.json",
        ("properties", "action"),
        "McpServerElicitationAction",
    ),
    (
        "ToolRequestUserInputResponse.json",
        ("properties", "answers", "additionalProperties"),
        "ToolRequestUserInputAnswer",
    ),
)


ENUM_CHECKS = (
    (
        "v2/ThreadResumeParams.json",
        ("definitions", "SandboxMode"),
        ("read-only", "workspace-write", "danger-full-access"),
    ),
    (
        "v2/ThreadResumeParams.json",
        ("definitions", "AskForApproval"),
        ("untrusted", "on-request", "never"),
    ),
    (
        "v2/ThreadResumeResponse.json",
        ("definitions", "SandboxPolicy"),
        ("readOnly", "workspaceWrite", "dangerFullAccess"),
    ),
    (
        "CommandExecutionRequestApprovalResponse.json",
        ("definitions", "CommandExecutionApprovalDecision"),
        ("accept", "acceptForSession", "decline", "cancel"),
    ),
    (
        "FileChangeRequestApprovalResponse.json",
        ("definitions", "FileChangeApprovalDecision"),
        ("accept", "acceptForSession", "decline", "cancel"),
    ),
    (
        "PermissionsRequestApprovalResponse.json",
        ("definitions", "PermissionGrantScope"),
        ("turn", "session"),
    ),
    (
        "McpServerElicitationRequestResponse.json",
        ("definitions", "McpServerElicitationAction"),
        ("accept", "decline", "cancel"),
    ),
)


TYPE_CHECKS = (
    ("v1/InitializeParams.json", ("definitions", "InitializeCapabilities", "properties", "experimentalApi"), "boolean"),
    ("v2/ThreadReadParams.json", ("properties", "threadId"), "string"),
    ("v2/ThreadReadParams.json", ("properties", "includeTurns"), "boolean"),
    ("v2/ThreadResumeParams.json", ("properties", "threadId"), "string"),
    ("v2/ThreadResumeParams.json", ("properties", "cwd"), "string"),
    ("v2/ThreadResumeParams.json", ("properties", "config"), "object"),
    ("v2/TurnStartParams.json", ("properties", "threadId"), "string"),
    ("v2/TurnStartParams.json", ("properties", "input"), "array"),
    ("v2/TurnSteerParams.json", ("properties", "threadId"), "string"),
    ("v2/TurnSteerParams.json", ("properties", "expectedTurnId"), "string"),
    ("v2/TurnSteerParams.json", ("properties", "input"), "array"),
    ("v2/TurnSteerResponse.json", ("properties", "turnId"), "string"),
    ("v2/TurnInterruptParams.json", ("properties", "threadId"), "string"),
    ("v2/TurnInterruptParams.json", ("properties", "turnId"), "string"),
    ("CommandExecutionRequestApprovalParams.json", ("properties", "threadId"), "string"),
    ("CommandExecutionRequestApprovalParams.json", ("properties", "turnId"), "string"),
    ("CommandExecutionRequestApprovalParams.json", ("properties", "itemId"), "string"),
    ("CommandExecutionRequestApprovalParams.json", ("properties", "startedAtMs"), "integer"),
    ("FileChangeRequestApprovalParams.json", ("properties", "threadId"), "string"),
    ("FileChangeRequestApprovalParams.json", ("properties", "turnId"), "string"),
    ("FileChangeRequestApprovalParams.json", ("properties", "itemId"), "string"),
    ("FileChangeRequestApprovalParams.json", ("properties", "startedAtMs"), "integer"),
    ("PermissionsRequestApprovalParams.json", ("properties", "threadId"), "string"),
    ("PermissionsRequestApprovalParams.json", ("properties", "turnId"), "string"),
    ("PermissionsRequestApprovalParams.json", ("properties", "itemId"), "string"),
    ("PermissionsRequestApprovalParams.json", ("properties", "startedAtMs"), "integer"),
    ("McpServerElicitationRequestParams.json", ("properties", "threadId"), "string"),
    ("McpServerElicitationRequestParams.json", ("properties", "turnId"), "string"),
    ("McpServerElicitationRequestParams.json", ("properties", "serverName"), "string"),
    ("ToolRequestUserInputParams.json", ("properties", "threadId"), "string"),
    ("ToolRequestUserInputParams.json", ("properties", "turnId"), "string"),
    ("ToolRequestUserInputParams.json", ("properties", "itemId"), "string"),
    ("ToolRequestUserInputParams.json", ("properties", "questions"), "array"),
    ("ToolRequestUserInputResponse.json", ("properties", "answers"), "object"),
)


def check_schema_bundle(schema_directory: Path) -> Mapping[str, object]:
    root = _resolve_schema_root(schema_directory)
    errors: list[str] = []
    checked_files: set[str] = set()
    observed_methods: dict[str, list[str]] = {}

    for relative, required_methods in REQUIRED_METHODS.items():
        document = _load_document(root, relative, errors)
        if document is None:
            continue
        checked_files.add(relative)
        observed = _method_values(document)
        observed_methods[relative] = sorted(observed)
        missing = sorted(set(required_methods) - observed)
        if missing:
            errors.append(f"{relative} is missing methods: {', '.join(missing)}")

    for relative, node_path, required_fields, available_fields in SHAPE_CHECKS:
        document = _load_document(root, relative, errors)
        if document is None:
            continue
        checked_files.add(relative)
        node = _mapping_node(document, node_path)
        if node is None:
            location = "/".join(node_path) or "<root>"
            errors.append(f"{relative} is missing schema node {location}")
            continue
        properties = node.get("properties")
        property_names = set(properties) if isinstance(properties, Mapping) else set()
        declared_required = node.get("required")
        required_names = (
            {item for item in declared_required if isinstance(item, str)}
            if isinstance(declared_required, list)
            else set()
        )
        for field in required_fields:
            if field not in property_names:
                errors.append(f"{relative} is missing property {field}")
            elif field not in required_names:
                errors.append(f"{relative} no longer requires property {field}")
        for field in available_fields:
            if field not in property_names:
                errors.append(f"{relative} is missing compatible property {field}")

    for relative, node_path, expected_definition in REFERENCE_CHECKS:
        document = _load_document(root, relative, errors)
        if document is None:
            continue
        checked_files.add(relative)
        node = _mapping_node(document, node_path)
        location = "/".join(node_path)
        if node is None:
            errors.append(f"{relative} is missing schema node {location}")
            continue
        references = _reference_values(node)
        if not any(ref.rsplit("/", 1)[-1] == expected_definition for ref in references):
            errors.append(
                f"{relative} {location} no longer references {expected_definition}"
            )

    for relative, node_path, required_values in ENUM_CHECKS:
        document = _load_document(root, relative, errors)
        if document is None:
            continue
        checked_files.add(relative)
        node = _mapping_node(document, node_path)
        location = "/".join(node_path)
        if node is None:
            errors.append(f"{relative} is missing schema node {location}")
            continue
        observed_values = _literal_values(node)
        missing_values = sorted(set(required_values) - observed_values)
        if missing_values:
            errors.append(
                f"{relative} {location} is missing enum/const values: "
                f"{', '.join(missing_values)}"
            )

    for relative, node_path, required_type in TYPE_CHECKS:
        document = _load_document(root, relative, errors)
        if document is None:
            continue
        checked_files.add(relative)
        node = _mapping_node(document, node_path)
        location = "/".join(node_path)
        if node is None:
            errors.append(f"{relative} is missing schema node {location}")
            continue
        observed_types = _type_values(node)
        if required_type not in observed_types:
            errors.append(
                f"{relative} {location} no longer permits type {required_type}"
            )

    initialize = _load_document(root, "v1/InitializeParams.json", errors)
    if initialize is not None:
        experimental = _mapping_node(
            initialize,
            (
                "definitions",
                "InitializeCapabilities",
                "properties",
                "experimentalApi",
            ),
        )
        if experimental is None or experimental.get("default") is not False:
            errors.append(
                "v1/InitializeParams.json experimentalApi must remain opt-in with default false"
            )

    resume_params = _load_document(root, "v2/ThreadResumeParams.json", errors)
    if resume_params is not None:
        ask_for_approval = _mapping_node(
            resume_params,
            ("definitions", "AskForApproval"),
        )
        if ask_for_approval is None:
            errors.append(
                "v2/ThreadResumeParams.json is missing AskForApproval"
            )
        else:
            property_names = _property_names(ask_for_approval)
            required_names = _required_names(ask_for_approval)
            expected_properties = {
                "granular",
                "mcp_elicitations",
                "request_permissions",
                "rules",
                "sandbox_approval",
                "skill_approval",
            }
            missing_properties = sorted(expected_properties - property_names)
            if missing_properties:
                errors.append(
                    "v2/ThreadResumeParams.json AskForApproval granular object "
                    f"is missing properties: {', '.join(missing_properties)}"
                )
            expected_required = {
                "granular",
                "mcp_elicitations",
                "rules",
                "sandbox_approval",
            }
            missing_required = sorted(expected_required - required_names)
            if missing_required:
                errors.append(
                    "v2/ThreadResumeParams.json AskForApproval granular object "
                    f"no longer requires: {', '.join(missing_required)}"
                )

    notifications = set(observed_methods.get("ServerNotification.json", ()))
    tool_input = _load_document(root, "ToolRequestUserInputParams.json", errors)
    tool_input_properties = (
        set(tool_input.get("properties", {}))
        if isinstance(tool_input, Mapping)
        and isinstance(tool_input.get("properties"), Mapping)
        else set()
    )
    deprecated_observed = sorted(
        notifications
        & {
            "item/fileChange/outputDelta",
            "item/agentMessage/delta",
            "item/commandExecution/outputDelta",
        }
    )
    out_of_scope_observed = sorted(
        (
            set(observed_methods.get("ClientRequest.json", ()))
            | notifications
        )
        & {"thread/rollback"}
    )

    return {
        "schema": "beacon_codex_app_server_schema_check.v2",
        "ok": not errors,
        "schemaRoot": str(root),
        "checkedFiles": sorted(checked_files),
        "requiredMethods": {
            relative: list(methods) for relative, methods in REQUIRED_METHODS.items()
        },
        "deprecatedCompatibilityMethodsObserved": deprecated_observed,
        "outOfScopeMethodsObserved": out_of_scope_observed,
        "stableApiOnly": True,
        "experimentalApiRequired": False,
        "observedCompatibilityFeatures": {
            "toolRequestUserInputIsBlocking": "isBlocking" in tool_input_properties,
            "resumeReturnsEffectivePolicy": True,
        },
        "errors": errors,
    }


def generate_schema_bundle(
    executable: str,
    output_directory: Path,
    *,
    timeout_seconds: float = 30.0,
) -> None:
    completed = subprocess.run(
        (
            executable,
            "app-server",
            "generate-json-schema",
            "--out",
            str(output_directory),
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            "Codex app-server schema generation failed"
            f" with exit code {completed.returncode}: {detail[-1000:]}"
        )


def _resolve_schema_root(schema_directory: Path) -> Path:
    root = schema_directory.resolve()
    if (root / "ClientRequest.json").is_file():
        return root
    if (root / "json" / "ClientRequest.json").is_file():
        return root / "json"
    return root


def _load_document(
    root: Path,
    relative: str,
    errors: list[str],
) -> Mapping[str, object] | None:
    path = root / Path(relative)
    if not path.is_file():
        missing = f"missing schema file: {relative}"
        if missing not in errors:
            errors.append(missing)
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"could not read {relative}: {exc}")
        return None
    if not isinstance(value, Mapping):
        errors.append(f"{relative} must contain a JSON object")
        return None
    return value


def _mapping_node(
    document: Mapping[str, object],
    path: Sequence[str],
) -> Mapping[str, object] | None:
    current: object = document
    for segment in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(segment)
    return current if isinstance(current, Mapping) else None


def _method_values(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            method = properties.get("method")
            if isinstance(method, Mapping):
                enum = method.get("enum")
                if isinstance(enum, list):
                    result.update(item for item in enum if isinstance(item, str))
        for child in value.values():
            result.update(_method_values(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_method_values(child))
    return result


def _reference_values(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if isinstance(reference, str):
            result.add(reference)
        for child in value.values():
            result.update(_reference_values(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_reference_values(child))
    return result


def _literal_values(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        enum = value.get("enum")
        if isinstance(enum, list):
            result.update(item for item in enum if isinstance(item, str))
        const = value.get("const")
        if isinstance(const, str):
            result.add(const)
        for child in value.values():
            result.update(_literal_values(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_literal_values(child))
    return result


def _type_values(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        declared = value.get("type")
        if isinstance(declared, str):
            result.add(declared)
        elif isinstance(declared, list):
            result.update(item for item in declared if isinstance(item, str))
        for key in ("anyOf", "oneOf", "allOf"):
            children = value.get(key)
            if isinstance(children, list):
                for child in children:
                    result.update(_type_values(child))
    return result


def _property_names(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            result.update(str(name) for name in properties)
        for child in value.values():
            result.update(_property_names(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_property_names(child))
    return result


def _required_names(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        required = value.get("required")
        if isinstance(required, list):
            result.update(item for item in required if isinstance(item, str))
        for child in value.values():
            result.update(_required_names(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_required_names(child))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Beacon's stable Codex app-server schema subset."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--schema-dir", type=Path)
    source.add_argument("--codex-executable")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    if args.schema_dir is not None:
        result = check_schema_bundle(args.schema_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="beacon-codex-schema-") as directory:
            output = Path(directory)
            try:
                generate_schema_bundle(
                    args.codex_executable,
                    output,
                    timeout_seconds=args.timeout_seconds,
                )
                result = check_schema_bundle(output)
            except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
                result = {
                    "schema": "beacon_codex_app_server_schema_check.v2",
                    "ok": False,
                    "schemaRoot": str(output),
                    "checkedFiles": [],
                    "errors": [f"{exc.__class__.__name__}: {exc}"],
                }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
