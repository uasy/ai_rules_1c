# Change lifecycle with agents

The workflow borrows the artifact set of the community OpenSpec schema *anvil* — review, test plan,
verify — without its full ceremony. OpenSpec itself only checks that artifacts exist; the order
below is kept by the orchestrator (the main session) and by the agents' definitions.

```
proposal / design / delta specs        orchestrator + user
        │
        ▼
review.md            VERDICT            reviewer with a fresh context, read-only
        │ APPROVE / APPROVE_WITH_CHANGES
        ▼
tests + test-plan.md 🔴                  openspec-tester
        │
        ▼
tasks.md done, tests 🟢                  openspec-implementer
        │
        ▼
verify.md            DECISION           openspec-tester
        │ PASS / PASS_WITH_WARNINGS
        ▼
audit, commit, archive                  orchestrator; the decision is the user's
```

A defect found by the tester goes back to the implementer (resume the same session with the
reproduction); rounds are bounded — three, then the user decides.

## `review.md` — before tests and implementation

Written by a reviewer with a fresh context that did not write the proposal — `1c-arch-reviewer`
fits; another model is better still. The reviewer reads the proposal, design, delta specs and the
code they touch, writes only `review.md`:

```
# Ревью — <change>
VERDICT: APPROVE | APPROVE_WITH_CHANGES | REVISE

## Замечания
<numbered findings: what, where, why it matters, what to change>
```

`REVISE` stops the change until the proposal is reworked. `APPROVE_WITH_CHANGES` lists what must be
settled before tests are written.

## `test-plan.md` — the red/green ledger

Written by the tester from the delta specs **before** the implementation:

| Scenario / statement of the requirement | Test step | Status |
|---|---|---|
| <scenario> | «<protocol line of the step>» | 🔴 / 🟢 / ⚪ + link to the reason: `../../tests/<capability>/README.md#<тест>-не-проверяется` |

- 🔴 — the test exists and fails (before implementation this is the expected state); 🟢 — passes;
  ⚪ — not verifiable, with a link to the reason in the capability README.
- Every scenario and every SHALL statement has a row; a silently missing one counts as uncovered.
- A section «Прогоны» records the failure-control run and the final run.
- A test written after the implementation says so: the 🔴 stage did not happen.

## `verify.md` — after implementation

Written by the tester from its own full run, not from the implementer's report:

```
# Проверка — <change>
DECISION: PASS | PASS_WITH_WARNINGS | FAIL

## Прогоны
<command> — <N [OK], M [FAIL]>

## Соответствие test-plan
<every 🟢 row confirmed by this run; every ⚪ has a reason; open 🔴 rows>

## Замечания
<warnings behind PASS_WITH_WARNINGS, defects behind FAIL with reproduction>
```

`DECISION` is evidence, not acceptance: audit and the decision to commit and archive stay with the
orchestrator and the user.

## Tests

Tests live in `openspec/tests/<capability>/`, under the same capability names as `openspec/specs/`,
and accumulate the way requirements do. **The layout, the test types, the naming and the shape of a
capability README are the project's convention in `openspec/tests/README.md`** when the project has
one — read it there rather than from a copy here. The rules for test data are the tester agent's
(`content/agents/openspec-tester.md`, «Data per the rules»).

What belongs to the agent lifecycle, and not to that convention:

- Tests are written straight into `openspec/tests/`, not as deltas of the change: they are code, they
  run before the change is archived, and they have to match the sources.
- **A test must be able to fail.** Every new test runs once against a deliberately wrong expectation
  and must give `[FAIL]` on exactly the affected steps; the result is recorded in `test-plan.md`.
- The reason a test cannot observe something is a property of the test, so it lives in the capability
  README under `#### <Тест>: не проверяется`, and `test-plan.md` links to it instead of restating it.
- Before handing back, the agent runs
  `python3 <skills>/openspec-agents/scripts/coverage-cross-check.py <capability>`: every scenario of
  the spec must be either claimed by a named test or written off in the README.

