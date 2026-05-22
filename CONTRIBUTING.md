# Contributing to NEXUS

Thanks for your interest in contributing! NEXUS is an AI-first multi-agent platform that
applications are built on top of as **plugins** — most contributions either improve the
core platform or add example plugins that show off the contract.

## Quick start

```bash
git clone https://github.com/rattleai/nexus.git
cd nexus
cp .env.example .env

# Bring up Postgres, Redis, API, frontend
make dev-up
make seed-docker          # runs migrations + creates a dev user

# Frontend on http://localhost:3000, API docs on http://localhost:8002/api/docs
```

For local development without Docker, see the README's "Local Development" section.

## Branching model

- `main` is always green and deployable. It is protected: PRs require review, signed commits,
  passing CI, linear history, and conversation resolution.
- Work on a feature branch. Suggested naming: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`,
  `refactor/<topic>`.
- Open a PR against `main`. Squash-merge is the default; rebase-merge is allowed for
  multi-commit PRs that you want to preserve.

## Commit & PR hygiene

- **Sign off** every commit (`git commit -s`). We use the
  [Developer Certificate of Origin](https://developercertificate.org/).
- Sign your commits cryptographically (`git commit -S`) — required by branch protection.
- Keep commits atomic: one logical change per commit; tests included where they belong.
- Write a clear PR description: **what** changed, **why**, and a **test plan** the reviewer
  can execute. Link related issues. The PR template prompts for these.
- For UI changes, attach a screenshot or short clip; for API changes, paste a sample
  request/response.

## Local checks before pushing

```bash
make lint        # ruff
make typecheck   # mypy
make test        # pytest with 80% coverage gate
make fe-lint     # ESLint + tsc --noEmit
make fe-test     # vitest
make fe-build    # also regenerates routeTree.gen.ts
```

CI runs the same checks plus SAST (Bandit), dependency audit (pip-audit), secret scan
(Gitleaks), container scan (Trivy), and CodeQL.

### Pre-commit hooks (recommended)

Install once per clone:

```bash
pip install pre-commit
pre-commit install
```

The hook set in [`.pre-commit-config.yaml`](.pre-commit-config.yaml) runs ruff (lint + format),
prettier on the frontend, gitleaks on the diff, basic file-hygiene checks (trailing whitespace,
end-of-file, large files, private keys, merge-conflict markers), and a guard that prevents
historical brand references from re-entering the codebase. Run on demand with
`pre-commit run --all-files`.

## Building a plugin

Most application code goes in `app/apps/<your_plugin>/` (backend) and
`frontend/src/apps/<your_plugin>/` (frontend). The plugin contract is defined in
[`app/plugins/base.py`](app/plugins/base.py); a working reference lives in
[`app/apps/example/`](app/apps/example/).

Read [`docs/PLUGINS.md`](docs/PLUGINS.md) for the step-by-step walkthrough.

Two hard rules:

1. **Plugins may import from `app.core.*`, `app.db.*`, `app.ai.*`** but never from another
   `app.apps.*`. Cross-app dependencies belong in `app.core.*` or in shared services.
2. **Plugins own their own DDL.** Each plugin ships its migrations under
   `app/apps/<name>/migrations/versions/` and chains via `down_revision`.

## Reporting bugs / requesting features

Use the GitHub issue templates. For security vulnerabilities, follow [SECURITY.md](SECURITY.md)
— do **not** open a public issue.

## Code of conduct

Be excellent to each other. We follow the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md).
Report concerns to `opensource@rattleai.de`.

## Licensing of contributions

By submitting a Contribution to this project, you agree that your Contribution is licensed
under the terms of the [Apache License 2.0](LICENSE), the same license that covers the
project, and that you have the right to grant that license.
