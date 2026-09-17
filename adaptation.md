# Адаптация `dev` относительно апстрима

Ветка `dev` — это апстрим [`comol/ai_rules_1c`](https://github.com/comol/ai_rules_1c) (`main`) плюс изменения, перечисленные ниже. Файл нужен для синхронизаций: всё, чем `dev` отличается от апстрима, должно быть записано здесь вместе с причиной. Отличие без записи считается ошибкой синхронизации и приводится к апстриму.

## Принципы синхронизации

1. **Апстрим — канон для своих файлов.** При расхождении в файле апстрима берётся версия апстрима, если отличие не записано в этом файле.
2. **Синхронизация — merge `upstream/main` в `dev`.** «`main` / `master` обновлён» означает `upstream/main`.
3. **Наши добавления в файлы апстрима — отдельными абзацами**, а не правкой его предложений. Правка внутри предложения апстрима даёт конфликт при каждой его правке этого предложения; отдельный абзац сливается чисто.
4. **Ревизия пар после каждой синхронизации.** Для каждого `.ps1` или `.py`, изменённого апстримом или у нас, проводится полная ревизия второй половины пары — в обе стороны. Сверка идёт по содержимому: гейты `-DryRun`/`-Force`, защита поддержки, чтение `.dev.env`, способ записи XML, путь к валидатору. Версия в шапке скрипта при локальных правках не меняется и паритет не доказывает.
5. **`.ps1` и остальные файлы инструментов апстрима — как в `main`.** Наши исправления живут в Python-портах, помечаются в коде комментарием `# Local:` и перечисляются здесь и в `content/skills/1c-metadata-manage/NOTICE.md`.
6. **Ошибки апстрима, исправленные у нас, — кандидаты в support.** Когда апстрим исправит ошибку, наше отличие удаляется.
7. **Инструменты сверх апстрима оставляются только по явному решению** и перечисляются здесь. Если у апстрима появился аналог, наш вариант приводится к нему.
8. **MCP-серверы: канон — документация апстрима** `content/skills/mcp-1c-tools/docs/`. В наших навыках — только маршруты использования (какой инструмент отвечает на какой вопрос и что не годится); настройка сервера, имена аргументов и флаги развёртывания — у апстрима.
9. **Навыки описывают только целевое поведение**: без истории проверок, дат сборок и условий совместимости. Провенанс инструмента — в его `docs/`.
10. **Правки навыков из рабочих проектов.** Рабочий проект несёт установленную, как правило более старую, версию навыков; правки сверяются с версией установки. Сначала перенос как есть отдельным коммитом, затем редактура по этим принципам.
11. **`AGENTS.md` не дополняется маршрутами наших навыков** — хост находит навыки по `description` в `SKILL.md`. После синхронизации размер `AGENTS.md` проверяется на лимит валидатора (16384 байт): CI для `dev` его не проверяет.
12. **История `dev` переписывается только диапазоном `dev ^upstream/main ^origin/dev`.** Иначе меняются хэши коммитов апстрима, включая подписанные merge-коммиты, и следующая синхронизация приносит дубли.
13. **Документы перед коммитом проверяются навыком `audit-review`.**

## Чек-лист после синхронизации

- [ ] `git diff --name-status upstream/main dev` — каждый путь покрыт этим файлом.
- [ ] Ревизия пар по изменённым `.ps1`/`.py` (принцип 4).
- [ ] `python3 -B tools/tests/python-ports-regression.py --python-only` — без падений.
- [ ] Размер `AGENTS.md` не больше 16384 байт.

## A. Собственные навыки и агенты

- `content/skills/1c-extension-analysis/` — анализ расширения конфигурации: зачем оно изменяет типовую, реестр изменений, отчёт для заказчика.
- `content/skills/1c-ui-testing/` — UI-тестирование через тестовый клиент и менеджер тестирования платформы.
- `content/skills/1c-test-debug/` — проверки на тестовой базе без человека у экрана: код и журнал регистрации через отладочное расширение, HTTP-вызовы с учётными данными из `.dev.env`, `/CheckModules`, публикация на Linux. Раннер `1c-ui-testing` вызывает его `ib-errors.py` для диагностики.
- `content/skills/openspec-agents/` — порядок работы над изменением OpenSpec с агентами (`review.md`, `test-plan.md`, `verify.md`, дерево `openspec/tests/`) и неинтерактивный запуск агента через `claude -p`.
- `content/skills/audit-review/` — проверка содержимого перед коммитом: утечки контекста и соответствие назначению файла.
- `content/agents/extension-analyst.md` — субагент полного анализа расширения; зарегистрирован в `content/rules/subagents.md` (каталог агентов, счётчик агентов, read-only агенты, тир `coding`).
- `content/agents/openspec-tester.md`, `content/agents/openspec-implementer.md` — агенты навыка `openspec-agents`: тесты по спецификации и проверка, реализация задач изменения. Зарегистрированы в `content/rules/subagents.md` (каталог, счётчик, `allowParallel: false`, тир `coding`); владение артефактами — отдельным абзацем после таблицы в `content/rules/sdd-integrations.md`.

## B. Python-рантайм `1c-metadata-manage`

Апстрим поставляет шесть Python-точек входа. `dev` поставляет Python-двойник почти для каждого инструмента, чтобы навык работал на Linux / macOS без PowerShell.

- **Порты:** `content/skills/1c-metadata-manage/tools/*/scripts/*.py`. Не портированы `web-info`, `web-stop`, `web-unpublish` из `tools/1c-web-ops/` и `tools/_common/DevEnv.ps1` (его Python-аналог — `dev_env.py`).
- **Общие помощники:** `tools/_common/Invoke-1CEdit.py`, `tools/_common/MetadataAddress.py`, `tools/_common/meta_dsl.py`, `tools/_common/platform_args.py`, `tools/_shared/support_guard.py`, `tools/_shared/xml_eol.py`.
- **Документация:** `content/skills/1c-metadata-manage/SKILL.md` (уровни Python-портов, Python-обёртка preview), `content/skills/1c-metadata-manage/NOTICE.md` (локальные отличия портов), `content/skills/1c-metadata-manage/docs/CHANGELOG.md` (записи об изменениях портов), `content/skills/1c-metadata-manage/docs/edit-preview.md` (Python-обёртка и та же политика preview).
- **Тесты:** `tools/tests/python-ports-regression.py` и фикстура `tools/tests/fixtures/epf-with-template/`.

### Отличия портов от поведения апстрима

| Порт | Отличие | Почему |
|---|---|---|
| `cf-edit.py`, `cfe-borrow.py`, `subsystem-compile.py`, `subsystem-edit.py`, `interface-edit.py`, `form-edit.py`, `add-help.py`, `add-template.py` | При перезаписи существующего XML сохраняется стиль строк файла; вставленные отступы не записываются как `&#13;` (`xml_eol.py`) | `lxml` при разборе приводит CRLF к LF и сериализует CR в тексте как `&#13;` |
| `form-compile.py` | Регистрация формы в объекте сохраняет стиль строк файла объекта | Чтение в текстовом режиме приводит CRLF к LF |
| `cf-edit.py`, `interface-edit.py`, `subsystem-compile.py`, `subsystem-edit.py` | Автопроверка вызывает соседний валидатор | Путь `../../<валидатор>/scripts/…`, который использует апстрим, в этой раскладке не существует — проверка молча пропускается. Кандидат в support |
| `add-template.py` | `-ObjectName` принимает путь к XML объекта | Так же, как `add-template.ps1` апстрима |
| `remove-template.py` | Гейт `-DryRun` / `-Force`, предварительный разбор, атомарная запись корневого XML | Так же, как `remove-template.ps1` апстрима |
| `meta-edit.py` | Отказ на `add-template` называет и `add-template.py` | У апстрима сказано, что Python-версии нет; `dev` её поставляет |
| `support_guard.py` | Режим защиты берётся только из `SUPPORT_GUARD` в `.dev.env`, без обращения к `.v8-project.json` | `.dev.env` — единственный источник рабочих параметров проекта |
| `web-publish.py` | Linux / macOS: модуль `wsap24.so`, Apache не скачивается; `bin/httpd` — сборка с `--prefix` или ссылка на пакетный `apache2`, запуск с `-d`/`-f`, свой сервер узнаётся по командной строке | У апстрима нет Python-версии; раскладка Apache на Linux иная |
| `web-publish.py` | В `default.vrd` задано `publishExtensionsByDefault="true"` | Без атрибута HTTP-сервисы расширений отвечают 404. В `web-publish.ps1` та же ошибка — кандидат в support |
| `db-run.py` | Флаги `-Out` и `-Wait` | В пакетном режиме ошибки запуска видны только в `/Out`; `-Wait` возвращает код завершения клиента |
| `content/skills/img-grid-analysis/scripts/overlay-grid.py` | Отклоняет `--cols <= 0` и `--rows < 0`, строит минимум одну строку сетки, выводит UTF-8 | Исправление ошибок; кандидат в support |

Каждое отличие отмечено в коде комментарием `# Local:` или заголовком `Deviation`.

## C. Собственные инструменты сверх апстрима

- `tools/1c-cfe-manage/scripts/cfe-build.ps1`, `cfe-build.py` и раздел о сборке в `content/skills/1c-metadata-manage/docs/cfe-manage.md` — сборка `.cfe` из XML через одноразовую базу. У апстрима то же делается цепочкой `db-ops` вручную.
- `tools/1c-form-decompile/` (`form-decompile.ps1`, `form-decompile.py`) и раздел «Decompile» в `content/skills/1c-metadata-manage/docs/form-manage.md` — черновик DSL из существующего `Form.xml`. Аналога у апстрима нет.

## D. Документация, точнее апстрима

Скрипты, которые описывают эти документы, совпадают с `main`; расходится только описание. Оставлено, кандидаты в support.

| Документ | Отличие |
|---|---|
| `content/skills/1c-metadata-manage/docs/web-manage.md` | Не описывает `web-stop -Start` / `-Force`: в `web-stop.ps1` этих параметров нет |
| `content/skills/1c-metadata-manage/docs/cf-manage.md` | Описывает параметры `cf-init` (`-Synonym`, `-Version` и др.), которые есть в скрипте |
| `content/skills/1c-metadata-manage/docs/template-manage.md` | Описывает `-SetMainSKD` и тип `DataCompositionSchema` у `add-template` |
| `content/skills/1c-metadata-manage/docs/skd-manage.md`, `content/skills/1c-metadata-manage/tools/1c-skd-info/modes-reference.md` | Описывают `skd-info -Raw` |
| `content/skills/1c-metadata-manage/docs/meta-manage.md` | Раздел о составных типах атрибутов |

## Этот файл

- `adaptation.md` — перечень отличий и принципы синхронизации.
