---
description: Re-download the 1C MCP server distribution from vibecoding1c.ru, pull new images, refresh keys and restart installed servers
userOnly: true
---

# /updatemcp — update MCP servers from a fresh vibecoding1c.ru distribution

This command updates already installed 1C MCP servers. It re-downloads the latest distribution from `https://vibecoding1c.ru/mcpserver` (download flow — `/installmcp` → *1.1. Distribution download flow*), unpacks the new archive into a **staging** directory, merges new license keys into the existing `config.env`, pulls fresh Docker images, and recreates the running containers. Reindexing is preserved by reusing existing volumes whenever possible.

Use `/installmcp` for the very first installation (no existing containers, fresh `config.env`). Use `/checkmcp` to inspect the current state at any point.

Load `content/rules/mcp-deployment.md` before locating the installation. Reuse the recorded local or shared host/context, bind address, allocated host ports, full client URLs and daemon-host paths. Run Docker commands against that target explicitly; a remote Debian/Ubuntu Engine needs no local Docker Desktop. Without access to its host, report update work as blocked instead of creating a local replacement. An update never automatically reallocates existing shared ports.

## Image variant and outdated tags

The tag contract (variants `latest` / `light` / `arm64`, `IMAGE_VARIANT` and the optional `IMAGE_TAG` override, which tags exist, how to verify a tag, the boundaries) is defined once in **`/installmcp` → `## Image variant`**. Read it there. An update keeps the installed variant; changing it happens only on the user's explicit request.

Since 27.09.2026 there is one channel — stable. An installation still on a `*-beta` tag (`latest-beta`, `light-beta`, `arm64-beta` in `config.env` or on a container) or on an image created before 27.09.2026 is outdated: this update moves it to the same variant without the suffix (`light-beta` → `light`), with the new `LICENSE_KEY_<SERVER>` keys from the archive and the index and container-name handling of the upgrade table in the distribution's `INSTALL.md`. Name the migration in the Step 4 plan; no separate confirmation beyond that plan is needed.

## Steps

### 1. Locate the existing installation

