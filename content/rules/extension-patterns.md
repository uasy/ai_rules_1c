---
description: 1C configuration extension (CFE) patterns — interceptor types (`&Перед` / `&После` / `&Вместо` / `&ИзменениеИКонтроль`), `ПродолжитьВызов` rules, change markers, adopted-object constraints. Load when writing or reviewing extension code.
alwaysApply: false
category: architecture
---

# 1C Extension Patterns (CFE)

BSL patterns for working with 1C configuration extensions.

Applies to: extension code (`**/Extensions/**/*.bsl` and similar).

Background reference: `dev-standards-architecture.md §2` (Extensions) — modification priority, directives, placement rules. This file is the **practical** companion: interceptor types, `ПродолжитьВызов` semantics, markers, and adopted-object constraints.

> **Naming convention used in examples.** Below, `Расш1_` / `МоеРасш_` denotes the **extension's own short alias** (set in the extension's properties — typically the `Имя` of the extension or an explicit alias), **not** `{PREFIX}` from `.dev.env`. `{PREFIX}` applies to new metadata objects and attributes; the extension alias applies to procedure / function names introduced by the extension and prevents name collisions between extensions. The two are independent: an extension can both add a new attribute `{PREFIX}Признак` to a typical object and define an interceptor procedure `Расш1_ПриЗаписи` in the same module.
>
> The alias itself MUST NOT contain the letter «ё» — see `dev-standards-code-style.md → Typography`. Use `МоеРасш_`, `Расш1_`, `MyExt_` or any «ё»-free form.

---

## Interceptor types

Platform reference: "Аннотации" (extension annotations) and "Инструкции препроцессора" (preprocessor instructions) in the syntax assistant. For **procedures** all four annotations are valid (and `&Перед` + `&После` may be combined on the same method); for **functions** only `&Вместо` or `&ИзменениеИКонтроль` are valid — a function has a return value, so before/after alone cannot supply one.

| Directive | Type | When to use |
|-----------|------|-------------|
| `&Перед("ИмяМетода")` | Before | Code before the original method; the platform calls the original automatically afterwards |
| `&После("ИмяМетода")` | After | Code after the original method; the original has already run |
| `&Вместо("ИмяМетода")` | InsteadOf | Full replacement written from scratch; optionally delegates to the original via `ПродолжитьВызов()` |
| `&ИзменениеИКонтроль("ИмяМетода")` | ChangeAndValidate | Surgical edit of the typical body: the full typical text is copied in verbatim, then edited via `#Вставка`/`#Удаление`; the platform validates that everything outside those markers still matches the current typical implementation |

### Before / After — simple interceptors

```bsl
&НаСервере
&Перед("ПриЗаписи")
Процедура Расш1_ПриЗаписи()
    // Runs BEFORE the original ПриЗаписи
КонецПроцедуры

&НаСервере
&После("ПриЗаписи")
Процедура Расш1_ПослеЗаписи()
    // Runs AFTER the original ПриЗаписи
КонецПроцедуры
```

### Вместо — full replacement, written from scratch

```bsl
&НаСервере
&Вместо("ОбработкаПроведения")
Процедура Расш1_ОбработкаПроведения(Отказ, РежимПроведения)
    // own logic before the original, if needed

    ПродолжитьВызов(Отказ, РежимПроведения); // optional — omit entirely to fully replace behavior

    // own logic after the original, if needed
КонецПроцедуры
```

The platform does **not** verify this body against the current typical implementation. If the typical procedure changes in a later base-configuration update, this replacement keeps applying with the old logic — silently, with no error at startup.

### ИзменениеИКонтроль — surgical edit of a copied body

```bsl
&НаСервере
&ИзменениеИКонтроль("ОбработкаЗаполнения")
Процедура Расш1_ОбработкаЗаполнения(ДанныеЗаполнения, СтандартнаяОбработка)
    // ... unchanged typical code, copied verbatim ...

    #Удаление
    // original line(s) being replaced — not executed, kept only for the platform's text-match check
    #КонецУдаления

    #Вставка
    // new code
    #КонецВставки

    // ... more unchanged typical code, copied verbatim ...
КонецПроцедуры
```

