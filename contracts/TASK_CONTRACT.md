# Task Contract

Every delegated task must have a persistent Markdown task file with:

1. **Task ID** — unique and stable.
2. **Objective** — one outcome, not a vague theme.
3. **Owner profile** — exact CAO profile name.
4. **Inputs** — files, links, prior decisions, and assumptions.
5. **Allowed paths** — files or directories the worker may modify.
6. **Forbidden paths/actions** — explicit exclusions.
7. **Deliverables** — exact artifact and source outputs.
8. **Acceptance checks** — observable pass/fail criteria.
9. **Authorised validation commands** — the exact tests or checks the engineer and reviewer may run, and nothing else. The engineer runs them before reporting completion; the reviewer re-runs them independently. Every command run is reported with its real output.
10. **Approval boundary** — actions that require the human.
11. **Dependencies** — upstream tasks or decisions.
12. **Callback format** — status, artifact path, findings, blockers.

A worker must stop and contact the captain when:

- required inputs are missing,
- allowed and forbidden scopes conflict,
- a task needs a locked action,
- acceptance checks cannot be evaluated,
- an unexpected change outside scope appears necessary.

The captain must not broaden a task informally through follow-up messages. Amend the task file and record the change.
