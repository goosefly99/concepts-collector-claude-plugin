# concepts-collector-claude-plugin

Research concepts collector MCP server — load collections, extract key concepts, and generate structured knowledge base overviews.

## What it does

`concepts-collector` is a Model Context Protocol (MCP) server packaged as a Claude Code plugin. It lets Claude load arbitrary JSON research collections (with auto-detected field mapping), query and filter items across them, and synthesize selected items into structured knowledge base overviews that can be saved to disk and retrieved later.

Typical workflow: `cc_load_collection` -> `cc_query` / `cc_get_items` -> `cc_collect_concepts` -> `cc_save_overview`.

MCP tools exposed:

- **`cc_load_collection`** — Load a JSON research collection with auto-detected schema mapping; optional field overrides.
- **`cc_query`** — Search and filter items across loaded collections by tags, full-text search, or metadata fields.
- **`cc_get_items`** — Retrieve full content of specific items by ID from a collection.
- **`cc_collect_concepts`** — Extract and organize key concepts from selected items into a structured overview template (brief / standard / deep).
- **`cc_save_overview`** — Persist a completed knowledge overview to disk as JSON.
- **`cc_list_overviews`** — List all saved overviews with metadata.
- **`cc_get_overview`** — Retrieve a saved overview by ID.

## Installation

Install via Claude Code's plugin command:

```
/plugin install goosefly99/concepts-collector-claude-plugin
```

Or clone manually and register the MCP server from the cloned directory:

```bash
git clone https://github.com/goosefly99/concepts-collector-claude-plugin.git
cd concepts-collector-claude-plugin
npm install
```

The plugin registers its MCP server via `.mcp.json`, which invokes `start.mjs` using `${CLAUDE_PLUGIN_ROOT}` so it resolves correctly regardless of install location.

## Configuration

No environment variables are required for basic use.

Runtime data is written under the plugin directory:

- `overviews/` — saved knowledge overviews (JSON). Created on first save. Gitignored.
- `config.local.json` — optional local configuration overrides. Gitignored.

Both are ignored by `.gitignore` and should never be committed.

## Requirements

- Node.js (tested with Node 20+)
- Claude Code with MCP plugin support

## License

MIT — see [LICENSE](./LICENSE).
