Execute TASK-0001 from `.company/tasks/TASK-0001-two-provider-smoke-test.md`.

Follow this exact sequence:

1. Read `.company/COMPANY.md`, every file under `.company/contracts/`, and the TASK-0001 file.
2. Confirm the only permitted writes are the paths listed in TASK-0001.
3. Use CAO `assign` to launch `claude_engineer` with the Engineering deliverable from TASK-0001. Name the exact artifact path. State that source changes and mutating commands are forbidden.
4. Record the returned engineer terminal ID in `.company/TEAM.md`.
5. Use CAO `assign` to launch `agy_researcher` with the Antigravity deliverable from TASK-0001. Name the exact artifact path. State that source changes and external side effects are forbidden.
6. Record the returned Antigravity terminal ID in `.company/TEAM.md`.
7. Do not perform either worker's assignment yourself. Become idle after dispatch so callbacks can arrive.
8. Wait until both workers have sent callbacks. Reuse and message an existing worker if clarification is needed; do not create duplicates.
9. Verify both artifact files exist and are non-empty.
10. Use CAO `handoff` to `claude_reviewer`. Instruct it to read TASK-0001 and both worker artifacts, then write `.company/reviews/TASK-0001-cross-provider-review.md`.
11. Read the review and write `.company/decisions/TASK-0001-captain-synthesis.md`.
12. Check each acceptance criterion as PASS, FAIL, or NOT VERIFIED with evidence.
13. Do not edit application source, run deployment actions, merge, push, or access secrets.
14. Finish by reporting only the task state, worker terminal IDs, artifact paths, failed/not-verified checks, and decisions required from the human.
