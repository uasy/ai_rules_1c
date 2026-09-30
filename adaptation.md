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
11. **`AGENTS.md` не дополняется маршрутами наших навыков** — хост находит навыки по `description` в `SKILL.md`. После синхронизации бюджеты `tools/validate-rules.ps1` проверяются вручную: CI для `dev` их не проверяет. Это размер `AGENTS.md`, отдельного правила, набора полного цикла и стартового набора субагента (`AGENTS.md` + `subagent-core.md` + промпт агента), длина описаний навыков, агентов и правил; пределы — в параметрах валидатора.
    Исключение: набор полного цикла (`-HotPathMaxBytes`) превышен на размер абзаца «Without `1c-data-mcp`» в Gate 3a (`content/rules/verification-gates.md`, сейчас 360 байт). Почему: в рабочих проектах нет `1c-data-mcp`, и без абзаца Gate 3a не выполняется никогда; вынос в навык ослабил бы маршрут, а цена — около 90 токенов на задачу. Допустимое превышение — ровно этот абзац; всё сверх — ошибка. Апстрим опускает этот лимит по мере сокращения набора, поэтому превышение пересчитывается при каждой синхронизации.
12. **История `dev` переписывается только диапазоном `dev ^upstream/main ^origin/dev`.** Иначе меняются хэши коммитов апстрима, включая подписанные merge-коммиты, и следующая синхронизация приносит дубли.
13. **Документы перед коммитом проверяются навыком `audit-review`.**

## Чек-лист после синхронизации

- [ ] `git diff --name-status upstream/main dev` — каждый путь покрыт этим файлом.
- [ ] Ревизия пар по изменённым `.ps1`/`.py` (принцип 4).
- [ ] `python3 -B tools/tests/python-ports-regression.py --python-only` и `python3 -B tools/tests/web-python-regression.py` — без падений.
- [ ] Бюджеты валидатора (принцип 11) не превышены, кроме исключения принципа 11. С `pwsh`: `tools/validate-rules.ps1 -HotPathMaxBytes <лимит апстрима + размер абзаца Gate 3a>`.

## Обновление правил в рабочих проектах

Правила ставятся по протоколу `AGENT-INSTALL.md`. Без `pwsh` его выполняет агент с пониманием контекста: решения по каждому сомнительному файлу принимаются по содержимому, а не по флагу. Механику — копирование, преобразование frontmatter, пути, хэши, манифест — выполняет одноразовый код в scratchpad; в репозиторий он не кладётся (третий установщик рядом с `install.ps1` и протоколом).

1. **Сначала `dev`.** Синхронизация с апстримом и аудит завершены. Правки навыков, сделанные в проекте, перенесены в `dev` до обновления (принцип 10) — иначе обновление их заморозит или затрёт.
2. **План, без записи на диск.** По каждому проекту: что добавится, обновится, удалится, останется нетронутым и что сомнительно — с причиной. Сомнительное решает пользователь.
3. **Применение — только после согласия с планом.** Перед ним архив `.claude/`, `.codex/`, `AGENTS.md`, `CLAUDE.md`, `.ai-rules.json` и затронутых файлов вне проекта (`~/.codex/prompts/`). Код выполняет утверждённый план и ничего не решает сам.
4. **Проверка.** Каждый файл — против источника с ожидаемым преобразованием, манифест — против диска, ссылки в установленных копиях, отсутствие `__pycache__`, проектные файлы не тронуты. Расхождения — в отчёт до работы в проекте.

Как поступать с файлами:

- **Управляемый файл изменён на месте** (хэш ≠ `installedHash`): выяснить, что в правке. Перенесена в `dev` — взять из `dev`; не перенесена — сначала перенос. Молча помечать `userModified` нельзя: файл перестанет обновляться, а его копия для другого клиента разойдётся с ним.
- **Проектные файлы с `userModified`** (`.mcp.json`, `.codex/config.toml`, `openspec/project.md`, `USER-RULES.md`, `memory.md`, `LLM-RULES.md`, `CLAUDE.md`): не перезаписывать и не генерировать заново.
- **`.dev.env`**: только дописать недостающие ключи, значения не менять. `INFOBASE_ROLE` задаёт пользователь.
- **Файлы OpenSpec** (`opsx/*`, `openspec-*`): установленные удалить до размещения и поставить из текущего бандла (раздел F).
- **`__pycache__`**: не копировать; удалить в `content/` до установки и в проекте, если остался.
- **Общие файлы вне проекта** (`~/.codex/prompts/*.md`) принадлежат манифестам нескольких проектов: их изменение после обновления первого проекта — не правка пользователя.
- **Сироты манифеста** (источника в `dev` больше нет) удаляются. Файлы вне манифеста не трогаются без решения пользователя.