No `ПродолжитьВызов()` call here — the typical body is already inline. The platform requires every line outside `#Вставка`/`#Удаление` to match the **current** typical implementation exactly; if the base configuration changes that procedure, the extension **fails to apply** (an explicit error at startup) — it does not silently diverge.

---

## ПродолжитьВызов() rules

`ПродолжитьВызов()` is only a valid call inside a `&Вместо`-annotated method — it has no meaning and is not available under `&Перед`, `&После`, or `&ИзменениеИКонтроль`.

- `&Перед` — the platform calls the typical method automatically after the interceptor finishes. There is no `ПродолжитьВызов()` involved at all; nothing to call manually.
- `&После` — the typical method has already run before the interceptor starts. Again, no `ПродолжитьВызов()` involved.
- `&Вместо` — `ПродолжитьВызов()` is the *only* way to invoke the typical implementation from inside the replacement. It is optional: call it (once) to wrap the original with before/after logic, or omit it entirely for a full behavioral replacement. The platform does **not** verify this body against the current typical implementation — a later base-configuration change to the typical method goes undetected; the extension keeps applying with the old logic, silently.
- `&ИзменениеИКонтроль` — `ПродолжитьВызов()` is **not used and not available**: the typical body is already copied verbatim into the method (see markers below). Correctness is enforced structurally instead — every line outside `#Вставка`/`#Удаление` must match the *current* typical implementation exactly, or the extension **fails to apply** (an explicit error at startup, not a silent divergence).

---

## Change markers

Markers are **required** inside `&ИзменениеИКонтроль` to track changes:

| Marker | Purpose |
|--------|---------|
| `#Вставка` / `#КонецВставки` | New code added by the extension |
| `#Удаление` / `#КонецУдаления` | Original code that was replaced |

Markers preserve diff/merge semantics when the base configuration is updated and the extension needs to be re-borrowed.

---

## Constraints on adopted (borrowed) objects

- An adopted object (`ObjectBelonging=Adopted`) is **not a copy** — it is a reference to a base-configuration object brought into the extension's scope so that the extension can attach interceptors and add its own attributes / tabular sections / form elements. The original definition still lives in the base configuration; on a base-configuration update the adopted object is automatically re-read, and the extension is re-applied on top of it.
- You **cannot** delete existing attributes / tabular sections of an adopted object — they belong to the base configuration.
- You **can** add your own attributes / tabular sections (with `{PREFIX}` from `.dev.env`).
- Modules of adopted objects — interceptors only (`&Перед` / `&После` / `&Вместо` / `&ИзменениеИКонтроль`), no direct edits to the original procedure body.
- Forms of adopted objects — you can add elements, you cannot delete existing ones.

---

## Anti-patterns

### Direct edit of an adopted module

```bsl
// WRONG: editing original code in place
Процедура ПриЗаписи()
    // changed code...
КонецПроцедуры

// RIGHT: interceptor
&Перед("ПриЗаписи")
Процедура Расш1_ПриЗаписи()
    // additional code
КонецПроцедуры
```

### Forgotten ПродолжитьВызов (under `&Вместо`)

```bsl
// DANGEROUS: original method will not execute, and the platform will not warn about it!
&Вместо("ОбработкаПроведения")
Процедура Расш1_ОбработкаПроведения(Отказ, РежимПроведения)
    // own code...
    // FORGOT: ПродолжитьВызов(Отказ, РежимПроведения);
КонецПроцедуры
```

Note the different failure mode under `&ИзменениеИКонтроль`: there `ПродолжитьВызов()` is never used at all (the typical body is already copied inline), so there is nothing to "forget" — instead, forgetting to keep the untouched text identical to the current typical implementation makes the extension **fail to apply**, loudly, rather than silently skip the original.

### No prefix in extension method names

```bsl
// Bad: name conflict with other extensions
Процедура ДополнительнаяПроверка()

// Good: extension prefix
Процедура МоеРасш_ДополнительнаяПроверка()
```

---

## Extension purpose tag

Set the `Purpose` (Назначение) of the extension in its properties:

| Type | Purpose | When to use |
|------|---------|-------------|
| Patch | `Patch` | Minimal changes, interceptors only |
| Customization | `Customization` | Attributes, forms, modules |
| AddOn | `AddOn` | Full new functionality |

The `Purpose` value affects update behaviour and the way the platform reapplies the extension after a base-configuration update.
