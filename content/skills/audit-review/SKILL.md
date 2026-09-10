---
name: audit-review
description: "Read what is about to enter the repository and give a verdict — leaks of local context (people, whose data a file was written from, how systems are reached, third-party records) and whether the content still matches what that file is for. Covers everything committed: documentation, code, configs, fixtures, exported metadata, screenshots. Use before committing, and when a file is created or substantially edited."
---

# Audit review — leaks of context and fitness for purpose

**This skill is a reading task. There is nothing to run.**

The leaks that matter here have no lexical signature. "Проверяли на копии рабочей базы за
июль" names no secret and matches no pattern, yet it tells an outside reader whose data was
copied, from which contour and when. A fixture with a real counterparty, a connection string
in a sample config, a screenshot of a working base — same class, no signature. Pattern
matching cannot see any of it; a reader can.

## Scope: git decides, and it is not only Markdown

A file **git does not ignore** goes into the repository and is reviewed strictly. An ignored
file (`tmp/`, `.dev.env`, `base/`) is the working environment: real addresses, identifiers
and infrastructure names are allowed there.

Everything committed is in scope, and the non-prose files are where leaks survive longest,
because nobody rereads them:

| Kind | Where context leaks in |
|---|---|
| Documentation (`.md`) | Prose about testing, environment, access, examples |
| Code (`.py`, `.ps1`, `.bsl`) | Comments, TODO notes, default values, hard-coded paths and hosts, sample calls |
| Configs and samples (`.json`, `.yaml`, `.env.example`) | Real values left where a placeholder belongs |
| Fixtures and test data | Records taken from a working base instead of invented ones |
| Exported metadata (`.xml`) | Real object names, synonyms, predefined values, comments from the source base |
| Binaries and images | Screenshots of a live base, dumps, exports — the least reviewed and the most revealing |

A screenshot leaks more per byte than any paragraph: window title, database name, user, menu
of a real configuration, counterparties in the list behind the dialog. Open the image and look
at it — a file that cannot be read as text still has to be read.

## Establish the set of files first

The failure mode of this review is not a wrong judgement — it is a file nobody opened. So the
set is enumerated before the reading starts, and every file in it gets its own verdict.

```bash
git status --porcelain                   # created and modified, staged or not
git diff --name-only HEAD                # changed since the last commit
git diff --name-only <base>..HEAD        # everything a branch touches
git diff --cached --name-only            # exactly what is staged for this commit
```

Rules for a batch:

- **A verdict per file, always.** Ten files means ten verdicts. One summary covering a batch
  hides exactly the file that needed attention.
- **A large file is read in sections**, not skimmed whole: sections about testing,
  environment, access and examples are where context concentrates.
- **A file that only gained a typo fix still gets a line** — "без изменений по существу" is a
  verdict. Silence is not.
- **A new binary or image is never waved through** on the grounds that it is not text.

## 1. Read for leaked context

Go through the file once per group. Name what you find; do not rewrite silently.

| Group | What to look for |
|---|---|
| **People** | Names, roles, departments, "спросить у …", who granted access, who made the copy; author notes left in comments |
| **Provenance of data** | Whose base the content was taken from, production or test contour, when it was taken, what was left unmasked — fixtures and exported XML included |
| **Access routes** | Accounts, connection strings, hosts and ports, how a machine is reached, physical location, where a key or credential is kept |
| **Third-party records** | Counterparties, ИНН, contract numbers and dates, debts, personal data — in prose, in fixtures, in test parameters alike |
| **Environment specifics** | Host and system names, internal addresses, local paths (`C:\Users\…`, `/home/…`), links into `tmp/` or a local dump |

Three things worth stating plainly:

- **A statement *about* a credential leaks it as surely as the credential does.** "Пароль тот
  же, что на стенде разработки" compromises both machines.
