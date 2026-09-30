---
description: Install Cognee MCP as the preferred persistent memory write provider and register it in the active AI client
userOnly: true
---

# /install-cognee — install Cognee persistent memory

Installs the official `cognee/cognee-mcp` server and exposes the focused memory API (`remember`, `recall`, `forget`) to the active AI client.

Use Cognee for general cross-session or cross-client memory. Installation is optional and preserves `.dev.env` `TOOL_*` choices. Explicit installation permits setup checks even for `TOOL_COGNEE=off`; ordinary memory use remains disabled unless the user changes/overrides policy. Routing, triage scope and Cognee-first writes belong to `content/rules/project-memory.md`. Keep server id `cognee-memory` so namespaces remain distinguishable.

Official sources:

- `https://docs.cognee.ai/cognee-mcp/mcp-quickstart`
- `https://docs.cognee.ai/cognee-mcp/mcp-local-setup`
- `https://github.com/topoteretes/cognee/tree/main/cognee-mcp`

## Default deployment

Use one local Docker HTTP server by default. It avoids file-lock contention from several editor windows spawning separate stdio processes, keeps one shared memory store, and fits the Docker-based 1C MCP bundle. Load `content/rules/mcp-deployment.md`: a shared Debian/Ubuntu Docker Engine host is an optional alternative, without requiring Docker Desktop on clients. Local-only access uses loopback; `8010` is a preferred host port, subject to the agent's automatic availability check on the deployment host.

Ask one deployment question:

> Где разместить память Cognee: локальный Docker (обычный вариант), общий сервер Debian/Ubuntu с Docker, подключение готового MCP-адреса или исходники со stdio? Для общего сервера укажите DNS/IP вместо 127.0.0.1 и доступ для установки; свободный порт я подберу сам.

If the user has no preference, choose local Docker. Never send an LLM, embedding, Cognee Cloud, or backend API key to chat logs, command output, source control, or `memory.md`.

## Docker steps (local by default; shared host optional)

### 1. Detect and collect settings

1. Confirm Docker is available and running on the selected target; apply the selected context or authorized SSH to all Docker commands. Automatically allocate a free host port and record the bind address/client URL per the deployment rule:

   ```powershell
   docker version
   docker compose version
   ```

2. Default installation root:
   - Windows: `C:\Work\CogneeMemory`
   - Linux/macOS: `~/.local/share/cognee-memory`

   Allow a different absolute path. The root must contain:

   ```text
   .env                 # secrets; never commit or print
   data/system/         # databases and graph
   data/files/          # ingested data/session cache
   install.manifest.json
   ```

3. Ask for the model/embedding provider settings Cognee needs. The simplest default is `LLM_API_KEY`; accept provider-specific variables when the user deliberately chooses another provider. Explain that Cognee needs both completion and embedding capability. Obtain explicit consent before persisting keys in `.env`.

4. If a `cognee-mcp` container or `cognee-memory` client entry already exists, inspect it. Do not overwrite or delete an existing memory store. Offer repair/update instead.

### 2. Create secret and data files

Create the directories and a UTF-8 `.env` without printing its contents. At minimum it contains the selected provider credentials plus:

```dotenv
SYSTEM_ROOT_DIRECTORY=/data/system
DATA_ROOT_DIRECTORY=/data/files
COGNEE_MCP_TOOL_MODE=minimal
TELEMETRY_DISABLED=true
```

Restrict `.env` permissions to the current user where the OS supports it. Add the absolute `.env` path and installation root to the local project's ignore rules only when they fall inside a repository.

Write `install.manifest.json` without secrets. Record the target/context, host OS, bind address, host/container ports, full client endpoint, container name, image reference, resolved image digest from `docker image inspect`, installation time, and host data directories. Refresh planned values after successful launch; reuse them on reruns.

### 3. Pull and start