## A. Собственные навыки и агенты

- `content/skills/1c-extension-analysis/` — анализ расширения конфигурации: зачем оно изменяет типовую, реестр изменений, отчёт для заказчика.
- `content/skills/1c-ui-testing/` — UI-тестирование через тестовый клиент и менеджер тестирования платформы.
  - Маршрут относительно UI-путей апстрима (`1c-qa-testing` / QA MCP, `1c-tester`, `1c-ui-regression`) — по принципу веба: интерактивная проверка идёт путями апстрима, сохранённые сценарии TestClient — нашим раннером. Отдельные тексты: раздел «Saved thin / thick client scenarios (TestClient)» в `content/rules/ui-testing-tools.md` (его читают `1c-tester`, шаг 4 `/deploy-and-test` и `/test-fix-loop`) и строка в списке «QA MCP Testing» в `content/agents/tester.md`; `UI_TESTING` (включая `essential`) распространяется и на прогоны TestClient.
  - Почему: пути апстрима не знают сохранённых сценариев TestClient — без этих текстов агент повторяет их через QA MCP или браузер, а поведение толстого клиента без QA MCP уводит в веб. QA MCP в рабочих проектах не используется: его обвязка запуска клиента рассчитана на Windows, а наш менеджер тестирования — толстый клиент.
  - Не кандидат в support: разделы имеют смысл только вместе с нашим навыком. При конфликте берётся текст апстрима, разделы переносятся на новое место.
- `content/skills/1c-test-debug/` — проверки на тестовой базе без человека у экрана: код и журнал регистрации через отладочное расширение, HTTP-вызовы с учётными данными из `.dev.env`, `/CheckModules`. Раннер `1c-ui-testing` вызывает его `ib-errors.py` для диагностики.
  - Gate 3a через `Dbg_Executor` — отдельными абзацами: «Without `1c-data-mcp`» в Gate 3a (`content/rules/verification-gates.md`) и фраза о планировании проверок в `content/rules/sdd-integrations.md`. Только при `TOOL_DATA=auto` и отсутствии `1c-data-mcp` в сеансе; `off` и `required` так не заменяются.
  - Вид `unit` навыка `1c-ui-testing` как проверенный раннер проекта — отдельный абзац в `content/skills/1c-business-tests/SKILL.md`.
  - Почему: в рабочих проектах нет `1c-data-mcp`, и без замены Gate 3a не выполняется никогда, а сдача работы требует подтверждения поведения (Gate 3a или UI). `1c-business-tests` велит взять раннер проекта, а наш спрятан в навыке UI-тестов.
  - Не кандидат в support: абзацы имеют смысл только вместе с нашими навыками. При конфликте берётся текст апстрима, абзацы переносятся. Абзац в Gate 3a живёт в наборе правил полного цикла, запас которого почти исчерпан, — укорачивать его, а не расширять.
- `content/skills/1c-ibsrv-ops/` — автономный сервер 1С (`ibsrv`) как публикация тестовой базы: создание базы и конфигурации сервера, публикация HTTP-сервисов конфигурации и расширений, запуск, перезапуск, остановка, сеансы и блокировки. На него опираются `1c-test-debug` и `1c-ui-testing`.
  - Ключ `IBSRV_DIR` — отдельным блоком в `.dev.env.example` после `INFOBASE_PUBLISH_URL`. Почему: навык и `1c-test-debug` читают его, а установщик создаёт `.dev.env` из примера — без блока в новом проекте ключа нет. При конфликте берётся файл апстрима, блок переносится.
- `content/skills/openspec-agents/` — порядок работы над изменением OpenSpec с агентами (`review.md`, `test-plan.md`, `verify.md`, дерево `openspec/tests/`) и неинтерактивный запуск агента через `claude -p`.
- `content/skills/audit-review/` — проверка содержимого перед коммитом: утечки контекста и соответствие назначению файла.
- `content/agents/extension-analyst.md` — субагент полного анализа расширения; зарегистрирован в `content/rules/subagents.md` (каталог агентов, счётчик агентов, тир `coding`) и в `content/rules/subagent-core.md` (read-only агенты).
- `content/agents/openspec-tester.md`, `content/agents/openspec-implementer.md` — агенты навыка `openspec-agents`: тесты по спецификации и проверка, реализация задач изменения. Зарегистрированы в `content/rules/subagents.md` (каталог, счётчик, `allowParallel: false`, тир `coding`); владение артефактами — отдельным абзацем после таблицы в `content/rules/sdd-integrations.md`.

