from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Iterable, Sequence

try:
    from scripts.check_versions import check_versions
except ModuleNotFoundError:  # Direct execution: python scripts/release_check.py
    from check_versions import check_versions


TEXT_SUFFIXES = {
    ".cfg",
    ".cmd",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".package-venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}
GENERATED_TOP_LEVEL_DIRECTORIES = {
    ".agent_os",
    ".beacon",
    "codex-output",
    "daemon-logs",
    "plugins",
    "runtime",
    "workspace",
}
REQUIRED_DOCUMENTS = (
    "README.md",
    "README.en.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "NOTICE",
)
PLACEHOLDER_MARKERS = ("<SECURITY_CONTACT>", "<COPYRIGHT HOLDER>")
EXPECTED_LICENSE = "Apache-2.0"


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: str
    message: str
    path: str | None = None


def check_repository(
    repository_root: Path,
    *,
    strict: bool = False,
    allow_license_placeholder: bool = False,
) -> dict[str, object]:
    root = repository_root.resolve()
    findings: list[Finding] = []

    if not root.is_dir():
        findings.append(
            Finding("repository_missing", "error", "Repository root does not exist.", str(root))
        )
        return _result(root, findings, strict)

    _check_required_documents(root, findings)
    _check_license(root, findings, allow_license_placeholder)
    _check_version_consistency(root, findings)

    files = tuple(_repository_files(root))
    tracked = _tracked_paths(root)
    _check_tracked_artifacts(tracked, findings)
    _scan_text_files(root, files, findings)
    _check_markdown_links(root, files, findings)
    _check_owner_placeholders(root, findings)
    if strict:
        _check_clean_worktree(root, findings)

    return _result(root, findings, strict)


def _check_required_documents(root: Path, findings: list[Finding]) -> None:
    for relative in REQUIRED_DOCUMENTS:
        if not (root / relative).is_file():
            findings.append(
                Finding("required_document_missing", "error", "Required document is missing.", relative)
            )


def _check_license(
    root: Path,
    findings: list[Finding],
    allow_placeholder: bool,
) -> None:
    license_path = next(
        (root / name for name in ("LICENSE", "LICENSE.txt", "LICENSE.md") if (root / name).is_file()),
        None,
    )
    severity = "warning" if allow_placeholder else "error"
    if license_path is None:
        findings.append(
            Finding(
                "license_missing",
                severity,
                "Owner-approved root LICENSE is required before public release.",
            )
        )
        return
    text = license_path.read_text(encoding="utf-8", errors="replace")
    if any(marker in text for marker in PLACEHOLDER_MARKERS) or "LICENSE NOT SELECTED" in text.upper():
        findings.append(
            Finding(
                "license_placeholder",
                severity,
                "Root LICENSE still contains an owner placeholder.",
                license_path.name,
            )
        )
        return

    if "Apache License" not in text or "Version 2.0" not in text:
        findings.append(
            Finding(
                "license_unexpected",
                "error",
                "Root LICENSE must contain the selected Apache License 2.0 text.",
                license_path.name,
            )
        )

    packaged_license = root / "python-core" / "LICENSE"
    if not packaged_license.is_file() or packaged_license.read_text(encoding="utf-8") != text:
        findings.append(
            Finding(
                "packaged_license_mismatch",
                "error",
                "Python package LICENSE must match the root LICENSE.",
                "python-core/LICENSE",
            )
        )

    notice = root / "NOTICE"
    packaged_notice = root / "python-core" / "NOTICE"
    if not notice.is_file() or "Beacon contributors" not in notice.read_text(encoding="utf-8"):
        findings.append(
            Finding("notice_invalid", "error", "NOTICE must identify Beacon contributors.", "NOTICE")
        )
    elif not packaged_notice.is_file() or packaged_notice.read_text(encoding="utf-8") != notice.read_text(
        encoding="utf-8"
    ):
        findings.append(
            Finding(
                "packaged_notice_mismatch",
                "error",
                "Python package NOTICE must match the root NOTICE.",
                "python-core/NOTICE",
            )
        )

    try:
        pyproject = tomllib.loads((root / "python-core" / "pyproject.toml").read_text(encoding="utf-8"))
        gateway = json.loads((root / "gateway" / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        findings.append(Finding("license_metadata_unavailable", "error", str(exc)))
        return
    if pyproject.get("project", {}).get("license") != EXPECTED_LICENSE:
        findings.append(
            Finding(
                "python_license_mismatch",
                "error",
                f"Python package license must be {EXPECTED_LICENSE}.",
                "python-core/pyproject.toml",
            )
        )
    if gateway.get("license") != EXPECTED_LICENSE:
        findings.append(
            Finding(
                "gateway_license_mismatch",
                "error",
                f"Gateway package license must be {EXPECTED_LICENSE}.",
                "gateway/package.json",
            )
        )


def _check_version_consistency(root: Path, findings: list[Finding]) -> None:
    try:
        result = check_versions(root)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:  # type: ignore[name-defined]
        findings.append(Finding("version_check_failed", "error", str(exc)))
        return
    for message in result["errors"]:
        findings.append(Finding("version_mismatch", "error", str(message)))


def _repository_files(root: Path) -> Iterable[Path]:
    for current_root, directory_names, file_names in os.walk(root):
        current = Path(current_root)
        relative = current.relative_to(root)
        if relative.parts and relative.parts[0] in GENERATED_TOP_LEVEL_DIRECTORIES:
            directory_names[:] = []
            continue
        directory_names[:] = [
            name
            for name in directory_names
            if name not in SKIP_DIRECTORIES
            and not name.endswith(".egg-info")
            and not (relative == Path(".") and name in GENERATED_TOP_LEVEL_DIRECTORIES)
        ]
        for file_name in file_names:
            yield current / file_name


def _tracked_paths(root: Path) -> tuple[Path, ...]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return ()
    if result.returncode != 0:
        return ()
    return tuple(Path(value.decode("utf-8", errors="replace")) for value in result.stdout.split(b"\0") if value)


def _check_tracked_artifacts(paths: Sequence[Path], findings: list[Finding]) -> None:
    for path in paths:
        normalized = path.as_posix()
        top_level = path.parts[0] if path.parts else ""
        name = path.name.lower()
        blocked = (
            top_level in GENERATED_TOP_LEVEL_DIRECTORIES
            or name.endswith((".sqlite", ".sqlite3", ".log"))
            or ".sqlite3-" in name
            or name in {".env", "provider-session-registry.json"}
            or name.startswith(".env.")
            or name.endswith(".local-runtime.json")
            or "wake-ticket" in name
            or "wake_ticket" in name
        )
        if blocked:
            findings.append(
                Finding("tracked_runtime_artifact", "error", "Generated runtime artifact is tracked.", normalized)
            )


def _scan_text_files(root: Path, files: Sequence[Path], findings: list[Finding]) -> None:
    internal_terms = ("\u8d44\u6e90\u6c60", "\u81ea\u52a8\u5316\u65e5\u5fd7")
    forbidden_patterns = (
        ("fixed_f_drive_path", re.compile(r"\bF:[\\/]", re.IGNORECASE)),
        ("local_windows_path", re.compile(r"[A-Za-z]:[\\/]+Documents[\\/]+Agent Chat", re.IGNORECASE)),
        ("local_user_path", re.compile(r"C:[\\/]+Users[\\/]+(?!FixtureUser(?:[\\/]|$))", re.IGNORECASE)),
        ("local_home_path", re.compile(r"/home/[A-Za-z0-9._-]+/")),
        ("migration_state_reference", re.compile(r"migration_state\.json", re.IGNORECASE)),
        ("internal_resource_reference", re.compile("|".join(internal_terms))),
    )
    credential_patterns = (
        re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    )
    for path in files:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for code, pattern in forbidden_patterns:
            if pattern.search(text):
                findings.append(Finding(code, "error", "Internal or machine-specific text found.", relative))
        for pattern in credential_patterns:
            for match in pattern.finditer(text):
                value = match.group(0).lower()
                if any(marker in value for marker in ("example", "fixture", "not-a-real")):
                    continue
                findings.append(
                    Finding("credential_candidate", "error", "Possible credential or private key found.", relative)
                )
                break


def _check_markdown_links(root: Path, files: Sequence[Path], findings: list[Finding]) -> None:
    link_pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for raw_target in link_pattern.findall(text):
            target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
            target = target.split("#", 1)[0]
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(root):
                findings.append(
                    Finding(
                        "external_local_document_link",
                        "error",
                        f"Local Markdown link escapes the repository: {raw_target}",
                        path.relative_to(root).as_posix(),
                    )
                )
                continue
            if not resolved.exists():
                findings.append(
                    Finding(
                        "broken_document_link",
                        "error",
                        f"Markdown link target does not exist: {raw_target}",
                        path.relative_to(root).as_posix(),
                    )
                )


def _check_owner_placeholders(root: Path, findings: list[Finding]) -> None:
    for relative in ("SECURITY.md", "CODE_OF_CONDUCT.md"):
        path = root / relative
        if path.is_file() and "<SECURITY_CONTACT>" in path.read_text(encoding="utf-8"):
            findings.append(
                Finding(
                    "security_contact_placeholder",
                    "warning",
                    "Project owner must replace the private security contact placeholder.",
                    relative,
                )
            )


def _check_clean_worktree(root: Path, findings: list[Finding]) -> None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all", "--", "."],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        findings.append(Finding("git_status_unavailable", "warning", str(exc)))
        return
    if result.returncode != 0:
        findings.append(Finding("git_status_unavailable", "warning", "Unable to inspect Git worktree."))
    elif result.stdout.strip():
        findings.append(Finding("worktree_dirty", "warning", "Repository worktree is not clean."))


def _result(root: Path, findings: Sequence[Finding], strict: bool) -> dict[str, object]:
    errors = sum(item.severity == "error" for item in findings)
    warnings = sum(item.severity == "warning" for item in findings)
    return {
        "ok": errors == 0 and (not strict or warnings == 0),
        "repositoryRoot": str(root),
        "strict": strict,
        "errorCount": errors,
        "warningCount": warnings,
        "findings": [asdict(item) for item in findings],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Beacon release hygiene.")
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-license-placeholder", action="store_true")
    args = parser.parse_args(argv)
    result = check_repository(
        args.repository_root,
        strict=args.strict,
        allow_license_placeholder=args.allow_license_placeholder,
    )
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for finding in result["findings"]:
            location = f" [{finding['path']}]" if finding["path"] else ""
            print(f"{finding['severity'].upper()} {finding['code']}{location}: {finding['message']}")
        print(
            "Release hygiene: "
            + ("PASS" if result["ok"] else "FAIL")
            + f" ({result['errorCount']} errors, {result['warningCount']} warnings)"
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
