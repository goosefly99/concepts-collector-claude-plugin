from __future__ import annotations

import json
import os
import secrets
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
STORE: dict[str, dict[str, Any]] = {}

mcp = FastMCP("concepts-collector")


def _output_dir() -> Path:
    env = os.environ.get("CONCEPTS_OUTPUT_DIR")
    if env:
        return Path(env).expanduser().resolve()

    config_path = PLUGIN_ROOT / "config.local.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            config = None
        if isinstance(config, dict):
            output_dir = config.get("output_dir")
            if isinstance(output_dir, str) and output_dir.strip():
                return Path(output_dir).expanduser().resolve()

    return Path.cwd().resolve() / "overviews"


def _as_string(value: Any) -> str:
    return "" if value is None else str(value)


def _detect_field_map(data: dict[str, Any], overrides: dict[str, str] | None = None) -> dict[str, str]:
    overrides = overrides or {}
    items_key = overrides.get("items_key", "items")
    if not isinstance(data.get(items_key), list):
        array_key = next((key for key, value in data.items() if isinstance(value, list)), None)
        if array_key:
            items_key = array_key

    items = data.get(items_key)
    if not isinstance(items, list) or not items:
        raise ValueError(f'No items array found in data (tried key "{items_key}")')

    sample = items[0]
    if not isinstance(sample, dict):
        raise ValueError("Items array must contain objects")

    def find_field(candidates: list[str]) -> str | None:
        for candidate in candidates:
            if candidate in sample:
                return candidate
        return None

    def find_id_field() -> str:
        direct = find_field(["id", "tweet_id", "post_id", "article_id", "item_id", "uid", "key"])
        if direct:
            return direct
        suffixed = next((key for key in sample if key.endswith("_id")), None)
        return suffixed or "id"

    return {
        "items_key": items_key,
        "id_field": overrides.get("id_field", find_id_field()),
        "content_field": overrides.get(
            "content_field",
            find_field(["content", "body", "text", "description", "full_text", "article_text"]) or "content",
        ),
        "title_field": overrides.get(
            "title_field",
            find_field(["summary", "title", "name", "headline", "subject"]) or "title",
        ),
        "tags_field": overrides.get(
            "tags_field",
            find_field(["tags", "categories", "labels", "keywords", "topics"]) or "tags",
        ),
        "author_field": overrides.get(
            "author_field",
            find_field(["profile", "author", "user", "creator", "poster"]) or "",
        ),
        "date_field": overrides.get(
            "date_field",
            find_field(["date", "created_at", "published", "timestamp", "published_at", "created"]) or "",
        ),
        "url_field": overrides.get(
            "url_field",
            find_field(["url", "link", "href", "source_url", "permalink"]) or "",
        ),
    }


def _normalize_item(raw: dict[str, Any], field_map: dict[str, str], index: int) -> dict[str, Any]:
    def get(field: str | None) -> Any:
        return raw.get(field) if field else None

    raw_author = get(field_map.get("author_field") or None)
    author: dict[str, Any] | None = None
    if isinstance(raw_author, str):
        author = {"name": raw_author}
    elif isinstance(raw_author, dict):
        author = {
            "name": _as_string(raw_author.get("display_name") or raw_author.get("name") or raw_author.get("username") or raw_author.get("handle") or "Unknown"),
        }
        if raw_author.get("handle") or raw_author.get("username"):
            author["handle"] = _as_string(raw_author.get("handle") or raw_author.get("username"))
        if raw_author.get("bio"):
            author["bio"] = _as_string(raw_author.get("bio"))

    known_fields = {
        field_map["id_field"],
        field_map["content_field"],
        field_map["title_field"],
        field_map["tags_field"],
        field_map["author_field"],
        field_map["date_field"],
        field_map["url_field"],
    }
    known_fields.discard("")

    metadata: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in known_fields:
            metadata[key] = value

    raw_tags = get(field_map["tags_field"])
    if isinstance(raw_tags, list):
        tags = [_as_string(tag) for tag in raw_tags]
    elif raw_tags is None:
        tags = []
    else:
        tags = [_as_string(raw_tags)]

    content = _as_string(get(field_map["content_field"]))
    title = _as_string(get(field_map["title_field"]))

    return {
        "id": _as_string(get(field_map["id_field"]) or f"item_{index}"),
        "title": title,
        "content": content,
        "url": get(field_map["url_field"]) if field_map["url_field"] else None,
        "date": get(field_map["date_field"]) if field_map["date_field"] else None,
        "author": author,
        "tags": tags,
        "metadata": metadata,
    }


