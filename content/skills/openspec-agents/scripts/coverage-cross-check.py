#!/usr/bin/env python3
"""Cross-check: are the requirements covered by tests, or written off.

Every scenario of `openspec/specs/<capability>/spec.md` (and of the delta specs of active changes)
must be either claimed by a test named in the table of `openspec/tests/<capability>/README.md`, or
declared uncovered — under «Не покрыто тестами» or «#### <Тест>: не проверяется». A requirement
named uncovered in full (bold, under «Не покрыто тестами») covers all of its scenarios; the README
is not obliged to list them one by one.

A silent omission is the finding: no test named, no refusal recorded.

Run from the project root — without arguments over every capability, or over the names given.
Exit code 1 when anything is found.
"""
import re, sys, json, pathlib

def find_root():
    """The project root: the nearest ancestor of the working directory holding openspec/specs."""
    d = pathlib.Path.cwd()
    while d != d.parent:
        if (d / "openspec" / "specs").is_dir():
            return d
        d = d.parent
    sys.exit("Run from the project: no openspec/specs here or above")

ROOT = find_root()

def norm(s):
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[«»\"'`(),.:;—–\-\[\]]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def parse_spec(path):
    """-> [(requirement, scenario)]"""
    out, req = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^### Requirement:\s*(.+?)\s*$", line)
        if m:
            req = m.group(1); continue
        m = re.match(r"^#### Scenario:\s*(.+?)\s*$", line)
        if m and req:
            out.append((req, m.group(1)))
    return out

def parse_readme(path):
    text = path.read_text(encoding="utf-8")
    tests = []                       # (test name, requirement, [scenarios])
    for line in text.splitlines():
        m = re.match(r"^\|\s*`([^`]+)`.*?\|([^|]*)\|([^|]*)\|\s*$", line)
        if m and "Требование" not in line:
            tests.append((m.group(1).strip(), m.group(2).strip(),
                          [c.strip() for c in re.split(r"[;]", m.group(3)) if c.strip()]))
    # A requirement named uncovered in full releases the README from listing its scenarios.
    excl_reqs, excl_text = set(), []
    m = re.search(r"^## Не покрыто тестами\s*$(.*)", text, re.M | re.S)
    if m:
        excl_text.append(m.group(1))
        for b in re.finditer(r"\*\*(.+?)\*\*", m.group(1)):
            excl_reqs.add(norm(b.group(1)))
    for m in re.finditer(r"^#### .*?: не проверяется\s*$(.*?)(?=^#{2,4} |\Z)", text, re.M | re.S):
        excl_text.append(m.group(1))
    return tests, excl_reqs, norm(" ".join(excl_text))

def test_file(cap, name):
    base = ROOT / "openspec" / "tests" / cap
    for p in (base / "unit" / f"{name}.bsl", base / "ui" / name, base / "e2e" / name):
        if p.exists():
            return True
    return False

caps = sys.argv[1:] or sorted(p.parent.name for p in (ROOT / "openspec" / "specs").glob("*/spec.md"))
problems = 0
for cap in caps:
    spec = ROOT / "openspec" / "specs" / cap / "spec.md"
    readme = ROOT / "openspec" / "tests" / cap / "README.md"
    if not spec.exists() or not readme.exists():
        print(f"## {cap}: no {'spec' if not spec.exists() else 'tests README'}"); problems += 1; continue

    pairs = parse_spec(spec)
    deltas = []
    for d in sorted((ROOT / "openspec" / "changes").glob(f"*/specs/{cap}/spec.md")):
        if "archive" in d.parts: continue
        for r, s in parse_spec(d):
            deltas.append((r, s, d.parts[-3]))
    tests, excl_reqs, excl = parse_readme(readme)
    claimed = {norm(c): t for t, _req, cs in tests for c in cs}

    print(f"\n## {cap} — requirements {len(set(r for r,_ in pairs))}, scenarios {len(pairs)}"
          + (f" (+{len(deltas)} from active deltas)" if deltas else ""))
    for t, _r, _c in tests:
        if not test_file(cap, t):
            print(f"  [!] test `{t}` is named in the README, but its file is missing"); problems += 1

    silent = []
    for req, sc in pairs + [(r, s) for r, s, _ in deltas]:
        n = norm(sc)
        if n in claimed or norm(req) in excl_reqs or n in excl:
            continue
        silent.append((req, sc))
    if silent:
        print(f"  [!] silently uncovered: {len(silent)}")
        for req, sc in silent:
            print(f"      {req} → «{sc}»")
        problems += len(silent)
    else:
        print("  every scenario is either claimed by a test or named uncovered")

print(f"\nFindings: {problems}")
sys.exit(1 if problems else 0)
