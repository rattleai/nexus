---
name: hook-author
description: Write or audit a Claude Code hook in settings.json. Use when the user asks to automate a behavior ("when X happens, do Y"), add a lifecycle trigger, block a tool, or validate a file after edit. Enforces matcher correctness, exit-code conventions, non-blocking defaults, and debugging for silent failures.
---

# Hook Author

Hooks run on Claude Code lifecycle events. Memory and skills can't guarantee behavior — hooks can, because the harness executes them, not the model.

## When a hook beats a skill

Use a **hook** when:
- The behavior must fire every time regardless of what Claude decides.
- The action is a short, deterministic shell command (format, lint, log, notify).
- A file state must be validated after an edit.
- You want to block an action under a condition.

Use a **skill** when:
- The behavior needs judgment ("is this change risky?").
- The action depends on conversation context.
- You want Claude to decide when to invoke.

## Hook events (common ones)

| Event | Fires | Typical use |
|---|---|---|
| `PostToolUse` | After a tool call succeeds | Auto-format a file that was just edited, rerun type checks, update an index. |
| `PreToolUse` | Before a tool runs (can block) | Block `git push --force main`, require a test to pass before writing prod config. |
| `Stop` | When Claude ends its turn | Remind the user to run tests, post a summary. |
| `SessionStart` | New session begins | Print status (docker health, PR queue), welcome info. |
| `SubagentStop` | Subagent finishes | Collect summaries, gate the main flow. |
| `UserPromptSubmit` | User sends a prompt | Inject reminders, block dangerous phrases. |

## settings.json structure

```json
{
  "hooks": {
    "<EventName>": [
      {
        "matcher": "<regex or tool name>",
        "hooks": [
          {
            "type": "command",
            "command": "your-shell-one-liner"
          }
        ]
      }
    ]
  }
}
```

- `matcher` is event-specific. For `PostToolUse`, it matches tool names (`Edit`, `Write`, `Bash`). Use a regex string like `"Edit|Write"` for multiple.
- Inside the command, Claude Code passes context via stdin (JSON with `tool_name`, `tool_input`, etc.) and environment variables. Parse stdin for robust hooks.

## Exit-code conventions

- `0` — success, continue. Stdout is shown to Claude for `PreToolUse`/`UserPromptSubmit`; for others it's mostly informational.
- `2` — block the tool (for `PreToolUse`). Stderr becomes the blocking reason shown to Claude.
- Non-zero other than 2 — treated as a failure; reported but usually non-blocking.

Rule: keep hooks **non-blocking by default**. Format-on-edit that exits 1 will interrupt flow. Silent-pass with a warning is almost always right for automation; block only when truly unsafe.

## File scoping

`PostToolUse` matcher doesn't filter by file path — it filters by tool. Filter paths inside the command:

```bash
# Only run ruff on backend Python files
file=$(jq -r '.tool_input.file_path // empty')
case "$file" in
  *backend/*.py) uv run ruff format "$file" ;;
esac
```

Read the file path from stdin JSON (via `jq`) — it's the reliable source.

## Debugging a silent hook

1. Is the hook registered? `cat .claude/settings.json` and confirm.
2. Is the matcher correct? Test the regex against the tool name.
3. Run the command manually with sample stdin: `echo '{"tool_input":{"file_path":"x.py"}}' | your-command`.
4. Check Claude Code logs — hook errors are surfaced but often easy to miss.
5. Add `>> /tmp/hook.log 2>&1` to the command temporarily.

## Hard rules

- **Non-destructive by default.** A hook that `rm`s, pushes, or force-pushes is a footgun.
- **Idempotent.** A hook that runs twice must produce the same state.
- **Fast.** Anything over ~2s blocks perceived responsiveness. Move long work to a background process.
- **No secrets in hook commands.** `.claude/settings.json` is committed; secrets belong in env vars or a secret manager.
- **Scope with the matcher AND with inline filtering.** `matcher: "Edit"` alone fires on every edit — overkill for a language-specific formatter.

## Gotchas

- `matcher: "*"` matches nothing, not everything. Use `".*"` for "all tools."
- Hook runs but output doesn't reach Claude — for `PostToolUse`, stdout is captured but not injected into context. Use `PreToolUse` or a dedicated channel if Claude must see the result.
- `bun` / `uv` / `docker` not on PATH when the hook runs in a restricted shell — use absolute paths or source `~/.zshrc` explicitly.
- Exit code 2 from `PostToolUse` doesn't "undo" the tool call — the edit already happened. Use `PreToolUse` to prevent.
- JSON parsing without `jq -e` silently succeeds on missing fields; check for empty strings before acting.
- Personal hooks in `~/.claude/settings.json` overlap with project hooks — know which one you're editing.
