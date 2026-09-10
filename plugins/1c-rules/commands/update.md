---
name: update
description: Update 1c-rules in this project via install.ps1
---

If `.ai-rules.json` is missing, run `/1c-rules:install` instead.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<plugin>/scripts/invoke-install.ps1" -Action update -ProjectRoot "<project-root>"
```

Keep `USER-RULES.md`, `memory.md`, and `LLM-RULES.md` untouched.