def load_collection(file_path: str, name: str | None = None, field_overrides: dict[str, str] | None = None) -> dict[str, Any]:
    abs_path = Path(file_path).expanduser().resolve()
    raw = json.loads(abs_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Collection root must be a JSON object")

    field_map = _detect_field_map(raw, field_overrides)
    raw_items = raw[field_map["items_key"]]
    if not isinstance(raw_items, list):
        raise ValueError(f'Field "{field_map["items_key"]}" must be an array')

    items = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise ValueError("Collection items must be objects")
        items.append(_normalize_item(raw_item, field_map, index))

    tag_set = sorted({tag for item in items for tag in item["tags"]})
    collection = {
        "name": name or abs_path.stem,
        "file_path": str(abs_path),
        "items": items,
        "field_map": field_map,
        "available_tags": tag_set,
    }
    STORE[collection["name"]] = collection
    return collection


def query_items(
    collection: str | None = None,
    tags: list[str] | None = None,
    search: str | None = None,
    fields: dict[str, str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if collection:
        selected = [STORE.get(collection)] if STORE.get(collection) else []
        if not selected:
            raise ValueError(f'Collection "{collection}" not loaded')
    else:
        selected = list(STORE.values())

    search_lower = search.lower() if search else None
    results: list[dict[str, Any]] = []

    for col in selected:
        if not col:
            continue
        for item in col["items"]:
            if tags:
                item_tags = [tag.lower() for tag in item["tags"]]
                if not any(tag.lower() in item_tags for tag in tags):
                    continue
            if search_lower:
                haystack = f'{item["title"]} {item["content"]} {" ".join(item["tags"])}'.lower()
                if search_lower not in haystack:
                    continue
            if fields:
                matched = True
                for key, value in fields.items():
                    if value.lower() not in _as_string(item["metadata"].get(key)).lower():
                        matched = False
                        break
                if not matched:
                    continue
            results.append(item)
            if len(results) >= limit:
                return results
    return results


def get_items(collection_name: str, item_ids: list[str]) -> list[dict[str, Any]]:
    col = STORE.get(collection_name)
    if not col:
        raise ValueError(f'Collection "{collection_name}" not loaded')
    wanted = set(item_ids)
    return [item for item in col["items"] if item["id"] in wanted]


def list_collections() -> list[dict[str, Any]]:
    return [
        {
            "name": col["name"],
            "item_count": len(col["items"]),
            "available_tags": col["available_tags"],
            "field_map": col["field_map"],
        }
        for col in STORE.values()
    ]


def _build_cross_references(source_groups: list[dict[str, Any]]) -> str:
    all_items = [item for group in source_groups for item in group["items"]]
    if len(all_items) < 2:
        return ""

    sections: list[str] = ["## Cross-Reference Analysis"]

    tag_counts = Counter(tag for item in all_items for tag in item["tags"])
    shared_tags = sorted(((tag, count) for tag, count in tag_counts.items() if count >= 2), key=lambda pair: pair[1], reverse=True)
    if shared_tags:
        sections.append("\n**Recurring tags:**")
        sections.extend(f"- {tag} ({count} items)" for tag, count in shared_tags)

    meta_freq: dict[str, Counter[str]] = defaultdict(Counter)
    for item in all_items:
        for key, value in item["metadata"].items():
            if isinstance(value, str):
                meta_freq[key][value] += 1

    for field, counts in meta_freq.items():
        ordered = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
        if len(ordered) >= 2 and any(count >= 2 for _, count in ordered):
            sections.append(f"\n**{field} distribution:**")
            sections.extend(f"- {value} ({count})" for value, count in ordered[:10])

    dep_counts: Counter[str] = Counter()
    for item in all_items:
        deps = item["metadata"].get("dependencies")
        if isinstance(deps, list):
            dep_counts.update(_as_string(dep) for dep in deps)
    shared_deps = sorted(((dep, count) for dep, count in dep_counts.items() if count >= 2), key=lambda pair: pair[1], reverse=True)
    if shared_deps:
        sections.append("\n**Common dependencies:**")
        sections.extend(f"- {dep} ({count} items)" for dep, count in shared_deps)

    return "\n".join(sections) if len(sections) > 1 else ""


def collect_concepts(
    source_groups: list[dict[str, Any]],
    title: str,
    focus: str | None = None,
    depth: str = "standard",
) -> tuple[dict[str, Any], str]:
    overview_id = secrets.token_hex(4)
    created_date = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

    sources: list[dict[str, str]] = []
    for group in source_groups:
        for item in group["items"]:
            sources.append(
                {
                    "collection": group["collection"],
                    "item_id": item["id"],
                    "title": item["title"] or item["content"][:80],
                }
            )

    source_sections: list[str] = []
    for group in source_groups:
        source_sections.append(f"\n## Collection: {group['collection']}\n")
        for item in group["items"]:
            parts = [f"### [{item['id']}] {item['title'] or '(untitled)'}"]
            author = item.get("author")
            if isinstance(author, dict):
                handle = f" (@{author['handle']})" if author.get("handle") else ""
                parts.append(f"Author: {author['name']}{handle}")
                if author.get("bio"):
                    parts.append(f"Bio: {author['bio']}")
            if item.get("date"):
                parts.append(f"Date: {item['date']}")
            if item.get("url"):
                parts.append(f"URL: {item['url']}")
            if item["tags"]:
                parts.append(f"Tags: {', '.join(item['tags'])}")
            parts.append("")
            parts.append(item["content"])
            meta_keys = [
                key
                for key, value in item["metadata"].items()
                if isinstance(value, (str, int, float, bool)) or isinstance(value, list)
            ]
            if meta_keys:
                parts.append("")
                parts.append("Metadata:")
                for key in meta_keys:
                    value = item["metadata"][key]
                    formatted = ", ".join(_as_string(entry) for entry in value) if isinstance(value, list) else _as_string(value)
                    parts.append(f"  {key}: {formatted}")
            source_sections.append("\n".join(parts))

    template = {
        "overview_id": overview_id,
        "title": title,
        "created_date": created_date,
        "status": "draft",
        "sources": sources,
        "summary": "",
        "concepts": [],
        "themes": [],
        "key_findings": [],
        "knowledge_gaps": [],
        "open_questions": [],
    }

    depth_instructions = {
        "brief": "Extract 3-5 top-level concepts. Keep descriptions concise (1-2 sentences each). Identify 1-2 major themes. List 3-5 key findings.",
        "standard": "Extract all distinct concepts with clear descriptions and key details. Group into logical themes. Identify relationships between concepts. List key findings and any knowledge gaps.",
        "deep": "Extract every distinct concept, technique, and pattern with thorough descriptions. Include implementation details, edge cases, and nuances in key_details. Map all relationships between concepts. Identify dependencies and prerequisites. List comprehensive findings, knowledge gaps, and open questions worth investigating.",
    }
    focus_clause = (
        f"\n\nFocus area: {focus} - prioritize concepts and findings related to this focus, but do not exclude other salient content."
        if focus
        else ""
    )
    cross_ref = _build_cross_references(source_groups)

    prompt = "\n".join(
        [
            "# Concepts Collection Task",
            "",
            f"**Title:** {title}",
            f"**Depth:** {depth}{focus_clause}",
            "",
            "## Instructions",
            "",
            "Analyze the source material below and produce a structured knowledge overview.",
            depth_instructions.get(depth, depth_instructions["standard"]),
            "",
            "For each concept extracted:",
            "- **name**: Clear, specific name for the concept",
            "- **category**: Broad category (e.g., \"strategy\", \"technique\", \"architecture\", \"data source\", \"risk management\")",
            "- **description**: What this concept is and why it matters",
            "- **key_details**: Specific details, numbers, parameters, or implementation notes",
            "- **source_items**: Which source item IDs contributed to this concept",
            "- **relationships**: How this concept relates to other concepts you've identified",
            "",
            "For themes:",
            "- Group related concepts under broader themes",
            "- Each theme should have a clear description of what unifies its concepts",
            "",
            cross_ref,
            "",
            "## Source Material",
            "",
            "\n\n---\n\n".join(source_sections),
            "",
            "## Output",
            "",
            "Fill in the following JSON template. Return ONLY the completed JSON - no surrounding text.",
            "",
            "```json",
            json.dumps(template, indent=2),
            "```",
        ]
    )

    return template, prompt


def _save_overview(overview: dict[str, Any], output_dir: str | None = None) -> Path:
    directory = Path(output_dir).expanduser().resolve() if output_dir else _output_dir()
    directory.mkdir(parents=True, exist_ok=True)
    title_slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in overview["title"]).strip("-")
    title_slug = "-".join(part for part in title_slug.split("-") if part)[:60]
    file_path = directory / f"{title_slug}--{overview['overview_id'][:8]}.json"
    overview["updated_date"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
    file_path.write_text(json.dumps(overview, indent=2), encoding="utf-8")
    return file_path


def _list_overviews(directory: str | None = None) -> list[dict[str, Any]]:
    dir_path = Path(directory).expanduser().resolve() if directory else _output_dir()
    if not dir_path.exists():
        return []
    results: list[dict[str, Any]] = []
    for file_path in sorted(dir_path.glob("*.json")):
        try:
            overview = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(overview, dict) or "overview_id" not in overview:
            continue
        results.append(
            {
                "overview_id": overview.get("overview_id", ""),
                "title": overview.get("title", ""),
                "created_date": overview.get("created_date", ""),
                "status": overview.get("status", ""),
                "concept_count": len(overview.get("concepts", []) or []),
                "source_count": len(overview.get("sources", []) or []),
                "file": str(file_path),
            }
        )
    return results


def _get_overview(overview_id: str, directory: str | None = None) -> dict[str, Any] | None:
    dir_path = Path(directory).expanduser().resolve() if directory else _output_dir()
    if not dir_path.exists():
        return None
    for file_path in sorted(dir_path.glob("*.json")):
        try:
            overview = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(overview, dict) and overview.get("overview_id") == overview_id:
            return overview
    return None


@mcp.tool()
def cc_load_collection(file_path: str, name: str | None = None, field_overrides: dict[str, str] | None = None) -> str:
    col = load_collection(file_path, name, field_overrides)
    lines = [
        f'Loaded collection "{col["name"]}"',
        f'  Items: {len(col["items"])}',
        f'  Source: {col["file_path"]}',
        "  Field map:",
        f'    items_key: {col["field_map"]["items_key"]}',
        f'    id: {col["field_map"]["id_field"]}',
        f'    content: {col["field_map"]["content_field"]}',
        f'    title: {col["field_map"]["title_field"]}',
        f'    tags: {col["field_map"]["tags_field"]}',
    ]
    if col["field_map"]["author_field"]:
        lines.append(f'    author: {col["field_map"]["author_field"]}')
    if col["field_map"]["date_field"]:
        lines.append(f'    date: {col["field_map"]["date_field"]}')
    if col["field_map"]["url_field"]:
        lines.append(f'    url: {col["field_map"]["url_field"]}')
    lines.extend(["", f'  Available tags ({len(col["available_tags"])}):', f'    {", ".join(col["available_tags"])}'])
    return "\n".join(lines)


@mcp.tool()
def cc_query(
    collection: str | None = None,
    tags: list[str] | None = None,
    search: str | None = None,
    fields: dict[str, str] | None = None,
    limit: int = 20,
) -> str:
    results = query_items(collection, tags, search, fields, limit)
    if not results:
        return "No items matched the query."
    lines = [f"Found {len(results)} item(s):", ""]
    for item in results:
        preview = item["content"][:200] + ("..." if len(item["content"]) > 200 else "")
        lines.append(f'[{item["id"]}] {item["title"] or "(untitled)"}')
        if item.get("author"):
            lines.append(f'  Author: {item["author"]["name"]}')
        if item["tags"]:
            lines.append(f'  Tags: {", ".join(item["tags"])}')
        lines.append(f"  {preview}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def cc_get_items(collection: str, item_ids: list[str]) -> str:
    if not collection or not item_ids:
        raise ValueError("collection and item_ids are required")
    items = get_items(collection, item_ids)
    if not items:
        return f'No items found with the given IDs in "{collection}".'
    lines: list[str] = []
    for item in items:
        lines.append(f'=== [{item["id"]}] {item["title"] or "(untitled)"} ===')
        if item.get("author"):
            author = item["author"]
            handle = f' (@{author["handle"]})' if author.get("handle") else ""
            lines.append(f'Author: {author["name"]}{handle}')
        if item.get("date"):
            lines.append(f'Date: {item["date"]}')
        if item.get("url"):
            lines.append(f'URL: {item["url"]}')
        if item["tags"]:
            lines.append(f'Tags: {", ".join(item["tags"])}')
        lines.extend(["", item["content"], ""])
    return "\n".join(lines)


@mcp.tool()
def cc_collect_concepts(
    title: str,
    items: list[dict[str, Any]],
    focus: str | None = None,
    depth: str = "standard",
) -> str:
    if not title or not items:
        raise ValueError("title and items are required")

    source_groups = []
    for group in items:
        collection = group.get("collection")
        item_ids = group.get("item_ids") or []
        if not collection or not item_ids:
            raise ValueError("Each item group must include collection and item_ids")
        source_groups.append({"collection": collection, "items": get_items(collection, list(item_ids))})

    if sum(len(group["items"]) for group in source_groups) == 0:
        raise ValueError("No items found for the given IDs")

    _, prompt = collect_concepts(source_groups, title, focus, depth)
    return prompt


@mcp.tool()
def cc_save_overview(overview: dict[str, Any], output_dir: str | None = None) -> str:
    if not overview:
        raise ValueError("overview is required")
    overview = dict(overview)
    overview["status"] = "complete"
    file_path = _save_overview(overview, output_dir)
    return (
        f"Overview saved: {file_path}\n"
        f"  ID: {overview['overview_id']}\n"
        f"  Title: {overview['title']}\n"
        f"  Concepts: {len(overview.get('concepts', []) or [])}\n"
        f"  Themes: {len(overview.get('themes', []) or [])}"
    )


@mcp.tool()
def cc_list_overviews(directory: str | None = None) -> str:
    overviews = _list_overviews(directory)
    if not overviews:
        return "No saved overviews found."
    lines = [f"{len(overviews)} overview(s):", ""]
    for overview in overviews:
        lines.append(f'[{overview["overview_id"]}] {overview["title"]}')
        lines.append(
            f'  Status: {overview["status"]} | Concepts: {overview["concept_count"]} | Sources: {overview["source_count"]}'
        )
        lines.append(f'  Created: {overview["created_date"]}')
        lines.append(f'  File: {overview["file"]}')
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def cc_get_overview(overview_id: str, directory: str | None = None) -> str:
    if not overview_id:
        raise ValueError("overview_id is required")
    overview = _get_overview(overview_id, directory)
    if overview is None:
        raise ValueError(f'Overview "{overview_id}" not found.')
    return json.dumps(overview, indent=2)


def main() -> None:
    print("concepts-collector: MCP server started", file=sys.stderr)
    mcp.run()
