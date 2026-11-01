# TASK-0001: Two-provider (Claude + Antigravity) orchestration smoke test

- **State:** APPROVED
- **Owner:** `startup_captain`
- **Workers:** `claude_engineer`, `agy_researcher`
- **Reviewer:** `claude_reviewer`

## Objective

Prove that the Claude captain can launch and coordinate one Claude Code engineer and one Antigravity/Gemini worker, collect file-based artifacts from both, obtain an independent review, and write a synthesis.

## Inputs

- repository contents,
- `.company/COMPANY.md`,
- all `.company/contracts/*.md` files.

## Allowed paths

All agents may read the repository according to their profile. Writes are limited to:

- `.company/TEAM.md`
- `.company/BACKLOG.md`
- `.company/artifacts/TASK-0001-engineering-assessment.md`
- `.company/research/TASK-0001-agy-product-assessment.md`
- `.company/reviews/TASK-0001-cross-provider-review.md`
- `.company/decisions/TASK-0001-captain-synthesis.md`

## Forbidden paths and actions

- no application-source modifications,
- no dependency or lockfile changes,
- no Git state changes,
- no deployment, merge, push, or publishing,
- no credentials, secrets, production systems, or external side effects,
- no worker may spawn another worker.

## Engineering deliverable (`claude_engineer`)

Write `.company/artifacts/TASK-0001-engineering-assessment.md` covering:

- repository structure and primary components,
- likely execution path or architecture,
- test and validation setup,
- five technical risks or improvement opportunities,
- three candidate engineering tasks with estimated complexity,
- explicit unknowns.

Do not modify application source and do not run commands that mutate the project.

## Antigravity deliverable

Write `.company/research/TASK-0001-agy-product-assessment.md` covering:

- apparent product purpose and target user,
- observed user journey from repository evidence,
- missing or ambiguous product capabilities,
- three possible product directions,
- questions requiring human validation,
- sources and evidence for any web-derived statements.

Do not modify application source or perform external side effects.

## Review deliverable

`claude_reviewer` writes `.company/reviews/TASK-0001-cross-provider-review.md` covering:

- task-scope compliance,
- overlap and disagreement between artifacts,
- unsupported or weakly supported claims,
- whether each acceptance check passes,
- blockers before a source-changing prototype task.

## Captain deliverable

Write `.company/decisions/TASK-0001-captain-synthesis.md` with:

- provider routing proof,
- worker terminal IDs,
- completed artifact paths,
- agreements and disagreements,
- recommended next milestone,
- proposed TASK-0002,
- decisions required from the human.

## Acceptance checks

- [ ] The active CAO session shows a Claude captain.
- [ ] The captain launches `claude_engineer` with provider `claude_code`.
- [ ] The captain launches `agy_researcher` with provider `antigravity_cli`.
- [ ] Both workers return callbacks to the captain.
- [ ] Both required worker artifacts exist and are non-empty.
- [ ] No application-source file is modified.
- [ ] `claude_reviewer` produces the review artifact.
- [ ] The captain produces the synthesis artifact.
- [ ] The synthesis records unresolved uncertainty rather than inventing missing evidence.

## Validation

```bash
git status --short
find .company -type f -print
```

Application-source changes cause this task to fail.

## Approval boundary

The human must approve any source-changing follow-up task.
