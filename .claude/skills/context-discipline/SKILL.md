---
name: context-discipline
description: Manage context budget across a long task. Use when the conversation has loaded many files, when results from tool calls are dominating the conversation, when Claude seems to have forgotten earlier content, or when compaction is imminent. Tells Claude which persistence mechanism fits which type of information — memory, plan files, tasks, or skills — and when to quarantine work in a subagent.
---

# Context Discipline

Context is finite. Every read, grep, and tool call consumes it. Performance degrades as it fills, and compaction summarizes (and sometimes loses) earlier detail. Spend context deliberately.

## The four persistence surfaces

| Mechanism | Lives | Use for |
|---|---|---|
| **Memory** (`~/.claude/projects/.../memory/`) | Across sessions | User profile, feedback/rules, project facts, external-system references. Facts the next session needs. |
| **Plan files** (`~/.claude/plans/*.md`) | Across sessions, session-bound | Design decisions that shape the current implementation and any follow-ups. |
| **Tasks** (TaskCreate/Update) | Current session | Step-by-step progress tracking. Transient. |
| **Skills** (`.claude/skills/*/SKILL.md`) | Committed, reusable | Standing instructions for repeated work. Load-on-invoke. |

Rules:

- **Never put ephemeral state in memory.** If it's useful only this session, it belongs in tasks or conversation.
- **Never put reusable instructions in memory.** They belong in a skill.
- **Never inline reference docs** in the conversation when they belong in a skill + supporting files.

## When to quarantine in a subagent

Push work into a subagent when:

- A tool call is going to dump >50 lines and you only need the conclusion.
- You're about to grep thousands of files and only care about ~10 results.
- You need to read 5+ large files for a question with a short answer.
- You're running a destructive experiment that should not pollute the main flow.

Pattern: "Research X; return a ≤200 word report." The bulk of the tool output never enters the main conversation.

## After compaction

Claude Code auto-compacts when context fills. Skills' first 5,000 tokens each are re-attached (25k shared budget). Practical consequences:

- **Older invoked skills may be dropped** if many skills were invoked. Re-invoke with `/<name>` if a skill's rules stopped applying.
- **Raw tool results are summarized** — specific file contents, error messages, grep hits become lossy. Re-read the file if you need precision.
- **Tasks survive** but marks (completed/in_progress) may drift. Re-sync via TaskList.

## Budget signals

Watch for these in your own behavior:

- You're reading the same file 3 times — lost it to compaction. Record the relevant lines in your next text turn so they survive.
- You can't remember a decision from earlier in the conversation — it was likely compacted. Check the plan file.
- Tool output is increasingly verbose summaries of summaries — compaction is chaining. Narrow scope or quarantine.

## Defensive writes

For anything load-bearing in a long task:

- Write the decision to the plan file immediately after making it — don't rely on conversation memory.
- Update memory with non-obvious findings (surprising facts, validated-by-user approaches).
- Keep tasks granular enough that the task list itself is a progress log.

## Anti-patterns

- Re-invoking a skill "to be safe" after every message — wastes tokens.
- Dumping entire files into the conversation when you only need a function.
- Using memory as a notepad for transient thoughts.
- Letting a tool result flood the conversation instead of redirecting through a subagent.
- Repeating instructions across multiple messages — put them in a skill once.

## Gotchas

- "Claude forgot X" almost always means the context was compacted — not a model failure. Re-introduce the fact.
- `Read` on a 2,000-line file consumes ~2,000 lines of context. Use `offset`/`limit` if you know the region.
- `Grep` with `output_mode: "content"` and no `head_limit` can dump thousands of matches. Default to `files_with_matches` first.
- Saving "save this list of PRs" into memory — that's snapshot data, stale instantly. Keep it in conversation or a plan file.
- Long stretches without TaskUpdate → hard to tell at a glance what's done. Keep the task list current.
