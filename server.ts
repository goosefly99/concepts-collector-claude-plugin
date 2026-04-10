import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from '@modelcontextprotocol/sdk/types.js'

import {
  loadCollection,
  queryItems,
  getItems,
  listCollections,
} from './collections.ts'

import {
  collectConcepts,
  saveOverview,
  listOverviews,
  getOverview,
} from './concepts.ts'

import type { KnowledgeOverview } from './types.ts'

// ── Server setup ────────────────────────────────────────────────

const server = new Server(
  { name: 'concepts-collector', version: '0.1.0' },
  {
    capabilities: { tools: {} },
    instructions:
      'Research concepts collector MCP server. Load JSON research collections, ' +
      'extract key concepts across items, and generate structured knowledge base overviews. ' +
      'Workflow: cc_load_collection → cc_query / cc_get_items → cc_collect_concepts → cc_save_overview.',
  },
)

// ── Tool definitions ────────────────────────────────────────────

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'cc_load_collection',
      description:
        'Load a JSON research collection with auto-detected schema mapping. ' +
        'Accepts any JSON file with an array of items — field mapping is inferred automatically. ' +
        'Returns collection summary with item count, detected fields, and available tags.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          file_path: {
            type: 'string',
            description: 'Path to the JSON file to load',
          },
          name: {
            type: 'string',
            description: 'Name for this collection (defaults to filename)',
          },
          field_overrides: {
            type: 'object',
            description:
              'Override auto-detected field mappings. Keys: items_key, id_field, content_field, title_field, tags_field, author_field, date_field, url_field',
          },
        },
        required: ['file_path'],
      },
    },
    {
      name: 'cc_query',
      description:
        'Search and filter items across loaded collections. ' +
        'Filter by tags, full-text search, or metadata field values. ' +
        'Returns matching items with truncated content previews.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          collection: {
            type: 'string',
            description: 'Collection name to search (omit to search all)',
          },
          tags: {
            type: 'array',
            items: { type: 'string' },
            description: 'Filter items that have any of these tags',
          },
          search: {
            type: 'string',
            description: 'Full-text search term',
          },
          fields: {
            type: 'object',
            description: 'Filter by metadata fields (e.g., {"strategy_type": "arbitrage"})',
          },
          limit: {
            type: 'number',
            description: 'Max results to return (default 20)',
          },
        },
      },
    },
    {
      name: 'cc_get_items',
      description:
        'Get the full content of specific items by ID from a collection. ' +
        'Use after cc_query to retrieve complete item data.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          collection: {
            type: 'string',
            description: 'Collection name',
          },
          item_ids: {
            type: 'array',
            items: { type: 'string' },
            description: 'Array of item IDs to retrieve',
          },
        },
        required: ['collection', 'item_ids'],
      },
    },
    {
      name: 'cc_collect_concepts',
      description:
        'Extract and organize key concepts from selected research items into a structured ' +
        'knowledge base overview. Accepts items from multiple collections. Returns a synthesis ' +
        'prompt with all source material, cross-reference analysis, and a knowledge overview ' +
        'template for you to complete.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          title: {
            type: 'string',
            description: 'Title for the knowledge overview',
          },
          items: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                collection: { type: 'string' },
                item_ids: {
                  type: 'array',
                  items: { type: 'string' },
                },
              },
              required: ['collection', 'item_ids'],
            },
            description: 'Items to analyze, grouped by collection',
          },
          focus: {
            type: 'string',
            description: 'Optional focus area to prioritize in the analysis',
          },
          depth: {
            type: 'string',
            enum: ['brief', 'standard', 'deep'],
            description: 'Analysis depth: brief (3-5 concepts), standard (all concepts), deep (exhaustive with relationships)',
          },
        },
        required: ['title', 'items'],
      },
    },
    {
      name: 'cc_save_overview',
      description:
        'Save a completed knowledge overview to disk. ' +
        'Pass the filled-in overview JSON from cc_collect_concepts.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          overview: {
            type: 'object',
            description: 'The completed KnowledgeOverview JSON object',
          },
          output_dir: {
            type: 'string',
            description: 'Directory to save to (defaults to ./overviews/)',
          },
        },
        required: ['overview'],
      },
    },
    {
      name: 'cc_list_overviews',
      description:
        'List all saved knowledge overviews with their metadata.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          directory: {
            type: 'string',
            description: 'Directory to list from (defaults to ./overviews/)',
          },
        },
      },
    },
    {
      name: 'cc_get_overview',
      description:
        'Retrieve a previously saved knowledge overview by its ID.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          overview_id: {
            type: 'string',
            description: 'The overview ID to retrieve',
          },
          directory: {
            type: 'string',
            description: 'Directory to search (defaults to ./overviews/)',
          },
        },
        required: ['overview_id'],
      },
    },
  ],
}))