Use the official image. Preserve data through the bind mount and preserve the service across reboots. The following is a local Windows example: before execution substitute the selected target, daemon-host paths and `-p <bind-ip>:<allocated-host-port>:8000` mapping. Recheck the chosen port immediately before launch:

```powershell
$root = 'C:\Work\CogneeMemory' # replace with the confirmed absolute path
$envFile = Join-Path $root '.env'
$data = Join-Path $root 'data'

docker pull cognee/cognee-mcp:main
if ($LASTEXITCODE -ne 0) { throw 'Failed to pull cognee/cognee-mcp:main' }

docker run -d --name cognee-mcp --restart unless-stopped `
  --env-file $envFile `
  -e TRANSPORT_MODE=http `
  -p 127.0.0.1:8010:8000 `
  -v "${data}:/data" `
  cognee/cognee-mcp:main
if ($LASTEXITCODE -ne 0) { throw 'Failed to start cognee-mcp' }
```

On Linux/macOS, use the equivalent shell syntax with the confirmed daemon-host paths. Shared access uses the chosen LAN/VPN interface or existing proxy per the deployment rule; never publish on `0.0.0.0` by default.

If the container name already exists, do not remove it blindly. Inspect it and ask before replacing the container; replacing the container is safe only after confirming the bind-mounted data path.

### 4. Verify

Cognee may need time for migrations on first start. Check logs on the selected host without exposing environment variables, then poll the actual client-reachable health URL for at most two minutes. Substitute the recorded endpoint in this local example:

```powershell
docker logs --tail 100 cognee-mcp
Invoke-RestMethod -Uri 'http://127.0.0.1:8010/health' -TimeoutSec 10
```

Failure to become healthy is an install failure. Report the last relevant log lines with secrets redacted.

### 5. Register the active client

Merge, never replace, an HTTP MCP entry named `cognee-memory` pointing to the recorded full client MCP URL. `http://127.0.0.1:8010/mcp` below is a local example only. Detect the client and use its native schema, following the same path/merge rules as `/installmcp` and `/install-agent-browser`.

Canonical `mcpServers` fragment:

```json
{
  "mcpServers": {
    "cognee-memory": {
      "type": "http",
      "url": "http://127.0.0.1:8010/mcp"
    }
  }
}
```

For clients that reject `type`, keep only the accepted `url`. For OpenCode use its strict remote schema; for Codex use the corresponding `[mcp_servers.cognee-memory]` TOML table. Preserve all unrelated settings and MCP entries.

Restart the AI client and verify that `remember`, `recall`, and `forget` are exposed under the `cognee-memory` server namespace. Store and recall one harmless test note, then delete that test note/dataset if the API supports precise cleanup.

## Existing remote endpoint

Ask for the Streamable HTTP URL and optional bearer token. Verify `/health` when available, merge the client entry, and store any token only in the client's supported secret/environment mechanism. Do not copy a bearer token into project files unless the user explicitly accepts that storage.

## Source stdio mode

Use only when Docker is unavailable or the user explicitly wants a source checkout. Follow the official local setup: clone `https://github.com/topoteretes/cognee.git`, enter `cognee-mcp`, install `uv`, run `uv sync --dev --all-extras --reinstall`, and register `uv --directory <absolute-cognee-mcp-path> run cognee-mcp --tool-mode minimal` as stdio.

Pin `SYSTEM_ROOT_DIRECTORY` and `DATA_ROOT_DIRECTORY` to stable absolute paths. Warn that multiple clients spawning stdio against the same embedded graph can contend on its file lock; prefer one HTTP process for shared use.

## Update and removal

- Update: on the recorded host pull a newer image, record its digest, recreate only the container with the same `.env`, bind address, port mapping and data mount, then verify its recorded endpoint. Never delete the data directory or reallocate a shared port as part of update.
- Disable: stop the container and disable/remove only the `cognee-memory` MCP entry.
- Delete memory: destructive and separate from uninstall. Require explicit confirmation naming the exact data directory before removing it.
