#!/usr/bin/env python3
"""Markdown scanner: local-data leaks and dangling links.

Scope is decided by git: a file git does NOT ignore goes into the repository and
is checked strictly; an ignored one (tmp/, .dev.env, base/) is the working
environment — local data is allowed there and only dangling links are checked.

A single finding is suppressed by a comment in the document itself, following the
practice used for BSL diagnostics:

    <!-- md-review: MD003 — identifier example from the vendor's documentation -->

The comment goes ABOVE the line it justifies (or at the end of that line) and
covers its own line and the next one.

Usage:
    python3 skills/md-review/scripts/md-review.py [paths...] [--all] [--json]

Without paths, tracked and new .md files outside ignored directories are checked.
Exit code: 0 — no findings at level error; 1 — at least one.
"""

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                      capture_output=True, text=True).stdout.strip() or os.getcwd()

# --- rules -------------------------------------------------------------------

# RFC 1918 private ranges, plus explicit http(s) links to non-public hosts.
RE_PRIVATE_IP = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")

SECRET_NAME = r"(pass(?:word)?|pwd|secret|token|api[_-]?key|ключ\w*|парол\w*)"

# The rule is deliberately simple and wide: a "secret-looking" name followed by a
# literal. A value cannot be told apart from a setting name reliably — a heuristic
# like "letters mixed with digits" would silently miss an all-letter key. So both
# cases are caught, and a legitimate mention is justified by a suppression comment
# carrying the reason: a visible, reviewable decision instead of an invisible
# heuristic.
RE_SECRET = re.compile(
    SECRET_NAME + r"\b\s*[:=]\s*[\"']?([A-Za-z0-9+/=_\-\.]{8,})[\"']?", re.I)

# A secret passed as an ARGUMENT — the shape 1C settings storage uses:
# ХранилищеОбщихНастроек.Сохранить("<НаборНастроек>", "КлючДоступа", "<value>").
# The value sits in a lookahead: otherwise the match eats the closing quote and the
# next argument pair is not parsed, so a three-argument call would report the
# setting name preceding the secret instead of the secret.
RE_SECRET_ARG = re.compile(
    r"[\"']" + SECRET_NAME + r"[^\"']*[\"']\s*,\s*(?=[\"']([^\"']{8,})[\"'])", re.I)

# Opaque object identifier of an external system: 24 hex digits, no dashes
# (MongoDB-style ObjectId, and the id shape several REST APIs expose).
# A 1C platform UUID (8-4-4-4-12, with dashes) does not match this pattern.
RE_OBJECT_ID = re.compile(r"\b[0-9a-f]{24}\b")

# Links: [text](path) and paths in backticks.
RE_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s#]+)(?:#[^)]*)?\)")

# A path in backticks: candidate for the "does it exist in the repository" check.
RE_BACKTICK_PATH = re.compile(r"`([\w.][\w./-]*/[\w./-]+)`")

RE_TODO = re.compile(
    r"(?i)(\bTODO\b|\bTBD\b|\bFIXME\b|будет уточнено|уточнить позже|"
    r"заполнить позже|\(уточнить\)|<заполнить>)")

# Cyrillic in an English-only file is a violation only in prose. 1C identifiers
# (ТестируемоеПриложение, ПерейтиКСтроке) and quoted platform messages are
# unavoidable, so code is stripped out and a chain of Cyrillic words is what
# counts as prose.
RE_CODE_SPAN = re.compile(r"`[^`]*`")
# A quoted platform message is not the author's prose: in an English document
# about 1C, reproducing the Russian error text verbatim is normal and necessary.
RE_QUOTED = re.compile(r"«[^»]*»|\"[^\"]*\"")
RE_CYRILLIC_PROSE = re.compile(r"[А-Яа-яЁё]+(?:\s+[А-Яа-яЁё]+){2,}")

# Two suppression forms: an HTML comment in prose, and a line comment inside a
# code block — an HTML comment cannot go inside ``` without being displayed.
RE_SUPPRESS = re.compile(
    r"<!--\s*md-review:\s*(MD\d{3})"
    r"|(?:^|\s)(?://|#|--)\s*(MD\d{3})\b")

# Example values that are not secrets.
SECRET_ALLOW = re.compile(
    r"(?i)^(cryptedpassword|password|пароль|значение|example|placeholder|"
    r"<[^>]+>|\*+|xxx+|\.\.\.)$")

# Files that AGENTS.md requires to be written in English.
#
# Only the top-level documents are checked, deliberately. Rules, skills, agents
# and commands are English prose *around* a Russian domain: DSL property values,
# metadata identifiers, quoted platform messages, message templates. Measured over
# the 1c-rules content tree the directory-wide form produced 1505 warnings and not
# one true positive — a rule that loud is a rule nobody reads. The top-level
# documents have no such domain content, so there the check still carries signal.
ENGLISH_ONLY = ()
ENGLISH_ONLY_FILES = ("AGENTS.md", "USER-RULES.md", "LLM-RULES.md", "memory.md",
                      "References.md")


def git_lines(args):
    r = subprocess.run(["git"] + args, capture_output=True, text=True, cwd=ROOT)
    return [x for x in r.stdout.splitlines() if x.strip()]


def ignored(path):
    r = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
    return r.returncode == 0


