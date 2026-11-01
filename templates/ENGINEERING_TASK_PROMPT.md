Captain, execute the approved task in `.company/tasks/<TASK-ID>.md`.

1. Read all company contracts.
2. Validate the task has explicit allowed and forbidden paths.
3. Assign the task to `claude_engineer` using the exact task file and artifact path.
4. Do not modify source yourself.
5. When the engineer reports `REVIEW_READY`, hand off to `agy_reviewer` (Antigravity) for review: a different provider from the Claude author.
6. Reconcile the review against each acceptance check.
7. Do not merge, push, or deploy.
8. Present the human with artifact paths, test evidence, review findings, and decisions required.
