# 1c-rules plugin

Thin marketplace wrapper. It does **not** ship `content/rules` as plugin rules. After the host enables the plugin, `scripts/invoke-install.ps1` calls the real `install.ps1`, and adapters still rewrite files for Cursor, Claude Code, OpenCode or Kilo Code.

## What the plugin contains

- Skills `/1c-rules:install` and `/1c-rules:update`
- Matching slash commands
- Host hooks / OpenCode plugin that run `ensure` on a 1C project (init or `add` the host tool; never auto-update)
- `plugin.mjs` for OpenCode and Kilo CLI

## Local check

```powershell
# Plan only
powershell.exe -NoProfile -File .\plugins\1c-rules\scripts\invoke-install.ps1 -Action ensure -Tool cursor -ProjectRoot . -DryRun

# Claude Code, this checkout
claude --plugin-dir .\plugins\1c-rules
```
