#!/usr/bin/env python3
"""
PAM Context Evaluation Runner

Loads evaluation questions, queries the PAM search and chat APIs,
scores answers using LLM-as-judge, and outputs a summary report.

Usage:
    python eval/run_eval.py
    python eval/run_eval.py --api-url http://localhost:8000 --questions-file eval/questions.json
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))
from judges import score_answer


# ---------------------------------------------------------------------------
# Retrieval evaluation
# ---------------------------------------------------------------------------

async def evaluate_retrieval(
    client: httpx.AsyncClient,
    api_url: str,
    question: str,
    expected_answer: str,
) -> dict:
    """
    Call POST /api/search and check whether results contain content relevant
    to the expected answer.

    Returns a dict with retrieved_chunks, has_relevant_result, and latency_ms.
    """
    start = time.perf_counter()
    try:
        resp = await client.post(
            f"{api_url}/api/search",
            json={"query": question, "top_k": 5},
            timeout=30.0,
        )
        latency_ms = round((time.perf_counter() - start) * 1000, 1)

        if resp.status_code != 200:
            return {
                "retrieved_chunks": [],
                "has_relevant_result": False,
                "latency_ms": latency_ms,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }

        data = resp.json()
        chunks = data.get("results", data.get("chunks", []))

        # Simple relevance heuristic: check if any chunk shares significant
        # keywords with the expected answer (lowercased).
        expected_keywords = set(expected_answer.lower().split())
        # Remove very common words
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "of", "in", "to",
            "and", "or", "for", "on", "at", "by", "with", "from", "that",
            "this", "it", "as", "be", "has", "have", "had", "not", "but",
            "all", "each", "which", "their", "if", "will", "can", "do",
        }
        expected_keywords -= stopwords

        has_relevant = False
        for chunk in chunks:
            chunk_text = ""
            if isinstance(chunk, dict):
                chunk_text = chunk.get("content", chunk.get("text", str(chunk)))
            else:
                chunk_text = str(chunk)

            chunk_words = set(chunk_text.lower().split())
            overlap = expected_keywords & chunk_words
            # Consider relevant if >= 20% keyword overlap
            if len(overlap) >= max(1, len(expected_keywords) * 0.2):
                has_relevant = True
                break

        return {
            "retrieved_chunks": len(chunks),
            "has_relevant_result": has_relevant,
            "latency_ms": latency_ms,
        }

    except httpx.RequestError as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return {
            "retrieved_chunks": 0,
            "has_relevant_result": False,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Agent / chat evaluation
# ---------------------------------------------------------------------------

async def evaluate_agent(
    client: httpx.AsyncClient,
    api_url: str,
    question: str,
) -> dict:
    """
    Call POST /api/chat and capture the agent's answer.

    Returns a dict with answer text and latency_ms.
    """
    start = time.perf_counter()
    try:
        resp = await client.post(
            f"{api_url}/api/chat",
            json={"message": question},
            timeout=60.0,
        )
        latency_ms = round((time.perf_counter() - start) * 1000, 1)

        if resp.status_code != 200:
            return {
                "answer": "",
                "latency_ms": latency_ms,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }

        data = resp.json()
        # Backend returns { response: str, citations: [...] } or
        # potentially { message: { role, content, citations } }.
        # Handle both structures safely.
        answer = data.get("answer", data.get("response", ""))
        if not answer:
            message = data.get("message", {})
            answer = message.get("content", "") if isinstance(message, dict) else str(message)
        return {"answer": answer, "latency_ms": latency_ms}

    except httpx.RequestError as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return {
            "answer": "",
            "latency_ms": latency_ms,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

async def run_evaluation(api_url: str, questions_file: str) -> dict:
    """Run the full evaluation pipeline and return results."""

    questions_path = Path(questions_file)
    if not questions_path.exists():
        print(f"Error: questions file not found at {questions_path}")
        sys.exit(1)

    with open(questions_path) as f:
        questions = json.load(f)

    print(f"Loaded {len(questions)} evaluation questions from {questions_path}")
    print(f"API URL: {api_url}")
    print("-" * 72)

    results = []

    async with httpx.AsyncClient() as client:
        for i, q in enumerate(questions):
            qid = q["id"]
            question = q["question"]
            expected = q["expected_answer"]
            difficulty = q.get("difficulty", "unknown")

            print(f"\n[{i+1}/{len(questions)}] {qid} ({difficulty}): {question}")

            # Step 1: Retrieval evaluation
            print("  -> Searching...")
            retrieval = await evaluate_retrieval(client, api_url, question, expected)
            relevant = retrieval["has_relevant_result"]
            print(
                f"     Retrieval: {retrieval['retrieved_chunks']} chunks, "
                f"relevant={relevant}, {retrieval['latency_ms']}ms"
            )
            if "error" in retrieval:
                print(f"     Retrieval error: {retrieval['error']}")

            # Step 2: Agent evaluation
            print("  -> Asking agent...")
            agent_result = await evaluate_agent(client, api_url, question)
            answer = agent_result.get("answer", "")
            print(
                f"     Agent: {len(answer)} chars, "
                f"{agent_result['latency_ms']}ms"
            )
            if "error" in agent_result:
                print(f"     Agent error: {agent_result['error']}")

            # Step 3: LLM-as-judge scoring
            judge_scores = {
                "factual_accuracy": 0.0,
                "citation_presence": 0.0,
                "completeness": 0.0,
                "average_score": 0.0,
                "reasoning": "No answer to score",
            }
            if answer:
                print("  -> Scoring with LLM judge...")
                try:
                    judge_scores = await score_answer(question, expected, answer)
                    print(
                        f"     Scores: accuracy={judge_scores['factual_accuracy']:.2f}, "
                        f"citation={judge_scores['citation_presence']:.2f}, "
                        f"completeness={judge_scores['completeness']:.2f}, "
                        f"avg={judge_scores['average_score']:.2f}"
                    )
                except Exception as exc:
                    print(f"     Judge error: {exc}")
                    judge_scores["reasoning"] = f"Judge error: {exc}"

            results.append({
                "id": qid,
                "question": question,
                "difficulty": difficulty,
                "retrieval": retrieval,
                "agent_answer": answer[:500],  # truncate for report
                "scores": judge_scores,
            })

    return {"questions": results}


def print_summary(eval_results: dict) -> None:
    """Print a formatted summary report."""
    questions = eval_results["questions"]
    total = len(questions)

    print("\n" + "=" * 72)
    print("EVALUATION SUMMARY")
    print("=" * 72)

    # Retrieval recall
    relevant_count = sum(
        1 for q in questions if q["retrieval"]["has_relevant_result"]
    )
    retrieval_errors = sum(1 for q in questions if "error" in q["retrieval"])
    avg_retrieval_latency = (
        sum(q["retrieval"]["latency_ms"] for q in questions) / total
        if total
        else 0
    )

    print(f"\n--- Retrieval Recall ---")
    print(f"  Relevant results found: {relevant_count}/{total} ({relevant_count/total*100:.0f}%)")
    print(f"  Retrieval errors:       {retrieval_errors}/{total}")
    print(f"  Avg retrieval latency:  {avg_retrieval_latency:.0f}ms")

    # Answer quality scores
    scored = [q for q in questions if q["scores"]["average_score"] > 0]
    if scored:
        avg_accuracy = sum(q["scores"]["factual_accuracy"] for q in scored) / len(scored)
        avg_citation = sum(q["scores"]["citation_presence"] for q in scored) / len(scored)
        avg_completeness = sum(q["scores"]["completeness"] for q in scored) / len(scored)
        avg_overall = sum(q["scores"]["average_score"] for q in scored) / len(scored)
    else:
        avg_accuracy = avg_citation = avg_completeness = avg_overall = 0.0

    print(f"\n--- Answer Quality (LLM Judge) ---")
    print(f"  Scored answers:     {len(scored)}/{total}")
    print(f"  Factual accuracy:   {avg_accuracy:.2f}")
    print(f"  Citation presence:  {avg_citation:.2f}")
    print(f"  Completeness:       {avg_completeness:.2f}")
    print(f"  Overall average:    {avg_overall:.2f}")

    # By difficulty
    print(f"\n--- By Difficulty ---")
    for diff in ["simple", "medium", "complex"]:
        diff_qs = [q for q in scored if q["difficulty"] == diff]
        if diff_qs:
            diff_avg = sum(q["scores"]["average_score"] for q in diff_qs) / len(diff_qs)
            print(f"  {diff:>8s}: {diff_avg:.2f} avg ({len(diff_qs)} questions)")
        else:
            print(f"  {diff:>8s}: no scored answers")

    # Per-question breakdown
    print(f"\n--- Per-Question Breakdown ---")
    print(f"  {'ID':<6} {'Diff':<8} {'Retr':>4} {'Acc':>5} {'Cite':>5} {'Comp':>5} {'Avg':>5}  Question")
    print(f"  {'-'*6} {'-'*8} {'-'*4} {'-'*5} {'-'*5} {'-'*5} {'-'*5}  {'-'*30}")
    for q in questions:
        retr = "Y" if q["retrieval"]["has_relevant_result"] else "N"
        s = q["scores"]
        print(
            f"  {q['id']:<6} {q['difficulty']:<8} {retr:>4} "
            f"{s['factual_accuracy']:>5.2f} {s['citation_presence']:>5.2f} "
            f"{s['completeness']:>5.2f} {s['average_score']:>5.2f}  "
            f"{q['question'][:40]}"
        )

    print("\n" + "=" * 72)


def main():
    parser = argparse.ArgumentParser(
        description="PAM Context Evaluation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("PAM_API_URL", "http://localhost:8000"),
        help="Base URL of the PAM API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--questions-file",
        default=str(Path(__file__).resolve().parent / "questions.json"),
        help="Path to the evaluation questions JSON file",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to save the full results JSON (optional)",
    )
    args = parser.parse_args()

    results = asyncio.run(run_evaluation(args.api_url, args.questions_file))

    print_summary(results)

    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nFull results saved to {output_path}")


if __name__ == "__main__":
    main()
