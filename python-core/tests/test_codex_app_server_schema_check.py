from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


BEACON_ROOT = Path(__file__).resolve().parents[2]
if str(BEACON_ROOT) not in sys.path:
    sys.path.insert(0, str(BEACON_ROOT))

from scripts import check_codex_app_server_schema as MODULE


class CodexAppServerSchemaCheckTests(unittest.TestCase):
    def test_accepts_beacon_stable_subset_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_valid_bundle(root)

            result = MODULE.check_schema_bundle(root)

            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(
                result["schema"],
                "beacon_codex_app_server_schema_check.v2",
            )

    def test_reports_missing_method_and_compatible_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_valid_bundle(root)
            _write_method_schema(
                root / "ClientRequest.json",
                tuple(
                    method
                    for method in MODULE.REQUIRED_METHODS["ClientRequest.json"]
                    if method != "turn/steer"
                ),
            )
            error_path = root / "v2" / "ErrorNotification.json"
            error_schema = json.loads(error_path.read_text(encoding="utf-8"))
            del error_schema["definitions"]["TurnError"]["properties"][
                "additionalDetails"
            ]
            _write_json(error_path, error_schema)

            result = MODULE.check_schema_bundle(root)

            self.assertFalse(result["ok"])
            errors = "\n".join(result["errors"])
            self.assertIn("turn/steer", errors)
            self.assertIn("additionalDetails", errors)

    def test_reports_missing_enum_and_response_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_valid_bundle(root)
            resume_path = root / "v2" / "ThreadResumeParams.json"
            resume = json.loads(resume_path.read_text(encoding="utf-8"))
            resume["definitions"]["SandboxMode"]["enum"].remove(
                "danger-full-access"
            )
            _write_json(resume_path, resume)
            response_path = root / "CommandExecutionRequestApprovalResponse.json"
            response = json.loads(response_path.read_text(encoding="utf-8"))
            response["properties"]["decision"]["$ref"] = (
                "#/definitions/UnexpectedDecision"
            )
            _write_json(response_path, response)

            result = MODULE.check_schema_bundle(root)

            self.assertFalse(result["ok"])
            errors = "\n".join(result["errors"])
            self.assertIn("danger-full-access", errors)
            self.assertIn("CommandExecutionApprovalDecision", errors)


