# 1c-insert-blocks

Dumps every `#Вставка … #КонецВставки` block of an extension, and every `#Удаление … #КонецУдаления` block, with the `&ИзменениеИКонтроль` routine that holds it. For that annotation the routine body is a verbatim copy of the typical one, and only these blocks are the extension's own change. So `SKILL.md` step 1 fills the registry's «what it writes / what it reads» column from them, not from the whole body.

## Why this exists

- **The markers are bare lines**, `#Вставка`, not `// #Вставка`. A scan written for the commented spelling returns zero blocks, which reads as «the extension inserts nothing». No other wrong answer misleads as much.
- **Dump all blocks before grouping, not on demand.** One run wrote with confidence that a document was abandoned. Two signals backed it: two 3-byte modules and 175 commented-out lines of a print form. A comment in an insert block of a *different* object refuted it: «будем использовать этот метод для возможности внесения изменений в форму без её включения в расширение». The analyst found it by chance, while searching a full dump of all blocks for something else. Reading blocks per object already classified would have sent the report out with advice to delete a live object.

The block and interceptor parsing is `registry-builder`'s, loaded from this skill. The two tools cannot disagree on what a block is.

## Usage

```
python3 content/skills/1c-extension-analysis/tools/1c-insert-blocks/scripts/insert-blocks.py \
    -ExtensionPath <path> [-ConfigPath <base config path>] [-Object "<Тип.Имя>"] [-Summary] > blocks.txt
```

- Without `-Summary`, every block is printed with its `file:start-end`, the holding annotation, the interceptor routine and the intercepted one, and the numbered lines of its body. The full output is about 100 KB on the reference extension. Redirect it to a file and search the file. Piping it into `head` truncates it silently.
- `-Summary` prints only the flagged items and the counters.
- `-ConfigPath` checks the base module behind every `&ИзменениеИКонтроль` without a block. If the base module is absent, there is nothing to change and nothing hidden. If it declares the routine, compare the bodies. Without it, the note says the check was not made.

## Output

Every run ends with two lists and one counter line:

- **flagged blocks**: an insert block with no executable line, comments only, which changes the conclusion that the extension «changes nothing» there; and a block outside `&ИзменениеИКонтроль`. Under `&Перед` / `&После` / `&Вместо` the whole body is own code and the markers are inert, usually a trace of copying from a typical routine.
- **`&ИзменениеИКонтроль` routines with no block**.
- `=== 74 insert block(s), 1 delete block(s) in 40 file(s): 4 without executable lines, 2 outside &ИзменениеИКонтроль; 50 &ИзменениеИКонтроль, 1 without a block [scope: …] ===`

**Zero blocks is not an error by itself.** With `&ИзменениеИКонтроль` routines present and no block found, the tool prints `PARSE FAILURE` to stderr and exits with code 2. With neither, the extension is built from `&Перед` / `&После` / `&Вместо` and own modules, and zero is the right answer. The tool says so.

## Cross-check through the graph

Where `1c-graph-metadata-mcp` is exposed, `search_code(query="КонецВставки", search_type="fulltext", project_name="<extension layer>")` returns one hit per routine holding a block. Its `total` must equal the number of distinct routines this tool prints a block for. On the reference extension both give 50: 49 `&ИзменениеИКонтроль` routines with a block and one `&После` routine with inert markers. A mismatch means one side missed a module. The graph does not index a common form's module, so a block there is visible only to this tool.

## Known gaps

- Markers are matched as whole lines, as in `registry-builder`. A marker followed by a comment on the same line is not recognised.
- A `#Удаление` block holds typical code the extension removes. It has no «executable lines» test and needs reading against the base routine.

## Provenance

Proposal: `change-request-extension-analysis-tools.md` at the project root. Acceptance on the reference extension: 74 insert blocks in 40 files; exactly one `&ИзменениеИКонтроль` without a block, on a record-set module the base object does not have. The first run also found two blocks inside an `&После` routine, which a block count alone would attribute to an `&ИзменениеИКонтроль`.
