## Summary

<!-- One paragraph: what this PR changes and why. Link related issues. -->

## Changes

<!-- Bullet list of the user-visible or developer-visible changes. -->

-

## Test plan

<!-- Steps a reviewer can run to verify. Include commands, URLs, expected output. -->

- [ ]
- [ ]

## Breaking changes

<!-- "None" or describe migration steps for downstream users. -->

None.

## Security & privacy

<!-- New external calls? Secrets? Auth changes? PII? RLS implications? "None" if N/A. -->

None.

## Checklist

- [ ] Commits are signed off (`git commit -s`) and signed (`git commit -S`).
- [ ] `make lint && make typecheck && make test` pass locally.
- [ ] Frontend: `make fe-lint && make fe-test && make fe-build` pass locally (if touched).
- [ ] Migrations run cleanly on a fresh DB (if schema changed).
- [ ] Docs updated (`README.md`, `docs/PLUGINS.md`, or area-specific docs).
- [ ] No secrets, internal URLs, or proprietary identifiers introduced.
