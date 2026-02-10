"""Tool definitions for the retrieval agent."""

SEARCH_KNOWLEDGE_TOOL = {
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
                "enum": ["google_doc", "markdown"],
                "description": "Optional: filter results by source type.",
            },
        },
        "required": ["query"],
    },
}

ALL_TOOLS = [SEARCH_KNOWLEDGE_TOOL]
