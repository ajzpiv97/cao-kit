# State Contract

Allowed task states:

```text
PROPOSED
APPROVED
ASSIGNED
IN_PROGRESS
BLOCKED
REVIEW_READY
CHANGES_REQUESTED
ACCEPTED
CANCELLED
FAILED
```

## Transitions

- `PROPOSED -> APPROVED` requires the human or an already authorized backlog rule.
- `PROPOSED -> APPROVED` also happens under the fast-path rule in the captain's Routing section (task needs at most two agents and meets none of the plan-path conditions); record it in `.company/DECISIONS.md` as approved under the fast-path rule.
- `APPROVED -> ASSIGNED` requires an owner profile and artifact path.
- `ASSIGNED -> IN_PROGRESS` begins when the worker starts.
- `IN_PROGRESS -> BLOCKED` requires a recorded blocker and requested decision.
- `IN_PROGRESS -> REVIEW_READY` requires deliverables and validation evidence.
- `REVIEW_READY -> CHANGES_REQUESTED` requires review findings.
- `REVIEW_READY -> ACCEPTED` requires all mandatory acceptance checks to pass and any required human approval.
- Any active state may become `CANCELLED` by the human.
- `FAILED` requires a failure record and preserved partial artifacts.

A task must never be marked `ACCEPTED` only because a worker said it completed.
