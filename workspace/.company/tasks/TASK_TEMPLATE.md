# <TASK-ID>: <Title>

- **State:** PROPOSED
- **Owner profile:** <exact CAO profile, e.g. `claude_engineer`>
- **Reviewer profile:** <different provider from the owner for source changes, e.g. `agy_reviewer`>
- **Depends on:** <TASK-NNNN, TASK-NNNN, or `none`; the task is blocked until each is ACCEPTED>
- **Created:** <YYYY-MM-DD>
- **Approved by human:** <date and how, filled in only after approval>

## Objective

<One concrete, observable outcome.>

## Inputs

- <file, artifact, decision, or source>

## Allowed paths

- <file or directory the worker may modify; prefer files>

## Forbidden paths and actions

- <path or action>

## Deliverables

- `<exact artifact path>`
- <source change, when authorized>

## Acceptance checks (human must confirm)

- [ ] <observable criterion>
- [ ] <observable criterion>

## Authorised validation commands

The engineer and the reviewer may run exactly these commands, and nothing else: no deletes, no cleanup, no installs, no state-changing git commands. The engineer must run them before reporting `COMPLETED`; the reviewer re-runs them independently. Both paste the real output in a **Commands run** section. Prefer commands that leave no generated files behind (for Python: `python3 -B -m unittest ...`).

```bash
<command>
git status --short
```

## Team plan

Filled in by the captain, with an estimate for every agent including the captain. On the plan path the human approves this section before anything launches. Cost is a rough range of fresh tokens (input + output + cache writes, no cache reads) with a low/med/high label and a few words of basis. Mark the path taken: **Path:** FAST | PLAN

| Sub-task | Depends on | Agent (profile/role) | Why this agent | Parallel with | Est. cost |
|---|---|---|---|---|---|
| <sub-task> | <ids or NONE> | <agent> | <reason> | <ids or NONE> | <tokens or low/med/high> |

- **Total agents:** <n> (fast path: at most 2)
- **Plan-path triggers hit:** <auth/secrets | data | dependency | external | ambiguity | >2 agents | NONE>
- **Clarification rounds so far:** 0

## Approval boundary

The human must approve before:

- <action>

## Dependencies

- <task or decision, or NONE>

## Open questions

- <anything the captain could not determine from the repository, or NONE>

## Callback format

Use the standard callback in `.company/contracts/COMMUNICATION_CONTRACT.md`.
