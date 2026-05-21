---
name: agent-design
description: Choose the right subagent for a task, or design a new custom subagent. Use when deciding whether to spawn an Explore / Plan / general-purpose agent, when a repeated pattern deserves a custom subagent in .claude/agents/, or when writing an agent prompt. Enforces prompt self-containment and right-sized delegation.
---

# Agent Design

Subagents are for **context quarantine** (keep noise out of the main conversation), **parallelism** (independent work in one message), and **specialization** (a prompt tuned for one task-class).

## When to spawn a subagent

**Spawn:**
- Broad codebase searches that would flood your context with tool output.
- Research across many files where only a summary matters to you.
- Independent tasks that can run in parallel (multiple builds, multiple explorations).
- Work you want shielded from the main conversation (destructive experiments in a worktree).

**Don't spawn:**
- Targets are known — use `Read` directly.
- Specific symbol/string search — use `Grep`.
- Single file pattern — use `Glob`.
- Quick one-shot shell — use `Bash`.
- One-line edit — use `Edit`.

If you can accomplish the task in ≤3 direct tool calls, skip the subagent.

## Picking the built-in agent type

| Agent | When to use |
|---|---|
| `Explore` | Broad codebase questions ("how does auth work?"), find usages, map structure. Read-only. Specify thoroughness: `quick`, `medium`, `very thorough`. |
| `Plan` | Architecture decisions, multi-file refactor strategy, trade-off analysis. Read-only, writes a plan. |
| `general-purpose` | Unclear scope, needs both research and small edits, unknown cost. Default fallback. |
| `claude-code-guide` | Questions about Claude Code, the Claude API, skills, hooks, MCP — don't spelunk docs yourself. |
| `feature-dev:code-architect` | Designing a new feature architecture in an existing codebase. |
| `feature-dev:code-explorer` | Deep-dive on an existing feature's execution paths before changing it. |
| `feature-dev:code-reviewer` | Independent code review with confidence-filtered issues. |

## Custom subagents (`.claude/agents/<name>.md`)

Create one when you'd otherwise copy-paste the same prompt skeleton weekly. Red flags that suggest making a custom agent:

- Same role preamble across many spawns.
- A recurring task that has its own style guide (e.g., "API design review for our REST conventions").
- A task that benefits from a dedicated tool allowlist.

## Writing a subagent prompt

A subagent starts with no memory of your conversation. **Brief it like a smart colleague who just walked in.**

Required elements:

- **Goal** — what you're trying to accomplish and why.
- **Context already gathered** — what you've ruled out or confirmed.
- **Constraints** — files to touch, files to avoid, style rules.
- **Deliverable shape** — "punch list", "under 200 words", "JSON with fields X, Y", "code + tests".
- **For lookups**: the exact command to run. For investigations: the question to answer.

Anti-patterns:

- "Based on your findings, fix the bug." → pushes synthesis onto the agent. Be specific: what file, what change, why.
- Terse command-style prompts ("search for X") → shallow results.
- Prescribed step lists for open-ended investigations → dead weight when the premise is wrong. Give the question instead.
- Implicit assumption that the agent can see your thinking or tool results → it cannot. Restate.

## Parallelism

When work is independent, spawn agents in **one message with multiple tool calls**. Sequential spawning is wasteful.

Example: "Map the backend and the frontend in parallel" → two `Explore` calls in a single message.

Don't parallelize dependent work — if B's prompt needs A's output, run A first.

## Context quarantine

Large tool output (file dumps, grep with 1,000 hits, compose logs) balloons your context. Push it into a subagent that summarizes, returns ≤400 words, and discards the rest.

Pattern: "Research X; return a ≤200 word report with file:line references."

## Gotchas

- Spawning an `Explore` agent for a task that requires editing — Explore can't edit. Use `general-purpose` or do it yourself.
- Treating the agent result as a user message — tool results are not shown to the user. Relay the findings yourself in your reply.
- Trusting an agent's summary of what it changed — read the diff. The summary describes intent; the files describe reality.
- Running a `Plan` agent for a trivial change — the plan overhead outweighs the value.
- Spawning many small agents for work that shares context — one larger agent with a structured deliverable is cheaper.
