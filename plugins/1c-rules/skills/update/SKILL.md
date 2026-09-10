---
name: update
description: Update an existing 1c-rules install by running install.ps1 update. Use when the user asks to update 1C rules, /updaterules, or refresh 1c-rules after a marketplace plugin update.
---

# Update 1c-rules

Call `install.ps1 update` through the plugin wrapper. Do not overwrite `USER-RULES.md`, `memory.md`, or `LLM-RULES.md`.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<plugin>/scripts/invoke-install.ps1" -Action update -ProjectRoot "<project-root>"
```

If `.ai-rules.json` is missing, this is a first install: use the `install` skill (`-Action init`), not update.