def collect(paths, include_all):
    if paths:
        out = []
        for p in paths:
            if os.path.isdir(p):
                for root, _, files in os.walk(p):
                    out += [os.path.join(root, f) for f in files if f.endswith(".md")]
            elif p.endswith(".md"):
                out.append(p)
        return sorted(set(out))
    tracked = git_lines(["ls-files", "*.md"])
    untracked = git_lines(["ls-files", "--others", "--exclude-standard", "*.md"])
    found = sorted(set(tracked + untracked))
    if include_all:
        return found
    return [f for f in found if not f.startswith("tmp/")]


def mask(text):
    """Blank out code and quotes, preserving newlines so line numbers survive."""
    def blank(m):
        return "".join("\n" if ch == "\n" else " " for ch in m.group(0))

    text = re.sub(r"```.*?```", blank, text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", blank, text)
    text = re.sub(r"«.*?»", blank, text, flags=re.S)
    text = re.sub(r'"[^"]*"', blank, text, flags=re.S)
    return text


def suppressed(lines, index):
    """A suppression covers its own line and the one after it.

    One direction only, top down: the comment precedes what it justifies. A
    two-sided window would swallow a genuine finding on the neighbouring line.
    """
    codes = set()
    for i in (index, index - 1):
        if 0 <= i < len(lines):
            for pair in RE_SUPPRESS.findall(lines[i]):
                codes |= {c for c in pair if c}
    return codes


def local_names():
    """Real infrastructure names — from a local file, never from the repository."""
    path = os.path.join(ROOT, "tmp", "md-review-names.txt")
    if not os.path.exists(path):
        return []
    names = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                names.append(line)
    return names


def check(path, repo_bound, names):
    full = os.path.join(ROOT, path)
    try:
        with open(full, encoding="utf-8") as f:
            text = f.read()
        lines = text.splitlines()
        masked = mask(text).splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [(path, 0, "MD000", "error", f"file not read: {exc}")]

    findings = []

    def add(no, code, level, text):
        if code in suppressed(lines, no - 1):
            return
        findings.append((path, no, code, level, text))

    english_only = path.startswith(ENGLISH_ONLY) or path in ENGLISH_ONLY_FILES
    in_code = False

    for no, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue

        if repo_bound:
            for m in RE_PRIVATE_IP.finditer(line):
                add(no, "MD001", "error", f"internal address: {m.group(0)}")

            for m in RE_SECRET.finditer(line):
                value = m.group(2)
                if not SECRET_ALLOW.match(value):
                    add(no, "MD002", "error",
                        f"looks like a secret: {m.group(1)}=<{len(value)} chars>")

            for m in RE_SECRET_ARG.finditer(line):
                value = m.group(2)
                if not SECRET_ALLOW.match(value):
                    add(no, "MD002", "error",
                        f"literal following \"{m.group(1)}\": <{len(value)} chars>")

            for m in RE_OBJECT_ID.finditer(line):
                add(no, "MD003", "error",
                    f"external-system object id: {m.group(0)}")

            for name in names:
                if re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", line):
                    add(no, "MD004", "error", f"real infrastructure name: {name}")

            if english_only and not in_code:
                prose = RE_CYRILLIC_PROSE.search(
                    masked[no - 1] if no - 1 < len(masked) else "")
                if prose:
                    add(no, "MD006", "warning",
                        "Russian prose in a file AGENTS.md requires to be in "
                        f"English: \"{prose.group(0)[:40]}…\"")

            for m in RE_BACKTICK_PATH.finditer(line):
                target = m.group(1)
                if os.path.exists(os.path.join(ROOT, target)) and ignored(target):
                    add(no, "MD008", "warning",
                        f"link to a local path outside the repository: {target}")

            if path.startswith("openspec/") and RE_TODO.search(line):
                add(no, "MD007", "warning", "unclosed placeholder in an OpenSpec artefact")

        for m in RE_MD_LINK.finditer(line):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = os.path.normpath(
                os.path.join(os.path.dirname(full), target))
            if not os.path.exists(resolved):
                add(no, "MD005", "error", f"link resolves to nothing: {target}")

    return findings


def main():
    ap = argparse.ArgumentParser(description="Markdown review scanner")
    ap.add_argument("paths", nargs="*", help="files or directories (default: whole repository)")
    ap.add_argument("--all", action="store_true", help="include ignored directories (tmp/)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    names = local_names()
    findings = []
    checked = 0
    for path in collect(args.paths, args.all):
        repo_bound = not ignored(path)
        checked += 1
        findings += check(path, repo_bound, names)

    errors = [f for f in findings if f[3] == "error"]

    if args.json:
        print(json.dumps([{"file": f, "line": n, "code": c, "level": lv, "message": t}
                          for f, n, c, lv, t in findings], ensure_ascii=False, indent=1))
    else:
        for f, n, c, lv, t in sorted(findings):
            print(f"{f}:{n}: [{c}] {lv}: {t}")
        print(f"\nFiles checked: {checked}; findings: {len(findings)} "
              f"(error {len(errors)}, warning {len(findings) - len(errors)})")
        if not names:
            print("No infrastructure name list configured — MD004 was not checked "
                  "(file tmp/md-review-names.txt)")
        print("This is the mechanical half only. Whether the content still matches the "
              "document's\npurpose is not scanned — work through \"The judgement half\" "
              "in SKILL.md.")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