## B. Python-рантайм `1c-metadata-manage`

Апстрим поставляет Python-точки входа для пяти команд метаданных и четырёх веб-команд `1c-web-ops`. `dev` поставляет Python-двойник для каждого инструмента, чтобы навык работал на Linux / macOS без PowerShell.

- **Порты:** `content/skills/1c-metadata-manage/tools/*/scripts/*.py`. Веб-команды `tools/1c-web-ops/` — реализация апстрима (`web_common.py`) с одним отличием, ниже. Не портирован `tools/_common/DevEnv.ps1` (его Python-аналог — `dev_env.py`).
- **Общие помощники:** `tools/_common/Invoke-1CEdit.py`, `tools/_common/MetadataAddress.py`, `tools/_common/meta_dsl.py`, `tools/_common/platform_args.py`, `tools/_shared/support_guard.py`, `tools/_shared/xml_eol.py`.
- **Документация:** `content/skills/1c-metadata-manage/SKILL.md` (уровни Python-портов, Python-обёртка preview), `content/skills/1c-metadata-manage/NOTICE.md` (локальные отличия портов), `content/skills/1c-metadata-manage/docs/CHANGELOG.md` (записи об изменениях портов), `content/skills/1c-metadata-manage/docs/edit-preview.md` (Python-обёртка и та же политика preview), `content/skills/1c-metadata-manage/docs/cf-manage.md` (вызов `dump-validate.py`), `content/skills/1c-metadata-manage/docs/template-manage.md` (абзац об `add-template.py`), `content/skills/1c-metadata-manage/docs/db-manage.md` (параметры `ibcmd` для базы в СУБД с пометкой «только Python»), `content/skills/1c-metadata-manage/docs/web-manage.md` (пункт о публикации HTTP-сервисов расширений), `content/commands/installfilesupdatescript.md` (раздел «Linux» для `install-files-update.py`).
- **Тесты:** `tools/tests/python-ports-regression.py` и фикстура `tools/tests/fixtures/epf-with-template/`; отличие веб-команд — в `tools/tests/web-python-regression.py` апстрима. Проверка апстрима «ports: exactly the documented commands have a Python peer» у нас ослаблена до «у документированных команд есть `.py`»: `.py` есть у каждого инструмента, поэтому требование «больше ни у кого» к `dev` неприменимо.

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
| `web_common.py` (`vrd_content()`) | В `default.vrd` задано `publishExtensionsByDefault="true"`; описано в `docs/web-manage.md` и `NOTICE.md` | Без атрибута HTTP-сервисы расширений отвечают 404. У апстрима та же ошибка и в `web_common.py`, и в `web-publish.ps1` — кандидат в support |
| `install-files-update.py` | Таймер systemd пользователя вместо задачи планировщика Windows; зеркалирование на Python вместо `robocopy /MIR`, неизменённые файлы не перезаписываются; отказ на символических ссылках; `1cv8` — `PLATFORM_PATH/bin/1cv8` или `PLATFORM_PATH/1cv8`. В `content/commands/installfilesupdatescript.md` — отдельные абзацы: «**Linux.**» после вводной части (переадресует на раздел «Linux») и раздел «Linux» в конце; текст апстрима не тронут | У `.ps1` нет Linux-варианта; таймер без linger, как и задача Windows, работает только в сеансе пользователя — конфигуратору нужен дисплей. Неперезапись неизменённых файлов не заставляет MCP переиндексировать весь каталог. |
| `db-run.py` | Флаги `-Out`, `-Wait` и `-ClientKind` | В пакетном режиме ошибки запуска видны только в `/Out`; `-Wait` возвращает код завершения клиента; `-ClientKind thin` запускает тонкий клиент — толстый к автономному серверу (`ibsrv`) не подключается |
| `db-create.py`, `db-load-dt.py`, `db-load-xml.py`, `db-update.py` (+ `ibcmd_connection()` в `_common/platform_args.py`) | Ветка `ibcmd` работает с базой в СУБД без кластера 1С (`-Dbms`, `-DbServer`, `-DbName`, `-DbUser`, `-DbPassword`, `-IbcmdDataPath`, `-IbcmdTempPath`); `db-create` — `-Locale` и `-PageSize`; `db-update` и `db-load-xml` — `-SessionTerminate`; `db-load-xml -UpdateDB` применяет загруженное расширение | Тестовая база в PostgreSQL без кластера — только через `ibcmd`, а у апстрима эта ветка умеет лишь файловую базу. Только в `.py`: `.ps1` остаются как в `main`; кандидат в upstream |
| `content/skills/img-grid-analysis/scripts/overlay-grid.py` | Отклоняет `--cols <= 0` и `--rows < 0`, строит минимум одну строку сетки, выводит UTF-8 | Исправление ошибок; кандидат в support |

