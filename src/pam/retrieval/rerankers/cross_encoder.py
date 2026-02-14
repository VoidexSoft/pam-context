"""Self-hosted cross-encoder reranker using sentence-transformers."""

from __future__ import annotations

import asyncio
from functools import lru_cache

import structlog

from pam.retrieval.rerankers.base import BaseReranker
from pam.retrieval.types import SearchResult

logger = structlog.get_logger()


@lru_cache(maxsize=1)
def _load_model(model_name: str):
    """Lazy-load the cross-encoder model (cached singleton)."""
    from sentence_transformers import CrossEncoder

    logger.info("loading_cross_encoder", model=model_name)
    return CrossEncoder(model_name)


class CrossEncoderReranker(BaseReranker):
    """Reranker using a local cross-encoder model.

    Default model: cross-encoder/ms-marco-MiniLM-L-6-v2 (~80MB, fast on CPU).
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def rerank(self, query: str, results: list[SearchResult], top_k: int | None = None) -> list[SearchResult]:
        if not results:
            return results

        # Build query-document pairs for the cross-encoder
        pairs = [(query, r.content) for r in results]

        # Run inference in a thread to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(None, self._predict, pairs)

        # Attach scores and sort descending
        scored = list(zip(results, scores))
        scored.sort(key=lambda x: x[1], reverse=True)

        reranked = []
        for result, score in scored:
            reranked.append(result.model_copy(update={"score": float(score)}))

        if top_k is not None:
            reranked = reranked[:top_k]

        logger.info(
            "reranked",
            model=self._model_name,
            input_count=len(results),
            output_count=len(reranked),
        )
        return reranked

    def _predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Synchronous prediction (runs in executor)."""
        model = _load_model(self._model_name)
        scores: list[float] = model.predict(pairs).tolist()
        return scores
