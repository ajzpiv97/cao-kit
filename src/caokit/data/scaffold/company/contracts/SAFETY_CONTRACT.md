# Safety Contract

## Default operating mode

This prototype is local, reversible, and human-supervised.

## Prohibited without explicit task-level and human authorization

- production access,
- secrets or credential access,
- deployment or publishing,
- `git push`, merge, rebase, reset, clean, or history rewriting,
- deletion outside generated task artifacts,
- package installation or dependency upgrades,
- lockfile changes,
- database migrations or mutations,
- external messaging or form submission,
- financial or billing actions,
- changes to CI/CD, infrastructure, auth, permissions, or security policy.

## Provider-specific cautions

- Claude tool restrictions are enforced through provider-native deny controls, but path-level restrictions still depend on instructions.
- Claude workers run with `permissionMode: auto` and native tool deny-lists. Never launch with CAO `--yolo` or unrestricted tools (`allowedTools: ["*"]`).
- A tool with soft enforcement (see `ROSTER.md`; for example Antigravity, which CAO launches with automatic permission bypass) has only advisory tool restrictions. Use it only in a low-risk workspace, give it no secrets, and keep it to read-only roles unless the human explicitly accepted the risk.

## Stop conditions

Stop and ask the human when:

- a command may be destructive,
- the repository has unexpected uncommitted changes,
- a required action crosses the approval boundary,
- provider behavior differs from the task contract,
- data sensitivity is unclear,
- an agent requests credentials or broader access.
