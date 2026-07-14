from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tomllib
from typing import Sequence


VERSION_MARKER = re.compile(r"<!--\s*beacon-version:\s*([^\s]+)\s*-->")


def check_versions(repository_root: Path) -> dict[str, object]:
    root = repository_root.resolve()
    canonical_path = root / "python-core" / "src" / "agent_os" / "VERSION"
    version = canonical_path.read_text(encoding="ascii").strip()
    errors: list[str] = []

    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.-]+)?", version):
        errors.append(f"Invalid canonical version: {version!r}")

    pyproject = tomllib.loads(
        (root / "python-core" / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = pyproject.get("project", {})
    if project.get("version") is not None:
        errors.append("python-core/pyproject.toml must use dynamic version metadata.")
    if "version" not in project.get("dynamic", []):
        errors.append("python-core/pyproject.toml must declare dynamic = ['version'].")

    gateway = json.loads((root / "gateway" / "package.json").read_text(encoding="utf-8"))
    if gateway.get("version") != version:
        errors.append(
            "gateway/package.json version does not match agent_os/VERSION: "
            f"{gateway.get('version')!r} != {version!r}."
        )
    gateway_lock = json.loads(
        (root / "gateway" / "package-lock.json").read_text(encoding="utf-8")
    )
    lock_versions = (
        gateway_lock.get("version"),
        gateway_lock.get("packages", {}).get("", {}).get("version"),
    )
    if any(candidate != version for candidate in lock_versions):
        errors.append(
            "gateway/package-lock.json versions do not match agent_os/VERSION: "
            f"{lock_versions!r} != {version!r}."
        )

    init_text = (root / "python-core" / "src" / "agent_os" / "__init__.py").read_text(
        encoding="utf-8"
    )
    if "from agent_os._version import __version__" not in init_text:
        errors.append("agent_os.__version__ must be imported from agent_os._version.")

    for relative in ("README.md", "README.en.md", "CHANGELOG.md"):
        path = root / relative
        if not path.is_file():
            errors.append(f"Missing versioned document: {relative}.")
            continue
        match = VERSION_MARKER.search(path.read_text(encoding="utf-8"))
        if match is None:
            errors.append(f"Missing beacon-version marker in {relative}.")
        elif match.group(1) != version:
            errors.append(
                f"{relative} version marker {match.group(1)!r} does not match {version!r}."
            )

    return {
        "ok": not errors,
        "version": version,
        "canonicalSource": str(canonical_path.relative_to(root)),
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Beacon version consistency.")
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    result = check_versions(args.repository_root)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Beacon version: {result['version']}")
        for error in result["errors"]:
            print(f"ERROR: {error}")
        print("Version check: PASS" if result["ok"] else "Version check: FAIL")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
