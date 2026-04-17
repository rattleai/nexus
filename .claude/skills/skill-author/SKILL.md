---
name: skill-author
description: Author or audit a Claude skill. Use when creating a new skill, reviewing an existing SKILL.md, or when asked how to write skills. Enforces SOTA SKILL.md conventions — front-loaded description, size limits, supporting-file split, correct frontmatter choices (paths/allowed-tools/disable-model-invocation), and a Gotchas section grounded in real failures.
---

# Skill Author

Write or audit a skill. A skill is a folder at `.claude/skills/<name>/` with `SKILL.md` as entrypoint; Claude loads SKILL.md into context on invocation and keeps it for the session.

## When writing a new skill

Decide three things before typing:

1. **Who invokes?**
   - Claude automatically → good `description`, no `disable-model-invocation`.
   - Only the user (side-effects: migrations, deploys, git pushes) → add `disable-model-invocation: true`.
   - Only Claude (background knowledge, not a menu action) → add `user-invocable: false`.

2. **Where does it run?**
   - Inline (default) → shares conversation context.
   - `context: fork` with `agent: Explore|Plan|general-purpose` → isolated subagent. **Requires** a concrete task in the skill body, not just guidelines.

3. **When should it auto-trigger?**
   - `paths: ["backend/app/api/**"]` limits auto-invocation to matching file work.
   - No `paths` → Claude decides purely from `description`.

## SKILL.md template

```yaml
---
name: <lowercase-hyphenated-name>
description: <What it does>. Use when <trigger phrases>. <Optional: what it's NOT for>.
# Optional:
# argument-hint: "<arg1> [arg2]"
# allowed-tools: Bash(cmd1 *) Bash(cmd2 *)
# paths: ["path/pattern/**"]
# disable-model-invocation: true
# user-invocable: false
# context: fork
# agent: Explore
# effort: high
---

# <Skill Name>

<One-paragraph what + why.>

## <Section>

<Instructions, written as standing rules, not one-time steps.>

## Gotchas

- <Real failure mode + how to avoid.>
- <Another real failure.>
```

## Hard rules

- **Description ≤1,536 chars** (frontmatter cap). Front-load the use-case in the first sentence. The second sentence lists trigger phrases.
- **SKILL.md ≤500 lines.** Move detail to sibling files (`EXAMPLES.md`, `GOTCHAS.md`, `TEMPLATE.md`, `reference.md`) and reference them.
- **Name = directory name** (kebab-case, ≤64 chars). `name:` frontmatter is optional if it matches directory.
- **Instructions are standing rules**, not narrative. Content enters context once and is not re-read — write imperatives that apply throughout a task.
- **`allowed-tools` is for frequently-used Bash patterns** this skill needs. Don't list every conceivable tool; listing more increases silent permission grants.
- **Gotchas section is mandatory** for any skill more complex than behavior guidelines. Each gotcha must be a real observed failure, not a theoretical one.

## Anti-patterns (reject in review)

- Description starting with "A skill that..." — wastes the first ~20 chars of the cap.
- Step-by-step procedures presented as one-shot prose — use numbered lists.
- Empty `## Gotchas` section, or gotchas that restate the rule.
- Skills over 500 lines with no supporting files.
- `context: fork` on a reference/guidelines skill (no task = no output).
- `allowed-tools: Bash(*)` — defeats the pre-approval safety net.
- Wrapping every sentence in bold. Reserve **bold** for keywords a skimmer must hit.

## Supporting files pattern

Use sibling files when SKILL.md approaches 300 lines:

```
<skill>/
├── SKILL.md          # Navigation + essentials
├── TEMPLATE.md       # Copy-paste template (scaffolds)
├── EXAMPLES.md       # Good/bad examples
├── GOTCHAS.md        # Long-form failure cases
└── scripts/
    └── run.sh        # Deterministic script (executed, not loaded)
```

Reference them from SKILL.md so Claude loads only what it needs:

```markdown
See [TEMPLATE.md](TEMPLATE.md) for the boilerplate. For edge cases, read [GOTCHAS.md](GOTCHAS.md).
```

## Dynamic context injection

Inline shell commands in backticks with `!` prefix run before the skill is sent to Claude:

```markdown
Current services: !`docker compose ps --format '{{.Name}}: {{.Status}}'`
```

The output replaces the placeholder. Use for live state (git status, compose ps, env vars). Do **not** use for commands with side effects.

## Extended thinking

Include the word `ultrathink` anywhere in the skill body to force extended thinking on invocation. Reserve for skills that handle hard problems (root-cause analysis, security review, architecture).

## Auditing an existing skill

Run through this checklist:

1. Description reads like a trigger — not a book blurb? First sentence names the action + when.
2. Line count under 500? If not, split supporting files.
3. All frontmatter fields intentional? No leftover defaults, no missing `disable-model-invocation` where it has side effects.
4. `paths` set where scope is file-specific?
5. `allowed-tools` scoped, not `Bash(*)`?
6. Gotchas section present, specific, grounded in real failures?
7. No narrative fluff — every sentence is a rule, an example, or a reference.

Report failures as `<skill>: <rule violated>: <fix>`.

## Gotchas

- Skills written as "here's what I would do if asked" read like docs. Rewrite as imperatives Claude applies.
- Changing SKILL.md mid-session — edits take effect within the session, but the already-loaded content is *not* re-read for active skills. Re-invoke with `/<name>` to refresh.
- `description` is capped at 1,536 chars *including* `when_to_use` appended. Don't blow the budget on adjectives.
- Putting raw credentials, tokens, or PII in a skill file — skills are committed artifacts, treat them as public.
- `context: fork` without an actionable task = subagent returns nothing useful.
