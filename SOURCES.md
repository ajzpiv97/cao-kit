# Primary documentation used

This kit was assembled on 2026-09-26 for macOS, CAO 2.5.0, and current provider CLIs. Re-check these pages before production use because the CLIs and profile schemas change frequently.

## CLI Agent Orchestrator

- Project and prerequisites: https://github.com/awslabs/cli-agent-orchestrator
- Installation: https://awslabs.github.io/cli-agent-orchestrator/docs/getting-started/installation/
- Quick start and session commands: https://awslabs.github.io/cli-agent-orchestrator/docs/getting-started/quick-start/
- Profile schema: https://awslabs.github.io/cli-agent-orchestrator/docs/features/profiles/
- Multi-provider routing: https://awslabs.github.io/cli-agent-orchestrator/docs/features/multi-provider/
- Assign: https://awslabs.github.io/cli-agent-orchestrator/docs/patterns/assign/
- Handoff: https://awslabs.github.io/cli-agent-orchestrator/docs/patterns/handoff/
- Send message: https://awslabs.github.io/cli-agent-orchestrator/docs/patterns/send-message/
- Tool restrictions: https://github.com/awslabs/cli-agent-orchestrator/blob/main/docs/tool-restrictions.md
- Claude Code provider: https://awslabs.github.io/cli-agent-orchestrator/docs/guides/building-with-claude-code/
- Codex provider: https://github.com/awslabs/cli-agent-orchestrator/blob/main/docs/codex-cli.md
- Antigravity provider: https://github.com/awslabs/cli-agent-orchestrator/blob/main/docs/antigravity-cli.md

## Provider CLIs

- Claude Code setup: https://code.claude.com/docs/en/setup
- Codex advanced configuration and named profile files: https://learn.chatgpt.com/docs/config-file/config-advanced
- Codex configuration reference: https://learn.chatgpt.com/docs/config-file/config-reference
- Antigravity CLI installer: https://antigravity.google/cli/install.sh

## Compatibility note

Current Codex versions load `--profile NAME` from `~/.codex/NAME.config.toml`. Codex 0.134.0 and later no longer reads the older `[profiles.NAME]` tables. The kit includes both the current files and a clearly separated legacy fallback note.
