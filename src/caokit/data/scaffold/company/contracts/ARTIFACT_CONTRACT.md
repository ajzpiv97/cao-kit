# Artifact Contract

## Persistence

Substantial outputs must be written under `.company/` so they survive terminal shutdown and can be reviewed by another provider.

## Required metadata

Every artifact begins with:

```text
Task ID:
Author profile:
Provider:
Created:
Status:
Inputs:
```

## Content standard

An artifact must state:

- what was examined,
- what was done,
- evidence supporting conclusions,
- assumptions and uncertainty,
- validation performed,
- unresolved risks,
- decisions required,
- recommended next action.

## Naming

```text
.company/artifacts/<TASK-ID>-<profile>.md
.company/research/<TASK-ID>-<profile>.md
.company/reviews/<TASK-ID>-<reviewer>.md
.company/decisions/<TASK-ID>-<decision>.md
```

## No terminal-only completion

A worker has not completed a substantial task when its only output is terminal text. The callback must point to the persistent artifact.
