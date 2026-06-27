# AGENTS.md — concepts-collector

## Purpose

concepts-collector is a Model Context Protocol (MCP) server that turns arbitrary
JSON research collections into structured knowledge overviews. It loads a
collection, auto-detects its field shape, lets you query and pull individual
items, builds a concept-extraction prompt from the items you select, and persists
the finished overview to disk for later retrieval.

It does not call any LLM itself. The extraction step hands *you* (the agent) a
structured prompt plus the raw source material; you fill in the overview, then
save it back. concepts-collector is the scaffolding around that loop, not the
analyst.

## Launch

The server is started by `.mcp.json` as
`uv run --directory ${CLAUDE_PLUGIN_ROOT} python -m concepts_collector` over
stdio. `uv` resolves dependencies from `pyproject.toml` / `uv.lock` on first run
— no Node, no build step. Requires Python >= 3.11 and `uv`. The MCP server name
is `concepts-collector`; every tool is prefixed `cc_`.

## Tools

- **`cc_load_collection(file_path, name=None, field_overrides=None)`** — Read a
  JSON collection from disk into memory. Auto-detects the items array and the
  id / content / title / tags / author / date / url fields; pass `field_overrides`
  to correct any mapping. The collection is keyed by `name` (defaults to the
  file stem). Returns the detected field map and the available tag set.
- **`cc_query(collection=None, tags=None, search=None, fields=None, limit=20)`**
  — Filter loaded items. `tags` is a case-insensitive OR match; `search` is
  full-text over title + content + tags; `fields` matches metadata key→substring.
  Omit `collection` to search across all loaded collections. Returns matched item
  IDs with previews.
- **`cc_get_items(collection, item_ids)`** — Retrieve the full content of specific
  items by ID from one collection (the detail read after a `cc_query`).
- **`cc_collect_concepts(title, items, focus=None, depth="standard")`** — Build
  the extraction prompt. `items` is a list of groups, each
  `{"collection": <name>, "item_ids": [...]}`. Returns a ready-to-fill prompt
  containing instructions, an auto-built cross-reference section, the selected
  source material, and a JSON overview template. `depth` is `brief`, `standard`,
  or `deep`; `focus` biases extraction toward a topic without excluding the rest.
- **`cc_save_overview(overview, output_dir=None)`** — Persist a completed overview
  (the filled JSON template) to disk as JSON, marking its status `complete`.
  Returns the saved path and concept/theme counts.
- **`cc_list_overviews(directory=None)`** — List saved overviews with metadata
  (id, title, status, concept/source counts, file path).
- **`cc_get_overview(overview_id, directory=None)`** — Retrieve a saved overview
  by its id, returned as JSON.

## Primary workflow

1. **`cc_load_collection`** — load each source JSON; note the reported `name` and
   `available_tags`. Use `field_overrides` if the auto-detected mapping is wrong.
2. **`cc_query` / `cc_get_items`** — narrow to the items worth synthesizing.
   Query for IDs by tag/search, then read full content with `cc_get_items`.
3. **`cc_collect_concepts`** — pass the selected `{collection, item_ids}` groups
   and a title. You receive a prompt + JSON template. Fill the template
   (`summary`, `concepts`, `themes`, `key_findings`, `knowledge_gaps`,
   `open_questions`) by analyzing the embedded source material.
4. **`cc_save_overview`** — save the filled overview. Later, recover it with
   `cc_list_overviews` and `cc_get_overview`.

## Key invariants

- **Collections live in memory only.** Loaded collections are held in a
  process-global store, not persisted. After a server restart you must
  `cc_load_collection` again before querying. Overviews, by contrast, are durable
  on disk.
- **`cc_collect_concepts` returns a prompt, not an answer.** It never fills the
  overview for you; it assembles instructions + sources + a blank template. The
  analysis is your job; the result feeds `cc_save_overview`.
- **`cc_save_overview` expects the filled template** produced by
  `cc_collect_concepts` (it preserves `overview_id`, `title`, `sources`). Always
  synthesize from a `cc_collect_concepts` template rather than hand-rolling JSON.
- **Output location precedence.** Overviews are written to the `output_dir` /
  `directory` argument if given, else `$CONCEPTS_OUTPUT_DIR`, else an `output_dir`
  in `config.local.json`, else `./overviews` relative to the working directory.
  `cc_list_overviews` / `cc_get_overview` must read from the same location they
  were saved to. The `overviews/` dir and `config.local.json` are gitignored —
  never commit them.
- **Names are the handles.** `cc_query`, `cc_get_items`, and the
  `cc_collect_concepts` groups all reference a collection by the `name` returned
  from `cc_load_collection`. Reuse that exact name.