Каждое отличие отмечено в коде комментарием `# Local:` или заголовком `Deviation`.

## C. Собственные инструменты сверх апстрима

- `tools/1c-cfe-manage/scripts/cfe-build.ps1`, `cfe-build.py` и раздел о сборке в `content/skills/1c-metadata-manage/docs/cfe-manage.md` — сборка `.cfe` из XML через одноразовую базу. У апстрима то же делается цепочкой `db-ops` вручную.
- `tools/1c-form-decompile/` (`form-decompile.ps1`, `form-decompile.py`) и раздел «Decompile» в `content/skills/1c-metadata-manage/docs/form-manage.md` — черновик DSL из существующего `Form.xml`. Аналога у апстрима нет.
- `tools/1c-db-ops/scripts/db-check.py` и раздел «11. Designer Checks» в `content/skills/1c-metadata-manage/docs/db-manage.md` — лестница проверок Конфигуратора из `content/rules/designer-batch-checks.md` (`/CheckModules` → `/CheckCanApplyConfigurationExtensions` → `/CheckConfig`) с вердиктом по трём признакам. Только Python, `.ps1` нет. Аналога у апстрима нет.

## D. Документация, точнее апстрима

Скрипты, которые описывают эти документы, совпадают с `main`; расходится только описание. Оставлено, кандидаты в support.

| Документ | Отличие |
|---|---|
| `content/skills/1c-metadata-manage/docs/cf-manage.md` | Описывает параметры `cf-init` (`-Synonym`, `-Version` и др.), операции `cf-edit` `set-panels` / `set-home-page` и параметры `cf-info` (`-Mode`, `-Section`, `-Limit`, `-Offset`, `-OutFile`) — всё это есть в скриптах |
| `content/skills/1c-metadata-manage/docs/template-manage.md` | Описывает `-SetMainSKD` и тип `DataCompositionSchema` у `add-template` |
| `content/skills/1c-metadata-manage/docs/skd-manage.md`, `content/skills/1c-metadata-manage/tools/1c-skd-info/modes-reference.md` | Описывают `skd-info -Raw` |
| `content/skills/1c-metadata-manage/docs/meta-manage.md` | Раздел о составных типах атрибутов |

## E. Правки внутри предложений апстрима

Принцип 3 нарушен в этих местах сознательно или отложенно. При конфликте берётся текст апстрима и правка повторяется; отложенные со временем выносятся в отдельные абзацы.

- Неизбежные — счётчики и списки агентов: `content/rules/subagents.md` (число агентов, `allowParallel`, список тира `coding`), `content/rules/subagent-core.md` (список read-only агентов).
- Отложенные:
  - `content/skills/1c-metadata-manage/SKILL.md`: таблица Python-рантайма заменена таблицей уровней, строка маршрута «Databases», слово «yet» в абзаце «A missing runtime…»;
  - `content/skills/1c-metadata-manage/NOTICE.md`: число Python-точек входа, фраза «Other tool commands remain PowerShell-only»;
  - `content/skills/1c-metadata-manage/docs/edit-preview.md`: заголовок, упоминание `MetadataAddress.py`, пункт о Python-обёртке;
  - `content/skills/1c-metadata-manage/docs/cfe-manage.md`: заголовок и вводное предложение;
  - `content/skills/1c-metadata-manage/docs/cf-manage.md`, `template-manage.md`, `skd-manage.md`: строки команд и таблиц из раздела D.

## F. Известные ошибки апстрима без локального исправления

Кандидаты в support; до исправления обходятся при установке.

- `install.ps1`: при обновлении из манифеста выбрасываются записи без `userModified`, после чего `Invoke-OpenSpecArtifacts` считает существующие файлы OpenSpec пользовательскими и не обновляет их. Бандл остаётся старым, новые команды встают рядом. Обход: перед обновлением удалить установленные `opsx/*` и `openspec-*`.
- `install.ps1`: навыки копируются из рабочего дерева целиком, включая игнорируемые git `__pycache__`. Обход: удалить `__pycache__` в `content/` перед установкой.

## Этот файл

- `adaptation.md` — перечень отличий и принципы синхронизации.
