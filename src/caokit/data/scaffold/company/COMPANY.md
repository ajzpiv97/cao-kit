# Company Context

## Mission

Replace this paragraph with the product or project mission for the repository.

## Prototype objective

Show that a General can coordinate engineer, scout and inspector workers through CAO while producing persistent, reviewable artifacts.

## Repository description

Replace this paragraph with a concise description of the repository, its users, and its major components.

## Team

The team is a set of **roles**, not named tools. Which tool and model fills each role in this project is in `ROSTER.md`.

| Role | Authority |
|---|---|
| General | Single entry point. Drafts tasks, dispatches by role, runs the acceptance procedure. Reads the repo, writes `.company/` only. The only role that dispatches. |
| Engineer | Scoped implementation; runs only the task's authorised commands. |
| Scout | Research; read-only, does not build. Writes under `.company/` only. |
| Inspector | Independent review outside the line that did the work; writes `.company/reviews/` only. |

## Human approval gates

The founder must explicitly approve source-modifying tasks, merges, pushes, deployments, production access, external communication, secrets access, dependency changes, and destructive actions.