- **A route to data is a leak, not a substitute for one.** "Ключ лежит в общих настройках",
  "полный лог в `tmp/vygruzka.log`" tell a reader exactly where to go.
- **Test data copied from a working base is production data.** Renaming the file does not
  change what is inside it; invented records are the only safe fixtures.

**Calibration** — `fixtures/context-leaks.md`. It plants twelve items of exactly these kinds
and carries the answer key at the bottom. Read it before trusting your own pass on real
material: if it yields three or four, the reading is too shallow to be worth reporting.

## 2. Read for fitness of purpose

Check against declared conventions, not against taste. Every file type has a purpose, and
drifting from it is a finding.

| File | Purpose | Sign of drift |
|---|---|---|
| `proposal.md` | why and what: scope, approach, risks | turns into technical decisions |
| `design.md` | how: technical decisions and their rationale | turns into a work report |
| `tasks.md` | **implementation checklist with checkboxes** | turns into a journal: "revised after review", "variant rejected", superseded notes |
| `specs/**/spec.md` | requirements and scenarios | implementation detail creeps in |
| a skill's `SKILL.md` | what to do and when | turns into the history of writing the skill |
| a script | one job, stated in its header | debug leftovers, commented-out code, a second job nobody named |
| a config sample | the shape of a setting | a working value in place of a placeholder |
| a fixture | the minimum that reproduces the case | a slab of real export nobody trimmed |

Questions to put to the content:

- **A fact, or the story of discovering it?** A document states how the system behaves, not
  how we found out. "The external service rejects an empty title" — yes; "потратили день,
  думали, что дело в кодировке" — no. In code the same rule applies to comments.
- **Is the statement still true?** Superseded notes ("раньше было написано обратное")
  mislead worse than missing text does.
- **Is the fact duplicated?** One fact in three places is three places that will age
  differently. A fact lives in one place; the rest link to it.
- **Does every link and path resolve?** Open the targets rather than judging them plausible —
  a relative path that looks right is the one that rots unnoticed.
- **Will the link survive archiving?** `openspec/changes/**` disappears on `/opsx:archive`.
  Code and long-lived documents must not point there; the direction is one-way.
- **Is a placeholder still open?** `TODO`, `TBD`, "будет уточнено" in something presented as
  finished.
- **Language per the `AGENTS.md` policy?** Rules, skills, agents and commands — English; BSL,
  metadata synonyms, user-facing strings and replies — Russian; `README.md` — Russian.

## The verdict is the deliverable

Report in this shape, one block per file:

```
Файл: openspec/changes/epd-exchange/proposal.md — назначение: зачем и что (scope, подход, риски)
Утечки контекста: 2
  - строка 14: копия рабочей базы за июль — происхождение данных → обезличить или убрать
  - строка 21: «уточнить у Сергея» — имя сотрудника → убрать, роль назвать без имени
Соответствие назначению: дрейф — раздел «Ход проверки» это отчёт о работе, а не обоснование
Ссылки и пути: 1 битая — ./protokol-obmena.md
Оставлено намеренно: строка 8 — ссылка на openspec/changes/** внутри самого change-пакета

Файл: tools/tests/fixtures/obmen/Contragent.xml — назначение: минимум, воспроизводящий случай
Утечки контекста: 1
  - ООО «Ромашка», ИНН 7707083893 — данные третьего лица из рабочей базы → заменить вымышленными
Соответствие назначению: выгрузка целиком, нужен один элемент
```

Two habits carried over from BSL diagnostics, because they are what makes a verdict
reviewable rather than decorative:

- **Anything left in place is named, with the reason.** A decision recorded in writing is a
  decision someone else can argue with; an unrecorded one is invisible.
- **"Утечек контекста не найдено" is a result only after an actual reading.** After a skim it
  is a false report, and it is worse than no review at all — it certifies the file.

A defect found in a **shipped** 1c-rules rule or skill is not fixed in place — that is the
`/support` route (`support-feedback.md`).
