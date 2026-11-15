# Artifact Contract

## Persistence

Substantial outputs must be written under `.caokit/` so they survive terminal shutdown and can be reviewed by another provider.

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
.caokit/artifacts/<TASK-ID>-<profile>.md
.caokit/research/<TASK-ID>-<profile>.md
.caokit/reviews/<TASK-ID>-<reviewer>.md
.caokit/decisions/<TASK-ID>-<decision>.md
```

## No terminal-only completion

A worker has not completed a substantial task when its only output is terminal text. The callback must point to the persistent artifact.
