# Dead Code After Insert Checker — Is Anything Silently Unreachable?

Use as a full-tree sweep to find a top-level (unconditional, not nested inside `Если`/`Пока`/`Для`/`Попытка`) `Возврат` statement that is followed by more code before the end of its routine. That trailing code is unreachable — regardless of whether it is typical (inherited) code shadowed by an `&ИзменениеИКонтроль` insertion, or the extension's own code with a stray early return.

## Why this exists

`#Вставка`/`#КонецВставки` markers and `&`-directives are meaningful to the extension-diff tooling and to a human reading the module, but they do not affect control flow at runtime — the platform executes every statement in a routine's body sequentially regardless of what markers surround it. This creates two related, easy-to-miss defect shapes:

1. **An `&ИзменениеИКонтроль` insertion that ends in an unconditional `Возврат`, immediately followed by the original typical code the interceptor was supposed to extend.** The typical logic silently never runs again, for any caller, and nothing about the diff view makes this obvious — the inserted block looks like a normal override, not a full replacement.
2. **A wholly new (own) routine whose author added an early `Возврат` — often while debugging — and left the rest of the routine's body in place.** The remaining code, sometimes dozens of lines, never executes.

Neither shape is visible to `syntaxcheck`, and both are easy to miss even when every affected file is nominally "read", because the dead code looks identical to live code on the page — only tracing actual reachability reveals it.

## Usage

```bash
python3 skills/1c-extension-analysis/tools/1c-dead-code-after-insert-checker/scripts/dead-code-after-insert-checker.py \
    -ExtensionPath <path-to-extension-source-dump>
```

| Parameter | Description | Default |
|---|---|---|
| `ExtensionPath` | Path to the extension source dump | — (required) |
| `BslFile` | Scope the scan to one `.bsl` file instead of the whole tree | none — whole tree scanned |

## Output

Grouped by file, one block per finding: the routine name, the line of the unconditional `Возврат`, the line and text of the first line of now-unreachable code, and a trailing-line count. A closing summary line gives the total finding count across the whole tree.

## How it avoids the two dominant false-positive classes

Both were found and fixed while validating this tool against a real, large extension — an unfiltered first pass produced well over a hundred hits, almost all noise:

1. **The routine's own closing `КонецФункции`/`КонецПроцедуры` is not "code after the return".** A function whose `Возврат` genuinely is its last statement is completely normal — that is the standard early-return / single-exit-point shape used throughout well-written BSL. The checker explicitly recognizes the routine-end line and treats it as "nothing follows", not as a finding.
2. **A `Возврат` line must actually terminate the statement (end with `;`) to count.** A multi-line call used as the return expression, e.g.:
   ```bsl
   Возврат СтрШаблон("%1;%2;%3;%4",
       НекоторыйАргумент, ...);
   ```
   has its opening line ending in `,` or `(`, not `;` — under a looser "optional `;`" pattern this was mis-treated as a complete, unconditional return, and the second line of the *same* call was reported as "unreachable". Requiring a genuine trailing `;` on the candidate line rejects this shape entirely; the continuation lines are then read as ordinary code with no special meaning, which is correct.

## Known limitations

- **Not a BSL parser — a heuristic depth counter.** Nesting depth is tracked via line-anchored keyword matching (`Если`/`Пока`/`Для`/`Попытка` open, `КонецЕсли`/`КонецЦикла`/`КонецПопытки` close, matched only when they are the *entire* stripped line). A single-line construct combining an opener and its closer on one physical line (e.g. `Если Х Тогда Возврат; КонецЕсли;` written as one line) would desynchronize the depth counter for the rest of the routine. This project's own style rules (`content/rules/dev-standards-code-style.md §2`: *"One statement per line. Single-line constructs with complex logic are prohibited."*) make this shape non-conforming and therefore rare in practice — treat it as a known, accepted gap rather than a reason to build a full tokenizer, consistent with `reference-finder.py`'s own "not a BSL parser" disclaimer.
- **Comment stripping is line-based, not string-literal-aware** — same accepted trade-off as the other tools in this skill.
- **Reports only the first offending `Возврат` per routine.** Once one is found, everything remaining in the routine is unreachable by definition; enumerating further "candidates" inside already-dead code adds noise without adding information.
- **Every finding is a candidate, not an automatically-confirmed defect** — confirm each one against the actual source (what the shadowed code was supposed to do, whether the early return is deliberate) before writing it into a report.

## Relationship to `BSL051` (`UnreachableCode`)

**Verified partial overlap — run both, this tool is not redundant.** `onec-hbk-bsl-*`'s `bsl_diagnostics`/`bsl_check_file` expose a real `BSL051 UnreachableCode` rule. Tested against every confirmed finding from a real-world validation run (see the numbered findings in Provenance below):

- **Plain routines with no `#Вставка`/`#КонецВставки` involved** — `BSL051` correctly fires.
- **Unreachable code sitting right after a `#КонецВставки` marker** — `BSL051` returns **zero** diagnostics. The analyzer appears to treat the `#Вставка`/`#КонецВставки` boundary as breaking its control-flow graph, even though the platform executes both sides as one plain statement sequence at runtime. `bsl_diagnostics(include_unused=true)` instead only produces a `BSL-DEAD` "unused function" hit on these cases — a different and misleading signal, since the routine is not unused, it is a directive-bound interceptor (a false-positive class already documented in `SKILL.md`'s `onec-hbk-bsl-*` section).

This is exactly the highest-value case for this skill — typical behaviour silently shadowed by an extension — so this tool covers a real gap `BSL051` does not. Use `BSL051` as a fast first pass (when the MCP server is available) and this tool as the reliable check for the `#Вставка`-adjacent case specifically.

## Provenance

Built and validated while auditing a real-world 1C configuration extension — **five** distinct real findings from that session, confirmed by reading the source. No specifics identifying that extension are reproduced here, to avoid disclosing details of a third party's codebase; the bug shapes themselves are described generically:

1. A wholly-own `&После` interceptor whose first real statements were a debug comment followed by a bare `Возврат;`, making roughly 30 lines of logging code that followed completely unreachable — no `#Вставка` markers involved.
2. An `&ИзменениеИКонтроль` insertion whose entire inserted block was `Возврат Истина;`, unconditionally overriding a typical feature-option check that followed it — the typical check never ran again, for any caller, regardless of the actual constant/option value.
3. An `&ИзменениеИКонтроль` insertion that set up one RIB registration rule then unconditionally returned, leaving a second typical registration rule (for a different dimension) permanently unreachable — the extension's rule fully replaced rather than supplemented the typical one.
4. A wholly-own function ending in an unconditional `Возврат <локальная переменная>;` followed by several dozen more lines of table-document construction code that could never run — apparent leftover from a superseded implementation.
5. An `&ИзменениеИКонтроль` insertion that called a sibling "modified" routine and then unconditionally returned, skipping the routine's own original setup code that followed — a comment directly above read "for checking the correctness of ..." the sibling routine, suggesting a debug/verification bypass left in place.

Two of these (1 and 4) had no `#Вставка` markers and were correctly caught by `BSL051`; the other three (2, 3, 5) all had `#Вставка`/`#КонецВставки` markers and were **missed entirely** by `BSL051` — this is the empirical basis for the "Relationship to `BSL051`" section above. On the three missed cases, `bsl_diagnostics(include_unused=true)` fired only a `BSL-DEAD` "unused function" hit on each — misleading, since all three are directive-bound interceptors that are genuinely called.