def _write_valid_bundle(root: Path) -> None:
    for relative, methods in MODULE.REQUIRED_METHODS.items():
        _write_method_schema(root / relative, methods)

    _write_json(
        root / "v1" / "InitializeParams.json",
        {
            "required": ["clientInfo"],
            "properties": {
                "clientInfo": {},
                "capabilities": {
                    "anyOf": [
                        {"$ref": "#/definitions/InitializeCapabilities"},
                        {"type": "null"},
                    ]
                },
            },
            "definitions": {
                "InitializeCapabilities": {
                    "type": "object",
                    "properties": {
                        "experimentalApi": {"type": "boolean", "default": False}
                    },
                }
            },
        },
    )
    _write_shape(
        root / "v1" / "InitializeResponse.json",
        ("codexHome", "platformFamily", "platformOs", "userAgent"),
    )
    _write_shape(root / "v2" / "ThreadReadParams.json", ("threadId",), ("includeTurns",))
    _write_shape(root / "v2" / "ThreadReadResponse.json", ("thread",))
    _write_json(
        root / "v2" / "ThreadResumeParams.json",
        {
            "required": ["threadId"],
            "properties": {
                "threadId": {"type": "string"},
                "cwd": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "sandbox": {
                    "anyOf": [
                        {"$ref": "#/definitions/SandboxMode"},
                        {"type": "null"},
                    ]
                },
                "approvalPolicy": {
                    "anyOf": [
                        {"$ref": "#/definitions/AskForApproval"},
                        {"type": "null"},
                    ]
                },
                "config": {"type": ["object", "null"]},
            },
            "definitions": {
                "SandboxMode": {
                    "enum": ["read-only", "workspace-write", "danger-full-access"]
                },
                "AskForApproval": {
                    "oneOf": [
                        {"enum": ["untrusted"]},
                        {"enum": ["on-request"]},
                        {"enum": ["never"]},
                        {
                            "type": "object",
                            "required": ["granular"],
                            "properties": {
                                "granular": {
                                    "type": "object",
                                    "required": [
                                        "mcp_elicitations",
                                        "rules",
                                        "sandbox_approval",
                                    ],
                                    "properties": {
                                        "mcp_elicitations": {"type": "boolean"},
                                        "request_permissions": {"type": "boolean"},
                                        "rules": {"type": "boolean"},
                                        "sandbox_approval": {"type": "boolean"},
                                        "skill_approval": {"type": "boolean"},
                                    },
                                }
                            },
                        },
                    ]
                },
            },
        },
    )
    _write_json(
        root / "v2" / "ThreadResumeResponse.json",
        {
            "required": [
                "thread",
                "cwd",
                "sandbox",
                "approvalPolicy",
                "approvalsReviewer",
                "model",
                "modelProvider",
            ],
            "properties": {
                "thread": {},
                "cwd": {"$ref": "#/definitions/AbsolutePathBuf"},
                "sandbox": {"$ref": "#/definitions/SandboxPolicy"},
                "approvalPolicy": {"$ref": "#/definitions/AskForApproval"},
                "approvalsReviewer": {},
                "model": {},
                "modelProvider": {},
            },
            "definitions": {
                "AbsolutePathBuf": {"type": "string"},
                "SandboxPolicy": {
                    "oneOf": [
                        {"properties": {"type": {"enum": ["readOnly"]}}},
                        {"properties": {"type": {"enum": ["workspaceWrite"]}}},
                        {"properties": {"type": {"enum": ["dangerFullAccess"]}}},
                    ]
                },
                "AskForApproval": {"enum": ["untrusted", "on-request", "never"]},
            },
        },
    )
    _write_shape(root / "v2" / "TurnStartParams.json", ("threadId", "input"))
    _write_shape(root / "v2" / "TurnStartResponse.json", ("turn",))
    _write_shape(
        root / "v2" / "TurnSteerParams.json",
        ("threadId", "input", "expectedTurnId"),
    )
    _write_shape(root / "v2" / "TurnSteerResponse.json", ("turnId",))
    _write_shape(root / "v2" / "TurnInterruptParams.json", ("threadId", "turnId"))
    _write_shape(root / "v2" / "TurnInterruptResponse.json", ())
    _write_shape(
        root / "CommandExecutionRequestApprovalParams.json",
        ("threadId", "turnId", "itemId", "startedAtMs"),
        ("command", "cwd"),
    )
    _write_enum_response(
        root / "CommandExecutionRequestApprovalResponse.json",
        property_name="decision",
        definition_name="CommandExecutionApprovalDecision",
        values=("accept", "acceptForSession", "decline", "cancel"),
    )
    _write_shape(
        root / "FileChangeRequestApprovalParams.json",
        ("threadId", "turnId", "itemId", "startedAtMs"),
        ("reason",),
    )
    _write_enum_response(
        root / "FileChangeRequestApprovalResponse.json",
        property_name="decision",
        definition_name="FileChangeApprovalDecision",
        values=("accept", "acceptForSession", "decline", "cancel"),
    )
    _write_shape(
        root / "PermissionsRequestApprovalParams.json",
        ("threadId", "turnId", "itemId", "startedAtMs", "cwd", "permissions"),
    )
    _write_json(
        root / "PermissionsRequestApprovalResponse.json",
        {
            "required": ["permissions"],
            "properties": {
                "permissions": {
                    "$ref": "#/definitions/GrantedPermissionProfile"
                },
                "scope": {"$ref": "#/definitions/PermissionGrantScope"},
            },
            "definitions": {
                "GrantedPermissionProfile": {"type": "object"},
                "PermissionGrantScope": {"enum": ["turn", "session"]},
            },
        },
    )
    _write_shape(
        root / "McpServerElicitationRequestParams.json",
        ("threadId", "serverName"),
        ("turnId",),
    )
    _write_enum_response(
        root / "McpServerElicitationRequestResponse.json",
        property_name="action",
        definition_name="McpServerElicitationAction",
        values=("accept", "decline", "cancel"),
        optional=("content",),
    )
    _write_shape(
        root / "ToolRequestUserInputParams.json",
        ("threadId", "turnId", "itemId", "questions"),
        ("isBlocking",),
    )
    _write_json(
        root / "ToolRequestUserInputResponse.json",
        {
            "required": ["answers"],
            "properties": {
                "answers": {
                    "type": "object",
                    "additionalProperties": {
                        "$ref": "#/definitions/ToolRequestUserInputAnswer"
                    },
                }
            },
            "definitions": {"ToolRequestUserInputAnswer": {"type": "object"}},
        },
    )
    _write_shape(
        root / "v2" / "ServerRequestResolvedNotification.json",
        ("threadId", "requestId"),
    )
    _write_shape(
        root / "v2" / "ItemCompletedNotification.json",
        ("threadId", "turnId", "item"),
        ("completedAtMs",),
    )
    _write_json(
        root / "v2" / "TurnCompletedNotification.json",
        {
            "required": ["threadId", "turn"],
            "properties": {"threadId": {}, "turn": {}},
            "definitions": {
                "Turn": {
                    "required": ["id", "items", "status"],
                    "properties": {
                        "id": {},
                        "items": {},
                        "status": {},
                        "itemsView": {},
                        "error": {},
                    },
                }
            },
        },
    )
    _write_json(
        root / "v2" / "ErrorNotification.json",
        {
            "required": ["threadId", "turnId", "error", "willRetry"],
            "properties": {
                "threadId": {},
                "turnId": {},
                "error": {},
                "willRetry": {},
            },
            "definitions": {
                "TurnError": {
                    "required": ["message"],
                    "properties": {
                        "message": {},
                        "codexErrorInfo": {},
                        "additionalDetails": {},
                    },
                }
            },
        },
    )
    _write_shape(
        root / "v2" / "DeprecationNoticeNotification.json",
        ("summary",),
        ("details",),
    )
    typed_fields = {
        "v2/ThreadReadParams.json": {
            "threadId": "string",
            "includeTurns": "boolean",
        },
        "v2/TurnStartParams.json": {"threadId": "string", "input": "array"},
        "v2/TurnSteerParams.json": {
            "threadId": "string",
            "expectedTurnId": "string",
            "input": "array",
        },
        "v2/TurnSteerResponse.json": {"turnId": "string"},
        "v2/TurnInterruptParams.json": {
            "threadId": "string",
            "turnId": "string",
        },
        "CommandExecutionRequestApprovalParams.json": {
            "threadId": "string",
            "turnId": "string",
            "itemId": "string",
            "startedAtMs": "integer",
        },
        "FileChangeRequestApprovalParams.json": {
            "threadId": "string",
            "turnId": "string",
            "itemId": "string",
            "startedAtMs": "integer",
        },
        "PermissionsRequestApprovalParams.json": {
            "threadId": "string",
            "turnId": "string",
            "itemId": "string",
            "startedAtMs": "integer",
        },
        "McpServerElicitationRequestParams.json": {
            "threadId": "string",
            "turnId": "string",
            "serverName": "string",
        },
        "ToolRequestUserInputParams.json": {
            "threadId": "string",
            "turnId": "string",
            "itemId": "string",
            "questions": "array",
        },
    }
    for relative, field_types in typed_fields.items():
        _set_property_types(root / relative, field_types)
    permissions_path = root / "PermissionsRequestApprovalParams.json"
    permissions = json.loads(permissions_path.read_text(encoding="utf-8"))
    permissions["properties"]["permissions"] = {
        "$ref": "#/definitions/RequestPermissionProfile"
    }
    permissions["properties"]["cwd"] = {
        "$ref": "#/definitions/AbsolutePathBuf"
    }
    permissions["definitions"] = {
        "AbsolutePathBuf": {"type": "string"},
        "RequestPermissionProfile": {"type": "object"}
    }
    _write_json(permissions_path, permissions)


def _write_method_schema(path: Path, methods: tuple[str, ...]) -> None:
    _write_json(
        path,
        {
            "oneOf": [
                {"properties": {"method": {"enum": [method]}}}
                for method in methods
            ]
        },
    )


def _write_shape(
    path: Path,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> None:
    _write_json(
        path,
        {
            "required": list(required),
            "properties": {field: {} for field in (*required, *optional)},
        },
    )


def _write_enum_response(
    path: Path,
    *,
    property_name: str,
    definition_name: str,
    values: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> None:
    _write_json(
        path,
        {
            "required": [property_name],
            "properties": {
                property_name: {"$ref": f"#/definitions/{definition_name}"},
                **{field: {} for field in optional},
            },
            "definitions": {definition_name: {"enum": list(values)}},
        },
    )


def _set_property_types(path: Path, field_types: dict[str, str]) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    for field, field_type in field_types.items():
        value["properties"][field] = {"type": field_type}
    _write_json(path, value)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
