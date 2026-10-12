# MCP server catalog

| Server id | Purpose | Details |
|---|---|---|
| `1c-graph-metadata-mcp` | Neo4j graph: dossier, impact, call graph, usages, business search, extension layers | [1c-graph-metadata-mcp.md](1c-graph-metadata-mcp.md) |
| `1c-code-metadata-mcp` | Metadata and BSL search, navigation, forms, XSD, `verify_xml` | [1c-code-metadata-mcp.md](1c-code-metadata-mcp.md) |
| `1c-syntax-checker-mcp` | BSL Language Server: `syntaxcheck_file` (default), `syntaxcheck` (text fallback) | [1c-syntax-checker-mcp.md](1c-syntax-checker-mcp.md) |
| `1c-code-check-mcp` | 1С:Напарник: `check_1c_code`, `review_1c_code`, AI drafts, ITS, version docs | [1c-code-check-mcp.md](1c-code-check-mcp.md) |
| `1C-docs-mcp` | Platform reference (`docsearch`, `docinfo`), `standards`, `formatspec` | [1C-docs-mcp.md](1C-docs-mcp.md) |
| `1c-ssl-mcp` | БСП / SSL API search | [1c-ssl-mcp.md](1c-ssl-mcp.md) |
| `1c-templates-mcp` | Code templates, memory fallback | [1c-templates-mcp.md](1c-templates-mcp.md) |
| `cognee`, `openviking` *(optional)* | Memory providers | [memory-providers.md](memory-providers.md) |
| `1c-data-mcp` | Live-IB execution over `hs/mcp` | [1c-data-mcp.md](1c-data-mcp.md) |
| `1c-qa` | QA MCP: test manager driving a 1C test client — UI checks under `UI_TESTING` | `content/skills/1c-qa-testing/SKILL.md` |
| `edt-mcp` *(conditional)* | Live EDT workspace | [edt-mcp.md](edt-mcp.md) |

### Optional pre-alpha servers

These are experimental projects, separate from the eight main servers above and not required by normal development gates. Client aliases vary; use the tools actually exposed in this session. Read their catalog only for a task that needs them; do not install, start a client, replay UI actions or write conversion files merely to check availability.

| Project / runtime server name | Purpose | Details |
|---|---|---|
| `MCP_Test` / `1C Visual UI Test` | Testing knowledge base, scenario preparation, test-client processes and UI replay | [mcp-test.md](mcp-test.md) |
| `MCP_ConversionData20` / `1C Конвертация данных 2.0 — разработка правил обмена` | Metadata mapping and conversion-rule authoring/validation/export | [mcp-conversion-data20.md](mcp-conversion-data20.md) |
