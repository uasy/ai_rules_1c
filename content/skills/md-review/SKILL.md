---
name: md-review
description: "Review a Markdown document before it goes into the repository — leaks of local data (internal addresses, secrets, real object identifiers and infrastructure names), dangling links, and whether the content still matches what that kind of document is for. Use when a .md file is created or substantially edited, and before committing documentation."
---

# Markdown review — leaks and fitness for purpose

Two halves. The mechanical one is a script; the judgement one is this file.

## Scope: git decides

A file **git does not ignore** goes into the repository and is checked strictly. An ignored
file (`tmp/`, `.dev.env`, `base/`) is the working environment: real addresses, identifiers
and infrastructure names are allowed there, and only dangling links are checked.

That split is the whole point. Evidence, snapshots and probe output belong in `tmp/`; what
gets committed must survive being read by someone outside this network.

## 1. Mechanical half — the scanner

```bash
python3 skills/md-review/scripts/md-review.py            # whole repository
python3 skills/md-review/scripts/md-review.py openspec/  # files or directories
python3 skills/md-review/scripts/md-review.py --json     # machine-readable
```

Exit code 1 when at least one `error` is found.

| Code | Level | What it catches |
|---|---|---|
| `MD001` | error | Internal address (RFC 1918: `10.*`, `192.168.*`, `172.16–31.*`) |
| `MD002` | error | A literal following a secret-looking name — either as an assignment or as the next positional argument (the shape `ХранилищеОбщихНастроек.Сохранить` uses); see the example below |
| `MD003` | error | External-system object id — 24 hex digits, no dashes; a 1C platform UUID does not match |
| `MD004` | error | Real infrastructure name from the local list |
| `MD005` | error | Relative link resolves to nothing |
| `MD006` | warning | Russian **prose** in a top-level document `AGENTS.md` requires to be English |
| `MD007` | warning | Unclosed placeholder (`TODO`, `TBD`, "будет уточнено") in an OpenSpec artefact |

<!-- md-review: MD008 — deliberately local; the list itself must not reach the repository -->
**The infrastructure name list lives in `tmp/md-review-names.txt`**, one name per line. It sits
in an ignored directory deliberately: the list of hosts and systems must not reach the
repository either. No file — `MD004` is skipped, and the report says so.

### Rules are simple on purpose

`MD002` does not try to tell a real secret from a settings name. Any literal after a
secret-looking name is reported, `ХранилищеОбщихНастроек.Загрузить("НастройкиИнтеграции",
"КлючДоступа")` included. A heuristic clever enough to clear that line — "a real key mixes
letters with digits", say — would silently miss a key that happens to be letters only. A rule
that over-reports and is argued down in writing beats a rule that under-reports invisibly.

The cost is annotation, and that is the intended trade: each suppression is a visible,
reviewable decision with a stated reason.

### Suppressing a finding

Same practice as with BSL diagnostics — a comment **above** the line it excuses. Two forms,
because an HTML comment cannot go inside a fenced code block without showing up in the
rendered code:

In prose:

```markdown
<!-- md-review: MD003 — identifier example from the vendor's documentation -->
Example call: `POST /folders/0123456789abcdef01234567/move`
```

Inside a code block — a line comment (`//`, `#` or `--`):

```bsl
// MD002 - safe: setting names only, no real data
ХранилищеОбщихНастроек.Загрузить("НастройкиИнтеграции", "КлючДоступа");
```

A suppression covers its own line and the next one — one direction only, so that it cannot
swallow a neighbouring real finding. Read the whole reported line before annotating it: a call
with three arguments produces two findings, and the harmless one sits next to the dangerous
one. A suppression with no reason after the dash is a bad sign: writing the reason down is
what verifies the finding is genuinely false.

`MD006` covers the top-level documents only (`AGENTS.md`, `USER-RULES.md`, `LLM-RULES.md`,
`memory.md`, `References.md`), not the rules / skills / agents / commands trees. Those are English
prose around a Russian domain — DSL property values, metadata identifiers, quoted platform
messages — and the directory-wide form of the check produced 1505 warnings with no true positive
over the `1c-rules` content tree. A warning that loud is a warning nobody reads.

### What the scanner deliberately misses

It is tuned for a small set of shapes, not for coverage. It does not look for staff names,
internal hostnames without a scheme (`srv-01.corp`), secrets written as prose ("the key is kept
in …"), or public URLs that mean an internal resource inside this network. That is the second
half's job.

## 2. The judgement half

The scanner cannot answer the main question: **does the content still match what this document
is for.** Check against declared conventions, not against taste.

### Purpose by document type

`openspec/changes/README.md` declares what a change consists of; drifting from it is a finding.

| Document | Purpose | Sign of drift |
|---|---|---|
| `proposal.md` | why and what: scope, approach, risks | turns into technical decisions |
| `design.md` | how: technical decisions and their rationale | turns into a work report |
| `tasks.md` | **implementation checklist with checkboxes** | turns into a journal: "revised after review", "variant rejected", superseded notes |
| `specs/**/spec.md` | requirements and scenarios | implementation detail creeps in |
| a skill's `SKILL.md` | what to do and when | turns into the history of writing the skill |

### Questions to put to the text

- **A fact, or the story of discovering it?** A document states how the system behaves, not how
  we found out. "The external service rejects an empty title" — yes; "found during manual
  acceptance on 2026-09-02, we first thought otherwise" — no.
- **Will the link survive archiving?** `openspec/changes/**` disappears on `/opsx:archive`.
  Code and long-lived documents must not point there; the direction is one-way.
- **Is the statement still true?** Superseded notes ("the previous version did it differently")
  mislead worse than missing text does.
- **Is the fact duplicated?** One fact in three documents is three places that will age
  differently. A fact lives in one place; the rest link to it.
- **Language per the `AGENTS.md` policy?** Rules, skills, agents and commands — English; BSL,
  metadata synonyms, user-facing strings and replies — Russian; `README.md` — Russian.

## Order of work

1. Run the scanner over the touched files; resolve every finding — fix it or suppress it with
   a stated reason.
2. Identify the document type and check the content against its purpose above.
3. Walk the questions in "Questions to put to the text".
4. In the report, say what was fixed and what was left deliberately.

A defect found in a **shipped** 1c-rules rule or skill is not fixed in place — that is the
`/support` route (`support-feedback.md`).
