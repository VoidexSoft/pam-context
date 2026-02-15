"""Tool definitions for the retrieval agent."""

from typing import Any

SEARCH_KNOWLEDGE_TOOL: dict[str, Any] = {
    "name": "search_knowledge",
    "description": (
        "Search the business knowledge base for relevant information. "
        "Use this to find definitions, processes, metrics, documentation, and any business knowledge. "
        "Returns relevant text segments with source citations. "
        "Be specific in your query and include key terms."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Be specific and include key terms relevant to the question.",
            },
            "source_type": {
                "type": "string",
                "enum": ["google_doc", "markdown", "google_sheets"],
                "description": "Optional: filter results by source type.",
            },
        },
        "required": ["query"],
    },
}

GET_DOCUMENT_CONTEXT_TOOL = {
    "name": "get_document_context",
    "description": (
        "Fetch the full content of a specific document for deep reading. "
        "Use this when you need the complete context of a document, not just search snippets. "
        "Provide either the document title or source ID."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "document_title": {
                "type": "string",
                "description": "The title of the document to fetch.",
            },
            "source_id": {
                "type": "string",
                "description": "The source ID of the document (e.g. file path or Google Doc ID).",
            },
        },
    },
}

GET_CHANGE_HISTORY_TOOL = {
    "name": "get_change_history",
    "description": (
        "Query the sync log to see recent changes to documents. "
        "Shows what was ingested, updated, or deleted and when. "
        "Useful for answering questions like 'what changed recently?' or 'when was X last updated?'"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "document_title": {
                "type": "string",
                "description": "Optional: filter changes for a specific document title.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of change records to return. Default: 20.",
                "default": 20,
            },
        },
    },
}

QUERY_DATABASE_TOOL = {
    "name": "query_database",
    "description": (
        "Run SQL queries against registered data files (CSV, Parquet, JSON) using DuckDB. "
        "Use this for analytical questions about data: aggregations, filtering, joins, etc. "
        "The query must be read-only SELECT statements. "
        "Available tables are listed in the 'tables' field of the response."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "A read-only SQL SELECT query to execute.",
            },
            "list_tables": {
                "type": "boolean",
                "description": "Set to true to list all available tables and their schemas instead of running a query.",
            },
        },
        "required": ["sql"],
    },
}

SEARCH_ENTITIES_TOOL = {
    "name": "search_entities",
    "description": (
        "Search for structured business entities extracted from documents. "
        "Entities include metric definitions, event tracking specs, and KPI targets. "
        "Use this for precise lookups of business definitions, formulas, and targets."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_type": {
                "type": "string",
                "enum": ["metric_definition", "event_tracking_spec", "kpi_target"],
                "description": "Optional: filter by entity type.",
            },
            "search_term": {
                "type": "string",
                "description": "Search term to match against entity names and data.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return. Default: 10.",
                "default": 10,
            },
        },
        "required": ["search_term"],
    },
}

ALL_TOOLS: list[dict[str, Any]] = [
    SEARCH_KNOWLEDGE_TOOL,
    GET_DOCUMENT_CONTEXT_TOOL,
    GET_CHANGE_HISTORY_TOOL,
    QUERY_DATABASE_TOOL,
    SEARCH_ENTITIES_TOOL,
]