Reuse the known installation root on the selected host. Only if missing, ask **one** question (adapt the path example to that host's OS):

> Где лежит текущий распакованный дистрибутив (`INSTALL.md` + `config.env` + папка `servers/`)? По умолчанию — `C:\Work\MCP_Distr`. Введите путь или нажмите Enter.

Verify that `<EXISTING>\INSTALL.md` and `<EXISTING>\config.env` exist. If not — stop and tell the user that this looks like a fresh install (run `/installmcp` instead).

Read `<EXISTING>\config.env` into memory (parsed key=value); these are the **current** values that will be merged with the new archive in Step 3.

### 2. Download the fresh distribution

Download and unpack — `/installmcp` → *1.1. Distribution download flow* (`content/commands/installmcp.md`): Tilda credentials from `memory.md` or asked once (storage only with consent — the policy is owned there), stub → `POST /api/login/` → `POST /api/getpage/` → Yandex Disk public link → Yandex Disk Public API → `Invoke-WebRequest`, with the browser-automation / manual fallback. Run it with two update-specific differences:

#### 2.1. Change check before the download

After the archive metadata is resolved (`$meta` from the Yandex Disk Public API), compare `$meta.modified` against the modification time of `<EXISTING>\INSTALL.md` (or any record kept from the previous installation). If the archive on Yandex Disk is older or equal, ask the user:

> На Яндекс.Диске лежит архив `<NAME>` от `<MODIFIED>`, размер `<SIZE>`. Текущая установка в `<EXISTING>` уже использует эту же или более свежую версию. `/updatemcp` может ничего не дать. Продолжать обновление (полезно если нужен `docker pull` под двигающимися тегами типа `latest`) или прервать команду?

Download only if the user proceeds (name + size are shown and confirmed before `Invoke-WebRequest`, as in the canon).

#### 2.2. Unpack into a staging directory (never over the user's `config.env`)

```powershell
$existing = '<EXISTING_DIR>'                                                   # e.g. C:\Work\MCP_Distr
$staging  = "$existing.new_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$archive  = '<PATH_TO_DOWNLOADED_ZIP>'                                         # from the download step
New-Item -ItemType Directory -Force -Path $staging | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $staging -Force
Get-ChildItem -LiteralPath $staging -Force | Select-Object Mode, Name, Length | Format-Table -AutoSize
```

Verify that `$staging\INSTALL.md`, `$staging\config.env`, `$staging\servers\` and `$staging\Graph_metadata_search\` exist. If not — the archive layout changed; stop and ask the user to recheck the source.

### 3. Merge `config.env` (keys-only update, do not lose user data)

Open `$staging\config.env` and `<EXISTING>\config.env` and merge them with the following rules:

| Field class | Source of truth | Action |
|---|---|---|
| `LICENSE_KEY_*` | new archive | **always overwrite** existing values with values from `$staging\config.env` (these are the new license keys included in the release) |
| `IMAGE_VARIANT` / `IMAGE_TAG` | **the existing file** | Keep the installed variant — an archive default must not silently switch `light` to `latest` or the reverse. A `*-beta` value becomes the same variant without the suffix (`## Image variant and outdated tags`). An older file with only `IMAGE_TAG` keeps that key. Show old vs new only when a value actually changes. |
| `USE_GPU`, `SSL_VERSION` and other release-version-coupled parameters | new archive default + user confirmation | show old vs new, ask explicitly whether to keep the user's existing value or switch to the new default |
| `PATH_1C_BIN`, `PATH_METADATA`, `PATH_CODE`, `PATH_BASES`, `EMBEDDING_API_KEY`, `EMBEDDING_API_BASE`, `EMBEDDING_MODEL`, `CHAT_API_KEY`, `ONEC_AI_TOKEN` and any other user-supplied data | existing file | **keep** the user's values; never overwrite from the archive (archive ships them empty) |
| any new variable present in `$staging\config.env` but missing in `<EXISTING>\config.env` | new archive | **add** it to the existing file; if it is empty and looks user-required, ask the user (one consolidated message), then save |

After merging, write the result back to `<EXISTING>\config.env`. **Never print license keys or tokens to the user**; refer to them by name (`LICENSE_KEY_HELP updated`, etc.).

Before replacing supporting files, save the current Compose file and its deployment overrides alongside the pre-update settings; the new staging copy is not a rollback copy. Once `<EXISTING>\config.env` is updated, refresh supporting files from staging while retaining recorded host paths, bind addresses and port assignments:

- `<EXISTING>\INSTALL.md` ← `$staging\INSTALL.md`
- `<EXISTING>\servers\*.md` ← `$staging\servers\*.md`
- `<EXISTING>\Graph_metadata_search\docker-compose.yml` ← `$staging\Graph_metadata_search\docker-compose.yml`
- `<EXISTING>\Graph_metadata_search\.env` — re-render from the merged `<EXISTING>\config.env` per `servers\02_GraphMetadataSearch.md` (do **not** blindly copy `.env` from staging — it ships with empty values).

Reapply supported deployment settings/overrides to the refreshed Compose configuration and inspect its effective publications before recreation. Do not accidentally keep both default and custom port publications or copy staging's localhost/default ports over the existing mapping.

After all files are in place, the staging directory can be deleted (or kept as a backup for one cycle, user choice).

### 4. Capture pre-update state

Before changing any container, record the current state so there is something to compare against and roll back from:

```powershell
docker version --format '{{.Server.Version}}'
docker ps --all --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker images --format 'table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.CreatedSince}}\t{{.Size}}'
```

For each MCP container the distribution knows about (`1c_help_mcp`, `1c_code_metadata_mcp`, `1c_ssl_mcp`, `1c_templates_mcp`, `1c_syntax_checker_mcp`, `1c_code_checker_mcp`, plus the GraphMetadata Compose stack), check whether it exists:

```powershell
docker ps -a --filter "name=<container_name>" --format "{{.Names}} {{.Status}} {{.Image}} {{.Mounts}}"
```

If a container is absent, it was not installed previously — `/updatemcp` will **not** install it (use `/installmcp` for that) and will mark it as skipped in the final report.

### 5. Plan the update

Briefly summarize for the user (3-7 lines):

- which servers will be updated (only those present in `docker ps -a`);
- the image tag per server: `<current tag>` → `<target tag>` (a `*-beta` migration is named explicitly), or "тег не меняется";
- which images will be pulled (image:tag from per-server `servers\NN_*.md`, with the effective tag from `config.env`);
- whether reindexing is needed and roughly how long;
- which `LICENSE_KEY_*` changed (by name only, never the value);
- explicitly: volumes are reused by default (no reindexing, indexes preserved).

Risky steps that must be called out: volume deletion, manual DB migration, stopping a container during active indexing, and a migration off a `*-beta` tag or a pre-27.09.2026 image (new keys, possibly new index folders per `INSTALL.md`). Ask for explicit confirmation before continuing.

### 6. Execute the update — one container at a time

For each installed container, perform the standard `INSTALL.md` update cycle:

#### 6.1. Stop and back up the old container

```powershell
docker stop <container_name>
$stamp = Get-Date -Format 'yyyyMMdd'
docker rename <container_name> "<container_name>_backup_$stamp"
```

Tell the user explicitly:

> Старый контейнер `<container_name>` остановлен и сохранён как `<container_name>_backup_<YYYYMMDD>`. Откатиться можно командой `docker start <container_name>_backup_<YYYYMMDD>` (после остановки нового).

#### 6.2. Confirm volume policy

> У старого контейнера были примонтированы тома (базы данных).
>
> 1. Использовать **те же базы** для нового контейнера (рекомендуется — данные сохранятся, не нужна переиндексация).
> 2. Создать **новые базы** в другом каталоге (старые останутся нетронутыми при старом контейнере).

Default to option 1 unless the user explicitly chooses 2 or the release notes require a fresh index.

#### 6.3. Pull the new image

```powershell
docker pull <image>:<IMAGE_TAG_from_config_env>
```

Pull is **mandatory** on update — this is the whole point of the command. Pull also the GraphMetadata stack via `docker-compose pull` in `<EXISTING>\Graph_metadata_search\` (it has multiple images: app + Neo4j) after writing the merged effective tag into that folder's `.env`, so the stack follows the same variant.

If the pull fails with `manifest unknown`, **stop for that server**, leave the previous state in place (the old container was only stopped and renamed in 6.1 — start the backup again), and report it. Never fall back to another tag silently, and never to a `*-beta` tag.

#### 6.4. Start the new container

Use the `docker run` block from `<EXISTING>\servers\NN_*.md`, substituting `{{...}}` placeholders from the merged `<EXISTING>\config.env` and preserving the recorded host bind address, host/container port mappings and daemon-host mounts. Show the target and command with secrets masked (`-e LICENSE_KEY="***"`) and wait for confirmation. For GraphMetadata use the selected host's Compose command with its verified deployment overrides. A conflict on an existing shared port blocks that restart; do not pick a new port as recovery.

If `USE_GPU=true`, add `--gpus all` right after `docker run -d` per the per-server file note.

#### 6.5. Verify

```powershell
docker logs <container_name> --tail 50
```

After a migration off an outdated image, also read the log for index / schema mismatch messages. If one appears, do **not** delete the old index: point that server's volume at a new directory under `PATH_BASES`, recreate the container, and let it reindex — the old index then survives a rollback to the backup container intact.

If the log shows `LICENSE` / `license key` errors:

- Tell the user: "Лицензионный ключ для `<server>` не принят. Возможно, в `<EXISTING>\config.env` нужно обновить значение `LICENSE_KEY_*` из свежего архива — повторите Шаг 3, либо скачайте актуальный ключ в личном кабинете https://vibecoding1c.ru/."
- Re-merge and re-run the container.

Report per server: image → new image+tag (digest if shown), container status (`Up X seconds`), volumes touched.

### 7. Reconcile the active tool MCP config

After all containers restart:

1. Compare the actual updated endpoints with the existing client config. New distribution defaults do not override allocated host ports, DNS names or proxy paths. File placement and per-client schemas belong to `/installmcp` → *Step 7. Per-client MCP config* (`content/commands/installmcp.md`). Merge only changed, selected entries and preserve other settings/auth references; an unchanged endpoint needs no client edit.
2. Never run `/updaterules` or regenerate the static MCP catalog to apply deployment endpoints. Follow `/setupmcp` merge/ownership rules, preserving external registry consumers. If an endpoint must deliberately change, record the affected shared consumers and their migration instead of silently updating only the current editor.
3. Ask the user to restart the client (Cursor / Claude Code / Codex / OpenCode / Kilo Code) so it reinitializes the MCP session.

### 8. Final check

After the client restart, run `/checkmcp`. All updated servers should reach **TOOLS_OK** (or **HTTP_OK** while reindexing is still running). If anything remains **TOOLS_MISSING** / **HTTP_DOWN**, return to Step 6 for the failing container and compare the executed steps with `<EXISTING>\servers\NN_*.md`.

## Rollback

If the update broke the working state:

1. Stop and remove the new container:

   ```powershell
   docker stop <container_name>
   docker rm <container_name>
   ```

2. Start the backup created in Step 6.1:

   ```powershell
   docker rename "<container_name>_backup_<YYYYMMDD>" <container_name>
   docker start <container_name>
   ```

3. **New image unusable**: start the backup containers from Step 6.1 — they keep the previous image and volumes — and report the failure with the log; do not move the set to a `*-beta` or another unpublished tag.
4. For GraphMetadata restore the saved **pre-update** Compose file, `.env` and deployment overrides on the recorded host, then recreate the previous stack without deleting data volumes. The freshly downloaded staging copy is not the previous deployment.
5. Restore the previous `<EXISTING>\config.env` if you saved a backup before Step 3 (recommended — copy it to `<EXISTING>\config.env.bak.<YYYYMMDD>` before merging) — this is also what restores the previous `IMAGE_VARIANT` / `IMAGE_TAG`.
6. Tell the user that rollback is complete and run `/checkmcp` again.

## Final report

Short user summary:

- download flow used (headless API / browser fallback / manual), staging directory, and final unpack directory;
- archive file name + size after download;
- new `INSTALL.md` version / date (if shown in the file);
- which `LICENSE_KEY_*` changed (by name only, never the value);
- **image tag**: `<previous tag>` → `<current tag>` per server, or "без изменений"; a `*-beta` migration named explicitly;
- servers actually updated (container name, port, previous → new image+tag);
- servers skipped and why (not installed, no `LICENSE_KEY_*`, no metadata dump, no `ONEC_AI_TOKEN`, etc.);
- backup containers kept (`<name>_backup_<YYYYMMDD>`);
- next steps if reindexing is still running.

## Limits

- The command **does not invent** update steps that are not in `<EXISTING>\INSTALL.md` and `<EXISTING>\servers\*.md`. If the bundled instruction lacks something, ask the user instead of filling gaps from memory.
- The command **does not echo or persist license keys / API tokens** in chat, in the repo, or in any committed file. Keys live only in `<EXISTING>\config.env` and in container environment variables.
- Tilda member-area credentials (`tilda_login`, `tilda_password`) are reused from `memory.md` or asked once; the storage / consent policy is owned by `/installmcp` → *Limits* and *1.1. Distribution download flow*.
- The command **does not install** servers that are not already in `docker ps -a` — use `/installmcp` for that.
- The command **does not change the image variant** without the user's explicit request, whatever the fresh archive's `config.env` defaults to, and never installs a `*-beta` tag.
- The command **does not run** `docker pull` / `docker compose up` / `docker rm` / `docker volume rm` without explicit user confirmation.
