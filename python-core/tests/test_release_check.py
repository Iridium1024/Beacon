from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


BEACON_ROOT = Path(__file__).resolve().parents[2]
if str(BEACON_ROOT) not in sys.path:
    sys.path.insert(0, str(BEACON_ROOT))

from scripts import release_check as MODULE


class ReleaseCheckTests(unittest.TestCase):
    def test_repository_passes_release_hygiene_checks(self) -> None:
        result = MODULE.check_repository(BEACON_ROOT)

        self.assertTrue(result["ok"], result["findings"])
        self.assertEqual(result["errorCount"], 0)

    def test_security_contact_placeholder_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SECURITY.md").write_text("<SECURITY_CONTACT>", encoding="utf-8")
            (root / "CODE_OF_CONDUCT.md").write_text("<SECURITY_CONTACT>", encoding="utf-8")
            findings: list[object] = []

            MODULE._check_owner_placeholders(root, findings)

            self.assertEqual(
                [item.code for item in findings],
                ["security_contact_placeholder", "security_contact_placeholder"],
            )

    def test_packaged_license_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "LICENSE").write_text(
                "Apache License\nVersion 2.0\n",
                encoding="utf-8",
            )
            (root / "NOTICE").write_text("Beacon contributors\n", encoding="utf-8")
            (root / "python-core").mkdir()
            (root / "python-core" / "LICENSE").write_text("different\n", encoding="utf-8")
            (root / "python-core" / "NOTICE").write_text(
                "Beacon contributors\n",
                encoding="utf-8",
            )
            (root / "python-core" / "pyproject.toml").write_text(
                '[project]\nlicense = "Apache-2.0"\n',
                encoding="utf-8",
            )
            (root / "gateway").mkdir()
            (root / "gateway" / "package.json").write_text(
                '{"license": "Apache-2.0"}',
                encoding="utf-8",
            )
            findings: list[object] = []

            MODULE._check_license(root, findings, allow_placeholder=False)

            self.assertIn("packaged_license_mismatch", {item.code for item in findings})

    def test_machine_specific_path_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "leak.md").write_text(
                "machine path: " + "C:/" + "Users/RealUser/project",
                encoding="utf-8",
            )
            findings: list[object] = []

            MODULE._scan_text_files(root, (root / "leak.md",), findings)

            self.assertIn("local_user_path", {item.code for item in findings})

    def test_generated_package_directories_are_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src" / "module.py"
            source.parent.mkdir()
            source.write_text("source", encoding="utf-8")
            build_file = root / "build" / "copied.py"
            build_file.parent.mkdir()
            build_file.write_text("copy", encoding="utf-8")
            metadata_file = root / "src" / "package.egg-info" / "PKG-INFO"
            metadata_file.parent.mkdir()
            metadata_file.write_text("metadata", encoding="utf-8")

            files = {path.relative_to(root).as_posix() for path in MODULE._repository_files(root)}

            self.assertEqual(files, {"src/module.py"})

    def test_local_markdown_link_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repository"
            root.mkdir()
            outside = base / "private.md"
            outside.write_text("private", encoding="utf-8")
            readme = root / "README.md"
            readme.write_text("[private](../private.md)", encoding="utf-8")
            findings: list[object] = []

            MODULE._check_markdown_links(root, (readme,), findings)

            self.assertIn(
                "external_local_document_link",
                {item.code for item in findings},
            )


if __name__ == "__main__":
    unittest.main()
