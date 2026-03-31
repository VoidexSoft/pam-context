#!/usr/bin/env python3
"""Generate synthetic Q&A evaluation pairs from ingested documents.

Reads documents from the PAM API and uses Claude to generate question-answer
pairs suitable for evaluation.

Usage:
    python eval/synthetic_gen.py --api-url http://localhost:8000 --count 50
"""

import argparse
import asyncio
import json
import os
import random
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judges import get_client


GENERATION_PROMPT = """\
You are an expert at creating evaluation question-answer pairs for a business knowledge Q&A system.

Given a text chunk from a document, generate a question that:
1. Can be answered using ONLY the information in the chunk
2. Tests understanding, not just keyword matching
3. Varies in difficulty (simple factual recall, medium synthesis, complex reasoning)

Respond ONLY with a JSON object:
{
  "question": "<natural question a business user would ask>",
  "expected_answer": "<complete answer derived from the chunk>",
  "difficulty": "<simple|medium|complex>"
}
"""


def build_prompt_for_chunk(chunk_text: str, document_title: str) -> str:
    """Build the user prompt for Q&A generation from a chunk."""
    return (
        f"## Document: {document_title}\n\n"
        f"## Text Chunk\n{chunk_text}\n\n"
        "Generate a question-answer pair from this chunk."
    )


async def generate_qa_pair(
    chunk_text: str,
    document_title: str,
    model: str = "claude-sonnet-4-5-20250514",
) -> dict:
    """Generate a single Q&A pair from a document chunk."""
    client = get_client()

    response = await client.messages.create(
        model=model,
        max_tokens=512,
        system=GENERATION_PROMPT,
        messages=[{"role": "user", "content": build_prompt_for_chunk(chunk_text, document_title)}],
    )

    raw_text = response.content[0].text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"question": "", "expected_answer": "", "difficulty": "simple", "error": raw_text[:200]}


async def fetch_chunks(api_url: str, sample_size: int = 50) -> list[dict]:
    """Fetch document chunks from the PAM API for generation."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{api_url}/api/documents", timeout=30.0)
        if resp.status_code != 200:
            print(f"Error fetching documents: {resp.status_code}")
            return []

        documents = resp.json()
        if isinstance(documents, dict):
            documents = documents.get("items", documents.get("documents", []))

        chunks = []
        for doc in documents:
            doc_id = doc.get("id")
            if not doc_id:
                continue
            resp = await client.get(f"{api_url}/api/documents/{doc_id}", timeout=30.0)
            if resp.status_code == 200:
                doc_data = resp.json()
                segments = doc_data.get("segments", [])
                for seg in segments:
                    content = seg.get("content", "")
                    if len(content) > 100:
                        chunks.append({
                            "content": content,
                            "document_title": doc.get("title", "Unknown"),
                        })

        if len(chunks) > sample_size:
            chunks = random.sample(chunks, sample_size)

        return chunks


async def generate_dataset(api_url: str, count: int, output_path: str) -> None:
    """Generate a synthetic evaluation dataset."""
    print(f"Fetching chunks from {api_url}...")
    chunks = await fetch_chunks(api_url, sample_size=count)

    if not chunks:
        print("No chunks found. Make sure documents are ingested.")
        return

    print(f"Generating {len(chunks)} Q&A pairs...")
    questions = []

    for i, chunk in enumerate(chunks):
        print(f"  [{i + 1}/{len(chunks)}] Generating from: {chunk['document_title'][:40]}...")
        qa = await generate_qa_pair(chunk["content"], chunk["document_title"])
        if qa.get("question") and qa.get("expected_answer"):
            qa["id"] = f"syn_{i + 1:03d}"
            qa["source_document"] = chunk["document_title"]
            questions.append(qa)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(questions, f, indent=2)

    print(f"\nGenerated {len(questions)} Q&A pairs -> {out}")


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic eval questions from ingested docs")
    parser.add_argument("--api-url", default=os.environ.get("PAM_API_URL", "http://localhost:8000"))
    parser.add_argument("--count", type=int, default=50, help="Number of Q&A pairs to generate")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent / "datasets" / "synthetic_questions.json"),
    )
    args = parser.parse_args()

    asyncio.run(generate_dataset(args.api_url, args.count, args.output))


if __name__ == "__main__":
    main()