// ── Tool handlers ───────────────────────────────────────────────

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const args = (req.params.arguments ?? {}) as Record<string, unknown>
  try {
    switch (req.params.name) {
      case 'cc_load_collection':
        return handleLoadCollection(args)
      case 'cc_query':
        return handleQuery(args)
      case 'cc_get_items':
        return handleGetItems(args)
      case 'cc_collect_concepts':
        return handleCollectConcepts(args)
      case 'cc_save_overview':
        return handleSaveOverview(args)
      case 'cc_list_overviews':
        return handleListOverviews(args)
      case 'cc_get_overview':
        return handleGetOverview(args)
      default:
        return {
          content: [{ type: 'text' as const, text: `Unknown tool: ${req.params.name}` }],
          isError: true,
        }
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return {
      content: [{ type: 'text' as const, text: `${req.params.name} failed: ${msg}` }],
      isError: true,
    }
  }
})

// ── Handler implementations ─────────────────────────────────────

function handleLoadCollection(args: Record<string, unknown>) {
  const filePath = args.file_path as string
  if (!filePath) throw new Error('file_path is required')

  const col = loadCollection(
    filePath,
    args.name as string | undefined,
    args.field_overrides as Record<string, string> | undefined,
  )

  const lines = [
    `Loaded collection "${col.name}"`,
    `  Items: ${col.items.length}`,
    `  Source: ${col.file_path}`,
    `  Field map:`,
    `    items_key: ${col.field_map.items_key}`,
    `    id: ${col.field_map.id_field}`,
    `    content: ${col.field_map.content_field}`,
    `    title: ${col.field_map.title_field}`,
    `    tags: ${col.field_map.tags_field}`,
    col.field_map.author_field ? `    author: ${col.field_map.author_field}` : '',
    col.field_map.date_field ? `    date: ${col.field_map.date_field}` : '',
    col.field_map.url_field ? `    url: ${col.field_map.url_field}` : '',
    '',
    `  Available tags (${col.available_tags.length}):`,
    `    ${col.available_tags.join(', ')}`,
  ]

  return { content: [{ type: 'text' as const, text: lines.filter(Boolean).join('\n') }] }
}

function handleQuery(args: Record<string, unknown>) {
  const results = queryItems({
    collection: args.collection as string | undefined,
    tags: args.tags as string[] | undefined,
    search: args.search as string | undefined,
    fields: args.fields as Record<string, string> | undefined,
    limit: args.limit as number | undefined,
  })

  if (results.length === 0) {
    return { content: [{ type: 'text' as const, text: 'No items matched the query.' }] }
  }

  const lines = [`Found ${results.length} item(s):\n`]
  for (const item of results) {
    const preview = item.content.length > 200
      ? item.content.slice(0, 200) + '...'
      : item.content
    lines.push(`[${item.id}] ${item.title || '(untitled)'}`)
    if (item.author) lines.push(`  Author: ${item.author.name}`)
    if (item.tags.length > 0) lines.push(`  Tags: ${item.tags.join(', ')}`)
    lines.push(`  ${preview}`)
    lines.push('')
  }

  return { content: [{ type: 'text' as const, text: lines.join('\n') }] }
}

