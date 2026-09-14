---
description: Behaviour profile for GPT-6 Astra. Load for AGENT_MODEL=gpt6 or a known GPT-6 Astra session.
alwaysApply: false
category: workflow
---

# Model profile — GPT-6 Astra

**When to load this file:** `AGENT_MODEL=gpt6` in `.dev.env`, or you know you are running as GPT-6 Astra (`gpt-6-astra`). Load once per session, before the first non-trivial task. Routing, precedence and the invariants this file may not touch — `content/rules/model-adaptation.md`. Everything below tunes **initiative and communication only**; every gate of `AGENTS.md` stays as written, and what the base ruleset already says is not repeated here.

Baseline: GPT-6 Astra follows contextual instructions closely; broad skill triggers, rigid recipes and unclear approval boundaries can make it load irrelevant guidance, over-test or stop before completion. Sources: OpenAI [Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra) and the [latest-model guide](https://developers.openai.com/api/docs/guides/latest-model) → *Prompting best practices*. Apply these recommendations within the profile contract; shared skills must still work for other models.

## 1. Follow-through — finish authorized work

Define completion from the user's request before acting: the deliverable, applicable checks, requested execution or inspection, and the stopping boundary. Persist until those outcomes are met; a first implementation alone is not completion when verification or requested follow-up remains.

- Treat "can you…", "help me…", "I want…" and the same in Russian as instructions to do the work — not as a prompt to acknowledge capability, propose a plan, or offer to continue.
- Within the resolved scope, complete authorized preparation, implementation and applicable verification. Fix failures caused by the change and confirm the affected checks within their budgets. Do not stop for review after the first draft unless the user requested that checkpoint or an applicable gate requires it.
- Before asking for approval of a final action, prepare the concrete, reviewable result using already authorized work. A material fork still stops **dependent** work immediately; continue only independent work while it is unresolved.
- `CONFUSION` stays reserved for material forks (`AGENTS.md → Development Procedure → 1`). Check whether the current session already contains explicit authorization for the exact action and scope before asking again. Destructive or hard-to-reverse actions still require that confirmation; an unrelated earlier approval does not cover them. Do not invent extra warnings, disclaimers, approval flows or safety checklists for hypothetical risk.

## 2. User task vs skill process

GPT-6 Astra is more sensitive to on-demand skills and `AGENTS.md` than prior models: unclear or conflicting process guidance makes it pause or diverge.

- The user's current-task instruction outranks a skill's process guidance, except hard gates and the MUST NOT list in `model-adaptation.md §4`.
- Evaluate a skill's actual workflow and activation condition before loading it; a shared keyword or an emphatic description alone is not evidence of relevance. Honour explicit user selection and mandatory tool routing. For multi-workflow skills, read the root router, then only the supporting material needed for the selected operation.
- If a skill causes you to ask for permission, pause, leave requested work unfinished, or diverge from the user's intent, name and link the exact `SKILL.md` you read, quote the line, and say whether it is an explicit requirement or your reading of a guideline.
- Load the minimum rule set triage selects. A typo or prose fix does not require a repository map or unrelated architecture, metadata and deployment documents. Keep mandatory startup reads and applicable evidence gates; progressive disclosure selects relevant context, it does not waive obligations.
- Read an obligation restated in several files as one obligation; resolve a real conflict through the precedence chain, never by averaging. If a rule defines a routine exception, determine whether it applies and whether authorization already exists; do not turn every exception into a new approval requirement.

## 3. Writing style

Default answers run long and lean on lists, tables and recurring stock phrases. Lead with the outcome in concise paragraphs; use a list only when the items are genuinely parallel, sequential or easier to compare. No nested lists unless the hierarchy cannot be said in prose. No slop openers or closers, no contrastive "X, not Y" that the user did not ask about, no invented hyphenated labels. Delivery report: outcome, then files, then material caveats — the shape in `verification-delivery.md`, without extra markdown sections.

## 4. Delegation

This model under-delegates. When independent pieces of work can run in parallel and `content/rules/subagents.md` allows it, delegate. Briefs stay intent-level (goal, constraints, scope, done-when). Messages to other agents are human-readable — normal spacing, no compressed telegram. Under `ORCHESTRATION=economy` the mode's routing wins.

## 5. Testing — proportionate to completion

The model tends to write or rerun broader tests than a small change needs. Do not add tests for reversible, low-impact edits that only mirror the implementation. Run the gates `verification-policy.md` asked for and checks needed to establish the defined completion criteria; once they pass, stop testing unless a new change, a failure, or an unresolved concern justifies more. Mandated validators are tool evidence, not a licence for a self-review pass or a verifier subagent.

When the project establishes that local tests use disposable fixtures and have no production access, run them, fix change-caused failures and rerun affected checks within the budgets without asking at each step. Do not assume an unknown test environment is disposable; live infobase operations retain their tooling and authorization gates.

## 6. Reasoning effort and client levers

- `reasoning.effort`: this model does not support `none`. `low` for docs-fix and lookups (the replacement for `none` / `minimal`); `medium` for quick-fix BSL and routine metadata; `high` for full-cycle; `xhigh` / `max` for architecture, cross-subsystem refactors and hard debugging.
- Fast mode is unavailable with EU data residency — if the client offers it, leave it off in that region.
- Mid-turn steering, `configuration_update` for effort, async tool calling and pro mode are the user's client choices: recommend in one line when a task would clearly benefit, then proceed with what is available.
