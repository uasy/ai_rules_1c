---
description: Explicitly enable, disable or inspect UI testing independently of verification depth and orchestration
userOnly: true
argumentHint: "[on|auto|manual|off|status]"
---

# /uitests — explicit UI-test policy

Control `UI_TESTING` in `.dev.env`. Read `content/rules/dev-standards-env.md → UI_TESTING — web UI-testing mode`; it owns execution prerequisites. This command configures policy, not a test run, deployment or installation.

## Arguments

Trim whitespace and compare case-insensitively:

- `on` or `auto` → `UI_TESTING=auto`: run applicable UI scenarios automatically during verification when the authorized dev/test environment and tools are ready.
- `manual` → `UI_TESTING=manual`: run only on an explicit UI-test request; this is the default for a missing, empty or invalid setting.
- `off` → `UI_TESTING=off`: do not run UI tests.
- Empty or `status` → report the effective state; change nothing.
- Any other argument → list accepted values; change nothing.

## Apply

1. Read the current setting and any explicit session override. Edit only `UI_TESTING` in an existing `.dev.env`, replacing its line or appending a missing key; preserve all other content. If the file is absent, apply a session-only override and point to `install.ps1 init` for persistent project setup; do not create a partial file or start installation.
2. Apply the selected value immediately, replacing any earlier UI policy override in this session. No re-render or client restart is needed for a value change. The command definition itself must first be installed by the normal rules update flow.
3. Confirm in Russian: effective value, project-persistent or session-only scope, and what triggers a run. For `auto`, report any known missing prerequisite without starting a setup questionnaire or claiming readiness.

## Status and boundaries

Status reports the effective value and source (session override, project setting or default), whether the publication URL is configured, and any already-known environment/tool blocker. Do not connect to an infobase or open a browser just to display policy.

An explicit natural-language enable/disable request follows this command; mere discussion or quoted examples do not switch policy. A request to run tests once under `manual` does not change the persistent value. Under `off`, a test-run request alone does not enable UI; point to `/uitests on` or `/uitests manual`. An explicit instruction to both enable and run needs no second toggle confirmation, but execution prerequisites still apply.

UI policy is independent of Mode, verification depth and orchestration. `/sdlc` and `/litemode` preserve it. `off` disables only UI execution: the agent must still perform applicable static checks, review and other allowed behavioural verification. It is not a passing UI result or a blanket DoD waiver; criteria that require UI evidence stay unverified unless explicitly waived in scope. Canon: `content/rules/verification-delivery.md → Soft gate D — UI confirmation policy`.
