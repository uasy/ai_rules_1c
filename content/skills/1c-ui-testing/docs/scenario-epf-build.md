# Building a scenario data processor

A scenario for the test manager is an ordinary EPF with one managed form, and it is built by the
**`1c-metadata-manage` skill** — `1c-epf-scaffold` → `1c-form-scaffold` → `1c-form-compile` →
`1c-epf-validate` → `1c-epf-build`. Exact invocations live in that skill
([epf-manage.md](../../1c-metadata-manage/docs/epf-manage.md),
[form-manage.md](../../1c-metadata-manage/docs/form-manage.md)); they are not repeated here.

**Do not hand-write the XML, and do not copy an existing scenario.** A copied directory carries the
original's object name and identities, which then have to be repaired in several places at once —
longer than scaffolding from scratch, and what gets missed either breaks the build or survives as a
silent duplicate. The tools set all of it correctly.

What to ask the skill for:

- an external data processor in the project's scenario directory, named after what it accepts;
- one managed form, set as the default form;
- the form's `OnOpen` event declared, handler `ПриОткрытии`;
- the main attribute `Объект` of type `ExternalDataProcessorObject.<Name>`.

## Declaring the handlers

This is the step the scaffold does not do for you, and the one that fails silently. `1c-form-scaffold`
generates `Form.xml` **without** an `<Events>` block, so the scenario would never start. Declare
events through the `events` key of the `1c-form-compile` DSL — never by hand-editing `Form.xml`.

**Input** — the DSL, a JSON file passed as `-JsonPath`:

```json
{
  "title": "Приёмка чего-то",
  "events": { "OnOpen": "ПриОткрытии" },
  "attributes": [
    { "name": "Объект", "type": "ExternalDataProcessorObject.УИПриемкаЧегоТо", "main": true }
  ]
}
```

**Output** — what the compiler writes into `Form.xml`; check it is there before building:

```xml
<Events>
  <Event name="OnOpen">ПриОткрытии</Event>
</Events>
```

`form-compile` rewrites `Form.xml` whole, so the DSL must restate the main attribute — omit it and
the form loses its object attribute.

Every other handler goes in the same way — `OnCreateAtServer` on the form, element events under the
element's own `events` key.

## One thing the linter catches late

**No em dash inside string literals.** `"… не выполнена — " + ОписаниеОшибки()` is reported as
`BSL204 Недопустимый символ` — an error, not a warning, and it fails the module check after the
scenario is otherwise finished. Use a hyphen in literals; comments are fine.

Everything else about the module — skeleton, protocol rules, the tested-object API and its traps —
is `SKILL.md → Step 3`. Running it — `SKILL.md → Step 1`, `Step 2` and `Runner`.

## Build checklist

- [ ] Scaffolded through `1c-metadata-manage`, not copied and not hand-written
- [ ] `<Events>` present in `Form.xml` for every handler the module defines
- [ ] Main attribute restated in the DSL and present after `form-compile`
- [ ] `1c-epf-validate` clean, module passes BSL checks
- [ ] EPF rebuilt after the last edit — the runner uses the built file, not the sources
