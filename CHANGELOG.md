# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `docs/ARCHITECTURE.md` — system-level view of how the platform fits together,
  with mermaid diagrams of the request lifecycle and the plugin contract surface.

### Fixed
- Backend lint: clear the residual `I001` import-ordering findings introduced by
  the public-release cleanup so `ruff check` and `ruff format --check` are clean
  for new contributors.
- `tests/agents/test_agent_rls_context.py`: realign the
  `TestToolExecutorRLSContext` and `TestToolFailureIsolation` mocks with
  `app.agents.setup.build_tool_executor`, which now threads `actor_user_id`,
  `agent_id`, and `agent_instance_id` through to the tool registry for confused-
  deputy prevention.
- `tests/test_pr53_security.py`: drop the two CPQ-specific asserts
  (`TestChunkDeletionTenantFilter`, `TestORMIndexNaming`) whose targets were
  extracted out of the public platform; the equivalents now live in the CPQ
  plugin's own test suite.
- CI dependency audit: ignore the disputed `PYSEC-2025-183` against pyjwt (key
  length is the application's responsibility per the maintainer).
- CI secrets scan: switch from `gitleaks/gitleaks-action` (paid for org-owned
  repos since v2) to the upstream Apache-2.0 gitleaks CLI binary so forks and
  orgs can run the same scan unchanged.
- `uv.lock`: regenerate against `pyproject.toml` (the prior `saas-platform` →
  `nexus-platform` rename hadn't been propagated, breaking the
  `Dependency Lock Drift` job).
- `.gitignore`: stop claiming `uv.lock` is ignored; the file is intentionally
  tracked so CI's `uv lock --check` and dev / prod environments resolve the
  same versions.

## [0.1.0] - 2026-05-03

### Added
- Initial public release of NEXUS as a generic AI-first multi-agent platform.
- Plugin architecture (`app/plugins/`): apps register routers, models, MCP tools,
  agent tools, capability domains, Celery config, scopes, error handlers, and frontend
  manifests via `AppPluginBase`.
- Reference plugin under `app/apps/example/` demonstrating the full contract.
- Apache License 2.0, contributor and security policies, GitHub issue/PR templates,
  CodeQL workflow, Dependabot configuration.

[Unreleased]: https://github.com/rattleai/nexus/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rattleai/nexus/releases/tag/v0.1.0
