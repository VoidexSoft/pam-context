"""Prompt templates for multimodal content analysis."""

IMAGE_ANALYSIS_SYSTEM = (
    "You are a document analysis assistant specialized in interpreting "
    "images found in business documents. Provide accurate, structured descriptions."
)

IMAGE_ANALYSIS_PROMPT = """Analyze this image from a document and provide a structured description.

Context from surrounding text:
{context}

Provide your analysis as a JSON object with these fields:
- "description": A detailed description of the image content
- "key_elements": A list of key elements or objects in the image
- "relevance": How this image relates to the surrounding text context

Output JSON only, no other text."""

TABLE_ANALYSIS_SYSTEM = (
    "You are a document analysis assistant specialized in interpreting "
    "tables found in business documents. Provide accurate, structured analysis."
)

TABLE_ANALYSIS_PROMPT = """Analyze this table from a document and provide a structured summary.

Context from surrounding text:
{context}

Table content (markdown):
{table_body}

Provide your analysis as a JSON object with these fields:
- "summary": A concise summary of what the table shows
- "key_findings": A list of important data points or trends
- "column_descriptions": Brief description of what each column represents

Output JSON only, no other text."""

IMAGE_CHUNK_TEMPLATE = """[Image: {description}]

Key elements: {key_elements}

Relevance: {relevance}"""

TABLE_CHUNK_TEMPLATE = """[Table Summary: {summary}]

Key findings: {key_findings}

{table_body}"""
