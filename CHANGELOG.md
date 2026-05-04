# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
