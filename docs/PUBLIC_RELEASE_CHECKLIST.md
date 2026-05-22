# Public-release checklist

This is the operator-side checklist for flipping the repository from private to public. Every item here requires GitHub UI / org-admin access — the items the codebase itself can solve already live in `.github/workflows/ci.yml`, `pyproject.toml`, and `docs/`.

Tick each box in order; if you skip ahead, CI on the first public PR will tell you about it.

## 1. Pre-flip hygiene (must be done **before** flipping to public)

- [ ] **GitHub Actions billing.** The org's Actions billing has lapsed (recent CI runs report _"recent account payments have failed or your spending limit needs to be increased"_). Fix the payment method and bump the spending limit in `Settings → Billing & plans`. CI will not run on any commit until this clears.
- [ ] **Run a clean CI on `main`.** Push a no-op commit (or merge a small PR) and confirm CI is green end-to-end. If anything is still red after the fixes in the latest `chore: public-release CI/docs polish` commit, file it as a follow-up — don't go public with red CI.
- [ ] **Rotate every secret that was ever stored in repo settings.** Even if there is no leak in source, secrets used during development should be assumed compromised on flip:
  - `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `STRIPE_SECRET_KEY` and Stripe webhook secrets
  - Database / Redis credentials (deployed env)
  - `SECRET_KEY`, `ADMIN_KEY`, `ENCRYPTION_KEY`
  - Any cloud provider keys (`AWS_*`, `R2_*`, etc.)
- [ ] **Final gitleaks pass.** `pre-commit run --all-files --hook-stage manual no-brand-leak-all-files` plus `gitleaks detect --config=.gitleaks.toml` from a fresh clone. No findings.
- [ ] **`@example.com` placeholders.** `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md` now point security and conduct reports at `opensource@rattleai.de`. Make sure that mailbox exists and has at least one human on it.

## 2. Flip the repo to public

- [ ] **Settings → General → Danger Zone → Change visibility → Public.** Type the repo name to confirm.
- [ ] **Verify Advanced Security enabled.** Once public, `Settings → Code security and analysis` should show *Code scanning (CodeQL)* and *Secret scanning* both available for free. CodeQL will move from "Advanced Security required" 403s to actual analysis runs.
- [ ] **Enable Discussions.** `Settings → General → Features → Discussions`. The README's "Community" section links to `…/discussions`.
- [ ] **Confirm branch protection on `main`.** Required: signed commits, status checks (`CI / Backend Lint`, `CI / Backend Tests`, `CI / Migration *`, `CI / Frontend *`, `CI / Dependency Audit`, `CodeQL / Analyze (python)`, `CodeQL / Analyze (javascript-typescript)`), at least one approving review, conversation resolution before merge.
- [ ] **GHCR packaging.** `Settings → Packages → Linked repositories` — link `ghcr.io/rattleai/nexus` to this repo and set visibility to public.

## 3. Right after going public

- [ ] **Watch the first 24h of forks / clones.** `Insights → Traffic`. A spike of `git clone` from an unusual region is a useful signal.
- [ ] **Pin a discussion** introducing the project and inviting plugin authors. Reference `docs/PLUGINS.md` and `docs/ARCHITECTURE.md`.
- [ ] **Issue triage rota.** Decide who owns first-response on issues for the first two weeks while interest is highest.
- [ ] **Open a `good-first-issue` bucket.** 5–10 small, well-scoped tickets so external contributors have an obvious on-ramp.
- [ ] **Cut the v0.1.0 GitHub release.** Tag `v0.1.0` on the commit that becomes the public baseline; release notes from `CHANGELOG.md`. The `release.yml` workflow handles the rest.

## 4. Optional but high-leverage

- [ ] **Set up Dependabot security alerts.** They're on by default for public repos but worth checking that they route to the right reviewers.
- [ ] **Add a `FUNDING.yml`** if you want GitHub Sponsors / Open Collective buttons (purely optional; can be added later).
- [ ] **Pin the repo to the org profile.** `rattleai` org → Customize your pins → check `nexus`.
- [ ] **Submit to relevant lists.** Awesome-AI, Awesome-FastAPI, Awesome-MCP. Keep submissions to lists whose curation you actually respect.
- [ ] **Talk about it.** Hacker News "Show HN", X/Bluesky, the Anthropic / OpenAI developer Discords, FastAPI's announcement channel. Be specific about what's interesting (plugin contract, multi-tenant RLS, MCP/A2A glue) rather than generic "we built a thing".

## 5. Known follow-ups (not blockers, but track them)

- [ ] `migration-drift` CI job is currently `continue-on-error: true`. Burn down the pre-existing baseline drift, then flip it to a hard merge gate.
- [ ] `backend-typecheck` (`mypy`) only checks `app/connectors`, `app/a2a`, `app/authz`. The remaining ~321 pre-existing baseline errors should be cleared so the full `app/` tree type-checks.
- [ ] `frontend-lint` (`eslint`) has `--max-warnings 100`. Drive this to 0 as warnings are addressed.
- [ ] Backend test coverage gate is at `--cov-fail-under=25`. Raise as real test suites land.
- [ ] Frontend JS bundle budget is 750 KB gzipped. Worth a `analyze` pass to find dead code if you want to drop it below 500 KB again.