function handleGetItems(args: Record<string, unknown>) {
  const collection = args.collection as string
  const itemIds = args.item_ids as string[]
  if (!collection || !itemIds) throw new Error('collection and item_ids are required')

  const items = getItems(collection, itemIds)

  if (items.length === 0) {
    return {
      content: [{ type: 'text' as const, text: `No items found with the given IDs in "${collection}".` }],
    }
  }

  const lines: string[] = []
  for (const item of items) {
    lines.push(`=== [${item.id}] ${item.title || '(untitled)'} ===`)
    if (item.author) {
      lines.push(`Author: ${item.author.name}${item.author.handle ? ` (@${item.author.handle})` : ''}`)
    }
    if (item.date) lines.push(`Date: ${item.date}`)
    if (item.url) lines.push(`URL: ${item.url}`)
    if (item.tags.length > 0) lines.push(`Tags: ${item.tags.join(', ')}`)
    lines.push('', item.content, '')
  }

  return { content: [{ type: 'text' as const, text: lines.join('\n') }] }
}

function handleCollectConcepts(args: Record<string, unknown>) {
  const title = args.title as string
  const itemGroups = args.items as { collection: string; item_ids: string[] }[]
  if (!title || !itemGroups) throw new Error('title and items are required')

  // Resolve items from each collection
  const sourceGroups = itemGroups.map((group) => ({
    collection: group.collection,
    items: getItems(group.collection, group.item_ids),
  }))

  const totalItems = sourceGroups.reduce((sum, g) => sum + g.items.length, 0)
  if (totalItems === 0) throw new Error('No items found for the given IDs')

  const { synthesis_prompt } = collectConcepts(sourceGroups, {
    title,
    focus: args.focus as string | undefined,
    depth: args.depth as 'brief' | 'standard' | 'deep' | undefined,
  })

  return { content: [{ type: 'text' as const, text: synthesis_prompt }] }
}

function handleSaveOverview(args: Record<string, unknown>) {
  const overview = args.overview as KnowledgeOverview
  if (!overview) throw new Error('overview is required')

  overview.status = 'complete'
  const filePath = saveOverview(overview, args.output_dir as string | undefined)

  return {
    content: [{
      type: 'text' as const,
      text: `Overview saved: ${filePath}\n  ID: ${overview.overview_id}\n  Title: ${overview.title}\n  Concepts: ${overview.concepts?.length ?? 0}\n  Themes: ${overview.themes?.length ?? 0}`,
    }],
  }
}

function handleListOverviews(args: Record<string, unknown>) {
  const overviews = listOverviews(args.directory as string | undefined)

  if (overviews.length === 0) {
    return { content: [{ type: 'text' as const, text: 'No saved overviews found.' }] }
  }

  const lines = [`${overviews.length} overview(s):\n`]
  for (const o of overviews) {
    lines.push(`[${o.overview_id}] ${o.title}`)
    lines.push(`  Status: ${o.status} | Concepts: ${o.concept_count} | Sources: ${o.source_count}`)
    lines.push(`  Created: ${o.created_date}`)
    lines.push(`  File: ${o.file}`)
    lines.push('')
  }

  return { content: [{ type: 'text' as const, text: lines.join('\n') }] }
}

function handleGetOverview(args: Record<string, unknown>) {
  const overviewId = args.overview_id as string
  if (!overviewId) throw new Error('overview_id is required')

  const overview = getOverview(overviewId, args.directory as string | undefined)
  if (!overview) {
    return {
      content: [{ type: 'text' as const, text: `Overview "${overviewId}" not found.` }],
      isError: true,
    }
  }

  return {
    content: [{ type: 'text' as const, text: JSON.stringify(overview, null, 2) }],
  }
}

// ── Connect transport ───────────────────────────────────────────

const transport = new StdioServerTransport()
await server.connect(transport)

process.stderr.write('concepts-collector: MCP server started\n')

// ── Graceful shutdown ───────────────────────────────────────────

process.on('SIGTERM', () => process.exit(0))
process.on('SIGINT', () => process.exit(0))
process.on('unhandledRejection', (err: unknown) => {
  process.stderr.write(`concepts-collector: unhandled rejection: ${err}\n`)
})
process.on('uncaughtException', (err: Error) => {
  process.stderr.write(`concepts-collector: uncaught exception: ${err}\n`)
})
