# 1c-insert-blocks

Dumps every `#Вставка … #КонецВставки` block of an extension, and every `#Удаление … #КонецУдаления` block, with the `&ИзменениеИКонтроль` routine that holds it. For that annotation the routine body is a verbatim copy of the typical one, and only these blocks are the extension's own change. So `SKILL.md` step 1 fills the registry's «what it writes / what it reads» column from them, not from the whole body.

## Why this exists

- **The markers are bare lines**, `#Вставка`, not `// #Вставка`. A scan written for the commented spelling returns zero blocks, which reads as «the extension inserts nothing». No other wrong answer misleads as much.
- **Dump all blocks before grouping, not on demand.** Empty 3-byte modules and a print form commented out in full make a document look abandoned. The refutation can sit in an author's comment inside an insert block of a *different* object — for instance, that a common method is used to change the form without adopting it into the extension. Reading blocks per object already classified never reaches that comment, and the report goes out with advice to delete a live object; a full dump of all blocks is searchable for it.

The block and interceptor parsing is `registry-builder`'s, loaded from this skill. The two tools cannot disagree on what a block is.

## Usage

```
python3 content/skills/1c-extension-analysis/tools/1c-insert-blocks/scripts/insert-blocks.py \
    -ExtensionPath <path> [-ConfigPath <base config path>] [-Object "<Тип.Имя>"] [-Summary] > blocks.txt
```

- Without `-Summary`, every block is printed with its `file:start-end`, the holding annotation, the interceptor routine and the intercepted one, and the numbered lines of its body. The full output is large. Redirect it to a file and search the file. Piping it into `head` truncates it silently.
- `-Summary` prints only the flagged items and the counters.
- `-ConfigPath` checks the base module behind every `&ИзменениеИКонтроль` without a block. If the base module is absent, there is nothing to change and nothing hidden. If it declares the routine, compare the bodies. Without it, the note says the check was not made.

## Output

Every run ends with two lists and one counter line:

- **flagged blocks**: an insert block with no executable line, comments only, which changes the conclusion that the extension «changes nothing» there; and a block outside `&ИзменениеИКонтроль`. Under `&Перед` / `&После` / `&Вместо` the whole body is own code and the markers are inert, usually a trace of copying from a typical routine.
- **`&ИзменениеИКонтроль` routines with no block**.
- `=== N insert block(s), D delete block(s) in F file(s): E without executable lines, O outside &ИзменениеИКонтроль; M &ИзменениеИКонтроль, K without a block [scope: …] ===`

**Zero blocks is not an error by itself.** With `&ИзменениеИКонтроль` routines present and no block found, the tool prints `PARSE FAILURE` to stderr and exits with code 2. With neither, the extension is built from `&Перед` / `&После` / `&Вместо` and own modules, and zero is the right answer. The tool says so.

## Cross-check through the graph

Where `1c-graph-metadata-mcp` is exposed, `search_code(query="КонецВставки", search_type="fulltext", project_name="<extension layer>")` returns one hit per routine holding a block. Its `total` must equal the number of distinct routines this tool prints a block for; both count a routine holding inert markers under `&После`. A mismatch means one side missed a module. The graph does not index a common form's module, so a block there is visible only to this tool.

## Known gaps

- Markers are matched as whole lines, as in `registry-builder`. A marker followed by a comment on the same line is not recognised.
- A `#Удаление` block holds typical code the extension removes. It has no «executable lines» test and needs reading against the base routine.

## Provenance

Accepted against an extension holding both edge cases: an `&ИзменениеИКонтроль` without a block, on a record-set module the base object does not have, and blocks inside an `&После` routine, which a block count alone attributes to an `&ИзменениеИКонтроль`. `tools/tests/extension-tools-regression.py` (ruleset source) reproduces both, plus the commented-marker parse failure.
