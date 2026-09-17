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

## Tests tree

Tests live in `openspec/tests/<capability>/`, the same capability names as `openspec/specs/`, and
accumulate the way requirements do:

```
openspec/tests/<capability>/
├── README.md     what each test checks, data requirements, environment, «<Тест>: не проверяется»
├── ui/           test-client scenarios: data processor sources and helper programs
├── server/       server-side checks (BSL for the debug executor)
└── http/         HTTP service checks
```

- Tests are written straight into `openspec/tests/` — they are code, they run before the change is
  archived and match the sources, which are not deltas either.
- Only sources go to git; data processors are built into `tmp/test_epf/`.
- **A test must be able to fail**: every new test runs once against a deliberately wrong expectation
  and gives `[FAIL]` exactly on the affected steps.
- The reason a test cannot observe something is a property of the test — it lives in the capability
  README under `#### <Тест>: не проверяется`; `test-plan.md` links to it.

## Test data

- Requirements for data are described in the capability README next to the test.
- Invented values only; the test creates what it needs and removes it; server-side checks run in a
  rolled-back transaction; settings the test changes are restored.
- **Leftovers of earlier runs are removed at the start**: a run stopped by a timeout or a lost session
  never reaches its cleanup. Test data carry an unmistakable invented marker (a name prefix).
- Data that depend on the environment (codes of created objects, external systems) are prepared per
  environment from the README requirements and kept in `tmp/test_epf/test_data/`.
- Data of working infobases are never used — neither copied nor searched for a «suitable» object.
