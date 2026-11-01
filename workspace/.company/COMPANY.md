# Company Context

## Mission

Replace this paragraph with the product or project mission for the repository.

## Prototype objective

Prove that a Claude Code captain can coordinate Claude Code and Antigravity CLI workers through CAO while producing persistent, reviewable artifacts.

## Repository description

Replace this paragraph with a concise description of the repository, its users, and its major components.

## Team

| Role | CAO profile | Provider | Initial authority |
|---|---|---|---|
| Captain | `startup_captain` | Claude Code | Coordinate, read repo, write `.company/` only |
| Engineer | `claude_engineer` | Claude Code | Scoped implementation; TASK-0001 is analysis-only |
| Cross-provider reviewer | `agy_reviewer` | Antigravity/Gemini | Reviews Claude-authored changes; writes `.company/reviews/` only |
| Researcher | `agy_researcher` | Antigravity/Gemini | Read/research; write `.company/` only |
| Artifact reviewer | `claude_reviewer` | Claude Code | Review; write `.company/reviews/` only |

## Human approval gates

The founder must explicitly approve source-modifying tasks, merges, pushes, deployments, production access, external communication, secrets access, dependency changes, and destructive actions.
