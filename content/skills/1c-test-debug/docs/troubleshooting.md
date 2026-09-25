# Troubleshooting a test infobase

Symptoms of the infobase and of the debug extension in it. Everything about the server that
publishes it — it will not start, a client lands in the wrong base, sessions hold licenses, a
service answers 404 or 503 — is `1c-ibsrv-ops/docs/troubleshooting.md`.

**Where the truth is.** The infobase event log answers almost everything: `scripts/ib-errors.py`
while the base can be reached, or `<data>/log-data/*.lgp` read as plain text when it cannot.

## An extension loads without an error and does nothing

**Symptom.** `infobase config import` and `apply` report success, `extension list` says
`active: yes`, and yet its HTTP services answer 404 and its objects are invisible.

**Check.** The infobase event log names the reason:

```
<Расширение>: Критичная: Значение контролируемого свойства ОбъектРасширяемойКонфигурации
у объекта Язык.Русский не совпадает со значением в расширяемой конфигурации
```

**Cause.** The extension's adopted objects — the language above all — carry the identity of the
configuration the scaffold was made against. Loaded into another base they do not match, and the
platform disables the extension silently.

**Fix.** Take the scaffold from the base the extension is loaded into:

```bash
ibcmd --pid=<pid> infobase config extension create --name=<Name> --name-prefix=<Prefix> --purpose=add-on
ibcmd --pid=<pid> infobase config export --extension=<Name> <dir>     # готовый каркас
# add your own objects to <dir>, register them in Configuration.xml ChildObjects
ibcmd --pid=<pid> infobase config import --extension=<Name> <dir>
ibcmd --pid=<pid> infobase config apply  --extension=<Name> --force
```

The platform's own scaffold has no adopted language at all and carries its own `ОсновнаяРоль`.
Editing the identity by hand in a foreign scaffold does not help — tried, still disabled.
Re-creating the base changes the identities again, so a scaffold is only valid for one base.

## A data processor opens with a security prompt

**Symptom.** An unattended session stops on «Предупреждение безопасности … Разрешить открывать
данный файл?» and waits forever.

**Cause.** The protection against dangerous actions is a property of the infobase **user**. A base
with users answers the prompt per user; a base created empty has no users to carry the setting.

**Fix.** Do not open scenarios as external files where nobody can answer: put the data processor
inside a configuration extension and open it by a navigation link
(`/URL "e1cib/app/Обработка.<Имя>"`). For a base that does have users, clear the flag on the user
(`ПользовательИнформационнойБазы.ЗащитаОтОпасныхДействий`).

## A request dies without an answer (`ib-http.py` exit 3)

**Symptom.** The connection is closed with no answer; the server's output shows the worker died on
that request (`Segmentation fault`).

**Cause.** The server module crashed on the executed code. Repeating the same request, or cutting
it into smaller pieces, only repeats the crash.

**Fix.** Read the infobase event log for what ran before the crash, and check what else was
connected: with a file infobase served through an external web server, writes sent while a client
session was connected crashed the worker in 6 of 10 measured runs. The standalone server
(`1c-ibsrv-ops`) showed no such crashes; run server-side checks before or after UI
scenarios in any case.

