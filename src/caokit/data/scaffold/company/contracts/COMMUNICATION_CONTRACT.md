# Communication Contract

## CAO primitives

- `assign` is for parallel or long-running independent work. It returns a terminal ID; the worker later calls `send_message` back to its parent.
- `handoff` is for synchronous work where the caller needs the result before continuing. The worker is temporary and is removed after successful completion.
- `send_message` is for steering an existing terminal or returning an assigned result.

## Prototype hierarchy

- Only the General may dispatch workers.
- Workers may not spawn additional workers.
- The General should reuse an active worker terminal rather than create a duplicate.
- Every message must include the task ID.
- Every assignment must include an exact artifact path.

## Callback format

```text
TASK: <TASK-ID>
STATUS: COMPLETED | BLOCKED | FAILED
ARTIFACT: <absolute path or NONE>
FINDINGS:
- <up to five concise findings>
BLOCKER_OR_DECISION: <text or NONE>
```

Long analyses belong in files, not inbox messages.

## Failure recovery

Before replacing a worker:

1. inspect session and worker status,
2. message the existing terminal,
3. preserve partial artifacts,
4. record why replacement is necessary,
5. get human approval when replacement changes scope or cost materially.
