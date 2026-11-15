# TASK-0001: Role-based orchestration smoke test

- **State:** APPROVED
- **Owner:** `general`
- **Workers:** `engineer`, `scout`
- **Reviewer:** `inspector`

## Objective

Prove that the General can launch and coordinate one engineer and one scout, collect file-based artifacts from both, obtain an independent review, and write a synthesis.

## Inputs

- repository contents,
- `.caokit/COMPANY.md`,
- all `.caokit/contracts/*.md` files.

## Allowed paths

All agents may read the repository according to their profile. Writes are limited to:

- `.caokit/TEAM.md`
- `.caokit/BACKLOG.md`
- `.caokit/artifacts/TASK-0001-engineering-assessment.md`
- `.caokit/research/TASK-0001-agy-product-assessment.md`
- `.caokit/reviews/TASK-0001-cross-provider-review.md`
- `.caokit/decisions/TASK-0001-general-synthesis.md`

## Forbidden paths and actions

- no application-source modifications,
- no dependency or lockfile changes,
- no Git state changes,
- no deployment, merge, push, or publishing,
- no credentials, secrets, production systems, or external side effects,
- no worker may spawn another worker.

## Engineering deliverable (`engineer`)

Write `.caokit/artifacts/TASK-0001-engineering-assessment.md` covering:

- repository structure and primary components,
- likely execution path or architecture,
- test and validation setup,
- five technical risks or improvement opportunities,
- three candidate engineering tasks with estimated complexity,
- explicit unknowns.

Do not modify application source and do not run commands that mutate the project.

## Scout deliverable

Write `.caokit/research/TASK-0001-agy-product-assessment.md` covering:

- apparent product purpose and target user,
- observed user journey from repository evidence,
- missing or ambiguous product capabilities,
- three possible product directions,
- questions requiring human validation,
- sources and evidence for any web-derived statements.

Do not modify application source or perform external side effects.

## Review deliverable

`inspector` writes `.caokit/reviews/TASK-0001-cross-provider-review.md` covering:

- task-scope compliance,
- overlap and disagreement between artifacts,
- unsupported or weakly supported claims,
- whether each acceptance check passes,
- blockers before a source-changing prototype task.

## General deliverable

Write `.caokit/decisions/TASK-0001-general-synthesis.md` with:

- provider routing proof,
- worker terminal IDs,
- completed artifact paths,
- agreements and disagreements,
- recommended next milestone,
- proposed TASK-0002,
- decisions required from the human.

## Acceptance checks

- [ ] The active CAO session shows the General.
- [ ] The General launches the profile ROSTER.md lists for `engineer`.
- [ ] The General launches the profile ROSTER.md lists for `scout`.
- [ ] Both workers return callbacks to the General.
- [ ] Both required worker artifacts exist and are non-empty.
- [ ] No application-source file is modified.
- [ ] `inspector` produces the review artifact.
- [ ] The General produces the synthesis artifact.
- [ ] The synthesis records unresolved uncertainty rather than inventing missing evidence.

## Validation

```bash
git status --short
find .caokit -type f -print
```

Application-source changes cause this task to fail.

## Approval boundary

The human must approve any source-changing follow-up task.
