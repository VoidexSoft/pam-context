"""Tests for the reranking pipeline."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.retrieval.rerankers.base import BaseReranker
from pam.retrieval.rerankers.cross_encoder import CrossEncoderReranker
from pam.retrieval.types import SearchResult


def _make_result(content: str, score: float = 1.0) -> SearchResult:
    return SearchResult(
        segment_id=uuid.uuid4(),
        content=content,
        score=score,
    )


class TestBaseReranker:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            BaseReranker()


class TestCrossEncoderReranker:
    def test_model_name(self):
        reranker = CrossEncoderReranker(model_name="test-model")
        assert reranker.model_name == "test-model"

    def test_default_model_name(self):
        reranker = CrossEncoderReranker()
        assert reranker.model_name == "cross-encoder/ms-marco-MiniLM-L-6-v2"

    async def test_rerank_empty_results(self):
        reranker = CrossEncoderReranker()
        results = await reranker.rerank("query", [])
        assert results == []

    async def test_rerank_reorders_by_score(self):
        reranker = CrossEncoderReranker()

        results = [
            _make_result("low relevance", score=0.1),
            _make_result("high relevance", score=0.9),
            _make_result("medium relevance", score=0.5),
        ]

        # Mock the model prediction
        mock_model = MagicMock()
        # Scores: low=0.1, high=0.95, medium=0.5
        import numpy as np

        mock_model.predict.return_value = np.array([0.1, 0.95, 0.5])

        with patch("pam.retrieval.rerankers.cross_encoder._load_model", return_value=mock_model):
            reranked = await reranker.rerank("test query", results)

        assert len(reranked) == 3
        assert reranked[0].content == "high relevance"
        assert reranked[1].content == "medium relevance"
        assert reranked[2].content == "low relevance"
        assert reranked[0].score == pytest.approx(0.95)

    async def test_rerank_with_top_k(self):
        reranker = CrossEncoderReranker()

        results = [
            _make_result("a", score=0.1),
            _make_result("b", score=0.2),
            _make_result("c", score=0.3),
        ]

        mock_model = MagicMock()
        import numpy as np

        mock_model.predict.return_value = np.array([0.8, 0.3, 0.6])

        with patch("pam.retrieval.rerankers.cross_encoder._load_model", return_value=mock_model):
            reranked = await reranker.rerank("test", results, top_k=2)

        assert len(reranked) == 2
        assert reranked[0].content == "a"  # highest score 0.8
        assert reranked[1].content == "c"  # second score 0.6

    async def test_rerank_preserves_metadata(self):
        reranker = CrossEncoderReranker()

        result = SearchResult(
            segment_id=uuid.uuid4(),
            content="test content",
            score=0.5,
            source_url="http://example.com",
            source_id="doc1",
            section_path="Section 1",
            document_title="Test Doc",
            segment_type="text",
        )

        mock_model = MagicMock()
        import numpy as np

        mock_model.predict.return_value = np.array([0.9])

        with patch("pam.retrieval.rerankers.cross_encoder._load_model", return_value=mock_model):
            reranked = await reranker.rerank("test", [result])

        assert len(reranked) == 1
        assert reranked[0].source_url == "http://example.com"
        assert reranked[0].source_id == "doc1"
        assert reranked[0].section_path == "Section 1"
        assert reranked[0].document_title == "Test Doc"
        assert reranked[0].score == pytest.approx(0.9)

    async def test_predict_called_with_pairs(self):
        reranker = CrossEncoderReranker()

        results = [
            _make_result("doc A"),
            _make_result("doc B"),
        ]

        mock_model = MagicMock()
        import numpy as np

        mock_model.predict.return_value = np.array([0.5, 0.5])

        with patch("pam.retrieval.rerankers.cross_encoder._load_model", return_value=mock_model):
            await reranker.rerank("my query", results)

        mock_model.predict.assert_called_once()
        pairs = mock_model.predict.call_args[0][0]
        assert pairs == [("my query", "doc A"), ("my query", "doc B")]


class TestHybridSearchWithReranker:
    """Test that reranking integrates correctly with HybridSearchService."""

    async def test_search_uses_reranker_when_configured(self, mock_es_client):
        from pam.retrieval.hybrid_search import HybridSearchService

        mock_reranker = AsyncMock(spec=BaseReranker)
        reranked_results = [_make_result("reranked", score=0.99)]
        mock_reranker.rerank = AsyncMock(return_value=reranked_results)

        # Setup ES to return results (fields nested under meta.* to match real ES mapping)
        sid = str(uuid.uuid4())
        mock_es_client.search = AsyncMock(
            return_value={
                "hits": {
                    "hits": [
                        {
                            "_id": sid,
                            "_score": 0.5,
                            "_source": {
                                "content": "original",
                                "meta": {
                                    "segment_id": sid,
                                },
                            },
                        }
                    ]
                }
            }
        )

        service = HybridSearchService(mock_es_client, index_name="test_idx", reranker=mock_reranker)
        results = await service.search("test", [0.1] * 1536)

        mock_reranker.rerank.assert_called_once()
        assert len(results) == 1
        assert results[0].content == "reranked"

    async def test_search_skips_reranker_when_not_configured(self, mock_es_client):
        from pam.retrieval.hybrid_search import HybridSearchService

        sid = str(uuid.uuid4())
        mock_es_client.search = AsyncMock(
            return_value={
                "hits": {
                    "hits": [
                        {
                            "_id": sid,
                            "_score": 0.5,
                            "_source": {
                                "content": "original",
                                "meta": {
                                    "segment_id": sid,
                                },
                            },
                        }
                    ]
                }
            }
        )

        service = HybridSearchService(mock_es_client, index_name="test_idx", reranker=None)
        results = await service.search("test", [0.1] * 1536)

        assert len(results) == 1
        assert results[0].content == "original"

    async def test_search_skips_reranker_for_empty_results(self, mock_es_client):
        from pam.retrieval.hybrid_search import HybridSearchService

        mock_reranker = AsyncMock(spec=BaseReranker)

        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})

        service = HybridSearchService(mock_es_client, index_name="test_idx", reranker=mock_reranker)
        results = await service.search("test", [0.1] * 1536)

        mock_reranker.rerank.assert_not_called()
        assert results == []
