# 1c-form-basediff

What the developer changed in a form of an adopted object: the live form against the `<BaseForm>` snapshot stored in the same `Form.xml`. Answers `markup-changed` or `markup-unchanged` per form and names every element and property behind the verdict.

## Why this exists

The file holds two states of one form: the snapshot the developer started from and the form as it is now, in the same serialisation. Their difference is exactly the edit. A text diff of the two needs six rules to get right: indentation, the wrapper lines, a «noise» class, reading order, no name-set comparison, a control element. Every audit run implemented them anew and got different line counts for the same verdicts. Each rule, when missed, broke the answer. The costliest miss in the skill's history happened here: an exchange-plan node form was twice called an empty copy and a removal candidate. Its one edit, a removed `ReadOnly` on two message-number fields, is the only manual way out of a RIB packet-number desynchronisation.

This tool compares the two sides as trees, so those rules are built in or no longer needed.

## What it compares

| Part of the form | Matched by | Reported |
|---|---|---|
| Layout elements under `ChildItems`, at any depth | name | own elements, snapshot elements missing from the form, lost / added / changed properties, a move to another parent, a changed order of shared siblings |
| A named sub-element: context menu, command bar, extended tooltip | its owner, then its own properties | the property path, e.g. `Список.ContextMenu: -Autofill` |
| Form attributes, commands, parameters | name | own items, property changes, items missing from the form |
| The form's own properties | tag | lost / added / changed |
| `Events` and a command's `Action` | as properties | apart, as **handler bindings**: they wire module code to the form and do not change its markup |

Ignored, and nothing else: element `id` values, whitespace and indentation, namespace declarations. Nested `ChildItems` are left out of a property's value at any depth. So a button added to a command bar is reported once, as an own element, and not again as a change of the bar.

**Lost properties come first.** A property the snapshot has and the form lacks is the edit that matters most and the easiest to miss. Each lost property is checked against a **control element**: another element of the same file keeping the same property with the same value on both sides. `kept by X -> deliberate edit` means a serialisation quirk would have dropped it everywhere, so the loss is intended. `no other element keeps it` means only that the check could not decide.

**The verdict ignores handler bindings.** A form whose module alone changed stays `markup-unchanged`, even when the extension's `Form.xml` binds `callType` events. Read the bindings in their own section.

## Usage

```
python3 content/skills/1c-extension-analysis/tools/1c-form-basediff/scripts/form-basediff.py \
    -ExtensionPath <path> [-Object "<Тип.Имя>[.<Форма>]" | -Object "CommonForm.<Имя>"] [-Summary]
```

- Without `-Object` it walks every `Ext/Form.xml` of the extension, common forms included. Do not glob `*/Forms/*`: that misses common forms.
- `-Summary` prints one line per form: the verdict, the number of changes and the touched names. On the reference extension it fits on one screen.
- A form with no `<BaseForm>` is an own form. It prints `no-snapshot` and stays out of the counts, because «what differs from stock» does not apply to it.
- The last line states the counts and the scope:
  `=== 6 form(s): 4 markup-changed, 2 markup-unchanged; 15 without a snapshot, not counted [scope: live form vs its own <BaseForm> snapshot] ===`

Standard library only, no `lxml` needed.

## Not offered: a comparison with the base configuration's form

The base configuration's current `Form.xml` is a third point and answers a different question: how far the snapshot drifted from today's typical form. A comparison with it was built and then removed, because the answer is mostly serialisation. The snapshot omits form attributes, titles and data paths and names sub-elements differently. On the reference extension, a form whose snapshot matches the extension's version gave 59 «differences» by name alone and 215 by property. When drift matters, read the base form by hand next to the snapshot.

## Known gaps

- Elements are matched by name. An element renamed between snapshot and form is reported as one missing and one own element.
- The control-element check looks for an exact property and value. It finds nothing for a property that only one element ever carries, and then cannot decide either way.
- It reads managed forms. An ordinary form is `Form.bin`; use `unpack_ordinary_form` (skill `v8unpack-cf`).

## Provenance

Built after ten runs of this skill on one extension. Proposal: `change-request-extension-analysis-tools.md` at the project root. Acceptance on that extension: exactly two forms `markup-unchanged`; the node form `markup-changed` with exactly two lost `ReadOnly`, kept by a third element; the common print form losing `Representation = Compact`. One run had found three real edits of a document form among 462 live-side lines: `Group`, `HeightInTableRows` and `VerticalStretch`. The tool reports all three among that form's other changes, the lost ones at the top.
