# Review Contract

## Independence

Whenever source code is modified, the primary reviewer must use a different provider from the authoring worker.

## Required review dimensions

- task-scope compliance,
- correctness,
- tests and validation,
- security and privacy,
- backward compatibility,
- maintainability,
- unnecessary complexity,
- documentation and operational impact,
- unsupported claims in artifacts.

## Severity

- **BLOCKING:** unsafe, incorrect, out of scope, or acceptance criteria cannot pass.
- **MAJOR:** material defect or missing validation that should be resolved first.
- **MINOR:** useful improvement that does not block acceptance.
- **NOTE:** observation or follow-up idea.

## Acceptance table

Every review includes:

```text
| Acceptance check | Result | Evidence |
|---|---|---|
| ... | PASS / FAIL / NOT VERIFIED | path, command, or artifact evidence |
```

The reviewer does not merge, deploy, or silently repair the work. It reports findings to the General.
