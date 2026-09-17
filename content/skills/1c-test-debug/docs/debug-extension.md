# Debug extension — `Dbg_Executor` and `Dbg_LogReader`

A configuration extension with two HTTP services that let an agent run BSL in a test infobase and
read its event log. **A debug tool for a trusted caller on a test infobase only** — `Dbg_Executor`
runs any code it receives. Never install it into a production infobase and never publish it beyond
the local machine.

The extension ships as a template in `extension/`: HTTP service descriptions for the
`1c-metadata-manage` DSL (`*.json`) and their modules (`*.bsl`). The extension itself is created
for each target configuration: its adopted configuration object, language and compatibility mode
belong to that configuration and cannot be copied from another project.

## Contract

### `Dbg_Executor` — run BSL, get the result back

`POST <publication>/hs/dbg_executor/exec/<anything>`, body `{"Код": "<BSL statements>"}`.

- The code runs through `Выполнить()` in the scope of the handler; assign to `Результат` to return
  a value.
- Answer `{"Результат": <JSON value>}`: `ТаблицаЗначений` → array of row objects; `Структура`,
  `Соответствие` → object; references, objects and metadata → their `Строка(...)`; nothing assigned →
  `null`.
- 200 — executed (also when nothing is assigned); 400 — body is not JSON or has no `Код`;
  500 — compile or runtime error in the code, with its text.

From a project: `python3 <skill>/scripts/ib-http.py --exec <file.bsl>` prints `Результат`.

### `Dbg_LogReader` — the event log as JSON

`POST <publication>/hs/dbg_logreader/read/<anything>`, body — a filter, all fields optional:
`ДатаНачала` / `ДатаОкончания` (XML date-time), `Уровень` (`"Информация"`, `"Ошибка"`,
`"Предупреждение"`, `"Примечание"`; string or array), `Событие`, `Пользователь`, `Метаданные`
(string or array), `КоличествоСобытий` (default 100, at most 5000). `{}` returns the last 100 events.

- Answer `{"Количество": N, "События": [...]}`; an event carries `Дата, Уровень, Пользователь,
  Компьютер, ИмяПриложения, Событие, Комментарий, Метаданные, Данные, Транзакция,
  СтатусТранзакции, Сеанс, Соединение`.
- 400 — bad filter (invalid date, `ДатаНачала` later than `ДатаОкончания`, unknown `Уровень`);
  500 — platform error.

From a project: `python3 <skill>/scripts/ib-errors.py` reads the errors.

### Rights

The extension has **no role**. Both services require a user with full rights of the main
configuration (`ПолныеПрава` or equivalent): through them the platform grants the HTTP services of
the extension and the event-log right.

This was checked on a real infobase: a user with only an extension role that granted `EventLog` on
the adopted configuration got **403** «Недостаточно прав для использования ресурса с данным HTTP
методом» on both services, `ПравоДоступа("ЖурналРегистрации", Метаданные, <роль>)` returned `Ложь`
with and without that right, and an administrator worked with the role reduced to nothing. A role
with rights on the adopted configuration only ties the extension to the configuration name and
gives nothing.

## Installing into a target configuration

Everything goes through the `1c-metadata-manage` skill; commands below are its Python entry points,
run from the project root. `<skill>` is this skill's directory, `<mm>` is
`<tools>/skills/1c-metadata-manage/tools`, `<ext>` is the extension source directory of the project.

1. **Scaffold without a role, bound to the main configuration.**

   ```bash
   python3 <mm>/1c-cfe-manage/scripts/cfe-init.py -Name АгентОтладкаHTTP -Synonym "Агент отладки HTTP" \
     -NamePrefix Dbg_ -Purpose AddOn -ConfigPath <main configuration sources> -NoRole -OutputDir <ext>
   ```

   `-ConfigPath` is required: from the main configuration it takes the identifier of the adopted
   language, `CompatibilityMode` and `InterfaceCompatibilityMode`. Without it the platform refuses
   the load: «Значение контролируемого свойства РежимСовместимостиИнтерфейса … не совпадает» and
   «… ОбъектРасширяемойКонфигурации у объекта Язык.Русский не совпадает».
2. **HTTP services from the template.**

   ```bash
   python3 <mm>/1c-meta-compile/scripts/meta-compile.py -JsonPath <skill>/extension/Dbg_Executor.json -OutputDir <ext>
   python3 <mm>/1c-meta-compile/scripts/meta-compile.py -JsonPath <skill>/extension/Dbg_LogReader.json -OutputDir <ext>
   cp <skill>/extension/Dbg_Executor.bsl  <ext>/HTTPServices/Dbg_Executor/Ext/Module.bsl
   cp <skill>/extension/Dbg_LogReader.bsl <ext>/HTTPServices/Dbg_LogReader/Ext/Module.bsl
   ```

   `meta-compile` names a method handler «template name + method name»: the template yields
   `ВыполнениеВызов` and `ЧтениеВызов`, the names of the functions in the template modules. Check
   `<Handler>` in `HTTPServices/*.xml` after compiling.
3. **Validate** — `cfe-validate.py -ExtensionPath <ext>`.
4. **Load into the test infobase** — `db-load-xml.py … -ConfigDir <ext> -Extension АгентОтладкаHTTP
   -Mode Full -UpdateDB`; read the whole log.
5. **Publish** the infobase with HTTP services of extensions enabled — [deploy-linux.md](deploy-linux.md)
   or `1c-web-ops` on Windows. Existing web sessions keep the old extension until the web server is
   restarted.
6. **Check** — `python3 <skill>/scripts/check-services.py`: both services 200 with the credentials of
   `.dev.env`.
