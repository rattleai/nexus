# Security Policy

## Supported versions

NEXUS is pre-1.0. Only the latest minor release line on `main` receives security fixes.

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |
| < 0.1   | No        |

## Reporting a vulnerability

**Do not open a public issue.** Use one of the following private channels:

1. Preferred: open a private advisory via GitHub Security Advisories
   (https://github.com/rattleai/nexus/security/advisories/new).
2. Alternative: email `opensource@rattleai.de` with a description, reproduction steps,
   and any patches you propose.

We aim to:
- acknowledge your report within 3 business days,
- provide an initial assessment within 7 business days,
- coordinate disclosure once a fix is available.

We do not currently run a paid bounty. We do credit reporters in release notes
unless you ask us not to.

## Scope

In scope:
- The platform code in this repository (`app/`, `frontend/`, `infra/`).
- The plugin contract in `app/plugins/base.py`.
- The reference Docker image published to GHCR.

Out of scope:
- Third-party plugins built on the platform — report to their maintainers.
- Vulnerabilities that require physical access or already-compromised credentials.
- Findings produced solely by automated scanners with no proven impact.
