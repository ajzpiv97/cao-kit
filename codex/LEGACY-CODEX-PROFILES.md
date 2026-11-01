# Legacy Codex profile syntax

Codex 0.134.0 and newer uses separate files:

```text
~/.codex/cao_engineer.config.toml
~/.codex/cao_reviewer.config.toml
```

Only use the legacy configuration below when `codex --version` reports an older build and separate profile files are not recognized.

Append to `~/.codex/config.toml`:

```toml
[profiles.cao_engineer]
approval_policy = "never"
sandbox_mode = "workspace-write"

[profiles.cao_engineer.sandbox_workspace_write]
network_access = false

[profiles.cao_reviewer]
approval_policy = "never"
sandbox_mode = "read-only"
```

Do not keep both representations after upgrading to Codex 0.134.0 or newer. Move the settings into separate profile files and remove these legacy tables.
