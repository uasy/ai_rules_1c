# Memory providers — Cognee, OpenViking and templates MCP

Policy, write priority, search coverage and failure handling are owned by `content/rules/project-memory.md`. This catalog maps those logical operations to tools; it does not make a configured or installed server available in the current session.

## Cognee

Server aliases commonly include `cognee` and `cognee-memory`. Discover the exposed namespace; do not call both aliases if they are known to share one store.

- Search: `recall(query=...)`; use an established project `datasets` scope when supported.
- Durable write: `remember(data=..., dataset_name=...)`; omit `session_id`, which selects session-only storage. Omit `dataset_name` when the established client default is appropriate.
- Inspect the live descriptor before optional arguments or cleanup. `forget(dataset=...)` can delete an entire dataset; it is not a single-note delete API.

Installation: `content/commands/install-cognee.md`. Official reference: [Cognee MCP quickstart](https://docs.cognee.ai/cognee-mcp/mcp-quickstart). Live tool descriptors override examples here.

## OpenViking

The native HTTP server exposes MCP at `/mcp` (default local port `1933`). Use its memory tools alongside other connected providers.

- Search: `search(query=...)` or `find(query=...)`; when supported, scope to an established `target_uri`. Current `search` also supports `mode="context"`; older deployments may expose `recall` instead. Select from the live schema, not a presumed tool version.
- Durable write: `remember(messages=[{"role":"user","content":"<one scoped fact>"}])`. Send the intended note, not an unrelated conversation transcript. Inspect the result for completion or pending extraction.
- Read a returned note URI with the exposed `read` tool when the search excerpt is insufficient. Preserve returned canonical URIs instead of constructing another user's memory path.
- Retire a note with `forget(uri=...)` only when that URI identifies the intended note; never substitute a recursive memory-root deletion.

Installation: `content/commands/install-openviking.md`. Verified against the [official MCP integration guide](https://docs.openviking.ai/en/guides/06-mcp-integration); the connected server's descriptor remains authoritative.

## 1c-templates-mcp

Search with `recall(query=...)` on every memory lookup while exposed, even when Cognee or OpenViking receives writes. Use `remember(content=...)` as the write fallback when neither primary provider is available for writing. `templatesearch` searches code templates and does not replace memory retrieval.

Authentication, schemas and template retrieval: `content/skills/mcp-1c-tools/docs/1c-templates-mcp.md`. A `stored=true` / `index_pending=true` response is already durable; do not retry that write.
