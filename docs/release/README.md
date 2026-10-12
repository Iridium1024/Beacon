# Release Readiness

Beacon is an alpha-quality local project. A release candidate must pass the
repository checks without credentials, provider accounts, or live provider
sessions.

The first alpha release remains archived in [v0.1.0.md](v0.1.0.md). Historical
notes not included in this source increment are not release prerequisites.

Current source release: [v0.2.0](v0.2.0.md). Follow
[source installation and optional runtimes](source-installation.md).
The source archive is not a standalone installer.

```powershell
py -3.11 scripts\check_versions.py
py -3.11 scripts\release_check.py --strict
py -3.11 -m unittest discover -s python-core\tests
npm.cmd --prefix gateway ci
npm.cmd --prefix gateway test
```

Run `scripts/release_check.py --strict` from a clean checkout before publishing
a release.

Before a public release, the project owner must:

1. Confirm the root Apache-2.0 `LICENSE` and `NOTICE` are present.
2. Confirm the private reporting channel in `SECURITY.md` is current.
3. Confirm the public semantic version and matching `vX.Y.Z` tag.
4. Confirm Windows, Ubuntu, Node 22, Node 24, wheel build, and release-hygiene
   checks are green in the target repository.
5. Review repository visibility, branch protection, vulnerability reporting,
   secret scanning, and release notes.
