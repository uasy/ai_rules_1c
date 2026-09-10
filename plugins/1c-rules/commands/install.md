---
name: install
description: Install 1c-rules into this project via install.ps1
---

Run the plugin wrapper so `install.ps1` adapts rules for this host.

1. Project root = the current 1C repository. Refuse home / CLI config directories.
2. Tool id: Cursor `cursor`, Claude Code `claude-code`, Codex `codex`, OpenCode `opencode`, Kilo `kilocode`.
3. Execute:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<plugin>/scripts/invoke-install.ps1" -Action init -Tool <tool-id> -ProjectRoot "<project-root>"
```

Do not copy `content/` by hand. Restart the client if MCP config changed.
