"""Tests for EntityRelationshipVDBStore — index creation, upsert, skip-unchanged, bulk errors."""

import hashlib
from unittest.mock import AsyncMock

from pam.ingestion.stores.entity_relationship_store import (
    EntityRelationshipVDBStore,
    EntityVDBRecord,
    RelationshipVDBRecord,
    get_entity_index_mapping,
    get_relationship_index_mapping,
    make_relationship_doc_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(
    exists_side_effect: list[bool] | None = None,
    mget_response: dict | None = None,
) -> tuple[EntityRelationshipVDBStore, AsyncMock]:
    """Build a store with a mock ES client."""
    client = AsyncMock()
    client.indices.exists = AsyncMock(side_effect=exists_side_effect or [False, False])
    client.indices.create = AsyncMock()
    client.mget = AsyncMock(return_value=mget_response or {"docs": []})
    client.bulk = AsyncMock(return_value={"errors": False, "items": []})

    store = EntityRelationshipVDBStore(
        client=client,
        entity_index="pam_entities",
        relationship_index="pam_relationships",
        embedding_dims=1536,
    )
    return store, client


def _mock_embedder(dims: int = 1536) -> AsyncMock:
    """Return a mock embedder that produces deterministic vectors."""
    embedder = AsyncMock()
    call_count = 0

    async def _embed(texts: list[str]) -> list[list[float]]:
        nonlocal call_count
        result = []
        for i, _ in enumerate(texts):
            result.append([float(call_count * 10 + i + 1) / 100] * dims)
        call_count += 1
        return result

    embedder.embed_texts = AsyncMock(side_effect=_embed)
    embedder.dimensions = dims
    return embedder


# ===========================================================================
# TestEnsureIndices
# ===========================================================================


class TestEnsureIndices:
    async def test_creates_both_indices_when_missing(self):
        store, client = _make_store(exists_side_effect=[False, False])
        await store.ensure_indices()

        assert client.indices.create.call_count == 2
        # First call: entity index
        first_call = client.indices.create.call_args_list[0]
        assert first_call.kwargs["index"] == "pam_entities"
        # Second call: relationship index
        second_call = client.indices.create.call_args_list[1]
        assert second_call.kwargs["index"] == "pam_relationships"

    async def test_skips_existing_indices(self):
        store, client = _make_store(exists_side_effect=[True, True])
        await store.ensure_indices()

        client.indices.create.assert_not_called()

    async def test_entity_index_mapping_has_required_fields(self):
        mapping = get_entity_index_mapping(1536)
        props = mapping["mappings"]["properties"]

        assert props["embedding"]["type"] == "dense_vector"
        assert props["embedding"]["dims"] == 1536
        assert props["name"]["type"] == "keyword"
        assert props["entity_type"]["type"] == "keyword"
        assert props["description"]["type"] == "text"
        assert props["content_hash"]["type"] == "keyword"

    async def test_relationship_index_mapping_has_required_fields(self):
        mapping = get_relationship_index_mapping(1536)
        props = mapping["mappings"]["properties"]

        assert props["embedding"]["type"] == "dense_vector"
        assert props["embedding"]["dims"] == 1536
        assert props["src_entity"]["type"] == "keyword"
        assert props["tgt_entity"]["type"] == "keyword"
        assert props["rel_type"]["type"] == "keyword"
        assert props["keywords"]["type"] == "text"
        assert props["description"]["type"] == "text"
        assert props["weight"]["type"] == "float"
        assert props["content_hash"]["type"] == "keyword"


# ===========================================================================
# TestUpsertEntities
# ===========================================================================


class TestUpsertEntities:
    async def test_upsert_embeds_and_bulk_inserts(self):
        """Full happy path: all entities are new → embed all, bulk upsert."""
        mget_resp = {"docs": [{"found": False}, {"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        entities = [
            EntityVDBRecord(name="AuthService", entity_type="Technology", description="Handles auth", source_id="s1"),
            EntityVDBRecord(name="TeamAlpha", entity_type="Team", description="Dev team", source_id="s1"),
        ]
        count = await store.upsert_entities(entities, embedder, source_id="src-1")

        assert count == 2
        embedder.embed_texts.assert_called_once()
        client.bulk.assert_called_once()

        # Verify bulk actions structure
        bulk_args = client.bulk.call_args.kwargs["operations"]
        # 2 entities → 4 items (action + doc each)
        assert len(bulk_args) == 4
        assert bulk_args[0]["index"]["_id"] == "AuthService"
        assert bulk_args[1]["name"] == "AuthService"
        assert bulk_args[2]["index"]["_id"] == "TeamAlpha"

    async def test_upsert_skips_unchanged_entities(self):
        """Content hash matches → no embed call, returns 0."""
        text = "AuthService\nHandles auth"
        existing_hash = hashlib.sha256(text.encode()).hexdigest()

        mget_resp = {"docs": [{"found": True, "_source": {"content_hash": existing_hash}}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        entities = [
            EntityVDBRecord(name="AuthService", entity_type="Technology", description="Handles auth", source_id="s1"),
        ]
        count = await store.upsert_entities(entities, embedder, source_id="src-1")

        assert count == 0
        embedder.embed_texts.assert_not_called()
        client.bulk.assert_not_called()

    async def test_upsert_partial_skip(self):
        """3 entities, 1 unchanged → only 2 embedded."""
        # Entity 0: unchanged
        text0 = "Existing\nSame description"
        hash0 = hashlib.sha256(text0.encode()).hexdigest()

        mget_resp = {
            "docs": [
                {"found": True, "_source": {"content_hash": hash0}},
                {"found": False},
                {"found": False},
            ]
        }
        store, _client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        entities = [
            EntityVDBRecord(name="Existing", entity_type="T", description="Same description", source_id="s1"),
            EntityVDBRecord(name="NewOne", entity_type="T", description="New desc", source_id="s1"),
            EntityVDBRecord(name="Another", entity_type="T", description="Another desc", source_id="s1"),
        ]
        count = await store.upsert_entities(entities, embedder, source_id="src-1")

        assert count == 2
        # embed_texts called with only the 2 changed texts
        embed_call_texts = embedder.embed_texts.call_args[0][0]
        assert len(embed_call_texts) == 2

    async def test_upsert_empty_list_returns_zero(self):
        store, client = _make_store()
        embedder = _mock_embedder()

        count = await store.upsert_entities([], embedder, source_id="src-1")

        assert count == 0
        embedder.embed_texts.assert_not_called()
        client.bulk.assert_not_called()

    async def test_lightrag_entity_embedding_format(self):
        """Embedding text for entities is 'name\\ndescription' (LightRAG format)."""
        mget_resp = {"docs": [{"found": False}]}
        store, _ = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        entities = [
            EntityVDBRecord(name="MyService", entity_type="Tech", description="Does things", source_id="s1"),
        ]
        await store.upsert_entities(entities, embedder, source_id="src-1")

        embed_texts = embedder.embed_texts.call_args[0][0]
        assert embed_texts == ["MyService\nDoes things"]

    async def test_content_hash_sha256(self):
        """Content hash matches hashlib.sha256(text.encode()).hexdigest()."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        entities = [
            EntityVDBRecord(name="Svc", entity_type="T", description="desc", source_id="s1"),
        ]
        await store.upsert_entities(entities, embedder, source_id="src-1")

        bulk_ops = client.bulk.call_args.kwargs["operations"]
        stored_hash = bulk_ops[1]["content_hash"]
        expected_hash = hashlib.sha256(b"Svc\ndesc").hexdigest()
        assert stored_hash == expected_hash


# ===========================================================================
# TestUpsertRelationships
# ===========================================================================


class TestUpsertRelationships:
    async def test_upsert_embeds_and_bulk_inserts(self):
        """Full happy path for relationship upsert."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        rels = [
            RelationshipVDBRecord(
                src_entity="A",
                tgt_entity="B",
                rel_type="USES",
                keywords="integration",
                description="A uses B",
                source_id="s1",
            ),
        ]
        count = await store.upsert_relationships(rels, embedder, source_id="src-1")

        assert count == 1
        embedder.embed_texts.assert_called_once()
        client.bulk.assert_called_once()

    async def test_upsert_skips_unchanged_relationships(self):
        """Content hash match → skip."""
        text = "kw\tSrc\nTgt\ndesc"
        existing_hash = hashlib.sha256(text.encode()).hexdigest()

        mget_resp = {"docs": [{"found": True, "_source": {"content_hash": existing_hash}}]}
        store, _client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        rels = [
            RelationshipVDBRecord(
                src_entity="Src",
                tgt_entity="Tgt",
                rel_type="REL",
                keywords="kw",
                description="desc",
                source_id="s1",
            ),
        ]
        count = await store.upsert_relationships(rels, embedder, source_id="src-1")

        assert count == 0
        embedder.embed_texts.assert_not_called()

    async def test_lightrag_relationship_embedding_format(self):
        """Embedding text is 'keywords\\tsrc\\ntgt\\ndescription' (LightRAG format)."""
        mget_resp = {"docs": [{"found": False}]}
        store, _ = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        rels = [
            RelationshipVDBRecord(
                src_entity="Alpha",
                tgt_entity="Beta",
                rel_type="DEPENDS",
                keywords="dependency",
                description="Alpha depends on Beta",
                source_id="s1",
            ),
        ]
        await store.upsert_relationships(rels, embedder, source_id="src-1")

        embed_texts = embedder.embed_texts.call_args[0][0]
        assert embed_texts == ["dependency\tAlpha\nBeta\nAlpha depends on Beta"]

    async def test_relationship_doc_id_is_alphabetically_sorted(self):
        """make_relationship_doc_id('B', 'REL', 'A') → 'A::REL::B'."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        rels = [
            RelationshipVDBRecord(
                src_entity="Zebra",
                tgt_entity="Apple",
                rel_type="USES",
                keywords="k",
                description="d",
                source_id="s1",
            ),
        ]
        await store.upsert_relationships(rels, embedder, source_id="src-1")

        bulk_ops = client.bulk.call_args.kwargs["operations"]
        doc_id = bulk_ops[0]["index"]["_id"]
        assert doc_id == "Apple::USES::Zebra"

    async def test_bulk_error_logging(self):
        """Bulk returns errors → logged but not raised."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        client.bulk = AsyncMock(
            return_value={
                "errors": True,
                "items": [{"index": {"error": {"type": "mapper_parsing_exception", "reason": "bad field"}}}],
            }
        )
        embedder = _mock_embedder()

        rels = [
            RelationshipVDBRecord(
                src_entity="X",
                tgt_entity="Y",
                rel_type="R",
                keywords="k",
                description="d",
                source_id="s1",
            ),
        ]
        # Should not raise
        count = await store.upsert_relationships(rels, embedder, source_id="src-1")
        assert count == 1


# ===========================================================================
# TestMakeRelationshipDocId
# ===========================================================================


class TestMakeRelationshipDocId:
    def test_sorted_pair(self):
        result = make_relationship_doc_id("Zebra", "USES", "Apple")
        assert result == "Apple::USES::Zebra"

    def test_same_order(self):
        result = make_relationship_doc_id("A", "X", "B")
        assert result == "A::X::B"

    def test_identical_entities(self):
        result = make_relationship_doc_id("Self", "RELATES", "Self")
        assert result == "Self::RELATES::Self"

    def test_multiple_rel_types_between_same_pair(self):
        """Different rel_types between the same entities produce distinct doc IDs."""
        id_manages = make_relationship_doc_id("Alice", "MANAGES", "Bob")
        id_mentors = make_relationship_doc_id("Alice", "MENTORS", "Bob")

        assert id_manages == "Alice::MANAGES::Bob"
        assert id_mentors == "Alice::MENTORS::Bob"
        assert id_manages != id_mentors


# ===========================================================================
# TestUpsertEntities — Gap Coverage
# ===========================================================================


class TestUpsertEntitiesGaps:
    async def test_entity_file_paths_included_in_doc(self):
        """file_paths contains entity.file_path when set."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        entities = [
            EntityVDBRecord(
                name="Svc",
                entity_type="T",
                description="d",
                source_id="s1",
                file_path="/docs/readme.md",
            ),
        ]
        await store.upsert_entities(entities, embedder, source_id="src-1")

        bulk_ops = client.bulk.call_args.kwargs["operations"]
        doc = bulk_ops[1]
        assert doc["file_paths"] == ["/docs/readme.md"]

    async def test_entity_file_paths_empty_when_none(self):
        """file_paths is [] when entity.file_path is None."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        entities = [
            EntityVDBRecord(name="Svc", entity_type="T", description="d", source_id="s1"),
        ]
        await store.upsert_entities(entities, embedder, source_id="src-1")

        bulk_ops = client.bulk.call_args.kwargs["operations"]
        doc = bulk_ops[1]
        assert doc["file_paths"] == []

    async def test_entity_source_ids_in_bulk_doc(self):
        """source_ids field contains the provided source_id."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        entities = [
            EntityVDBRecord(name="X", entity_type="T", description="d", source_id="s1"),
        ]
        await store.upsert_entities(entities, embedder, source_id="doc-42")

        bulk_ops = client.bulk.call_args.kwargs["operations"]
        doc = bulk_ops[1]
        assert doc["source_ids"] == ["doc-42"]

    async def test_entity_bulk_error_logged_not_raised(self):
        """Bulk returns errors on entity upsert → logged but not raised."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        client.bulk = AsyncMock(
            return_value={
                "errors": True,
                "items": [{"index": {"error": {"type": "mapper_parsing_exception", "reason": "bad"}}}],
            }
        )
        embedder = _mock_embedder()

        entities = [
            EntityVDBRecord(name="Svc", entity_type="T", description="d", source_id="s1"),
        ]
        # Should not raise
        count = await store.upsert_entities(entities, embedder, source_id="src-1")
        assert count == 1


# ===========================================================================
# TestUpsertRelationships — Gap Coverage
# ===========================================================================


class TestUpsertRelationshipsGaps:
    async def test_relationship_content_hash_sha256(self):
        """Content hash matches SHA-256 of LightRAG relationship embedding text."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        rels = [
            RelationshipVDBRecord(
                src_entity="A",
                tgt_entity="B",
                rel_type="USES",
                keywords="kw",
                description="A uses B",
                source_id="s1",
            ),
        ]
        await store.upsert_relationships(rels, embedder, source_id="src-1")

        bulk_ops = client.bulk.call_args.kwargs["operations"]
        stored_hash = bulk_ops[1]["content_hash"]
        expected_hash = hashlib.sha256(b"kw\tA\nB\nA uses B").hexdigest()
        assert stored_hash == expected_hash

    async def test_relationship_weight_in_bulk_doc(self):
        """Weight field from record is preserved in the bulk document."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        rels = [
            RelationshipVDBRecord(
                src_entity="A",
                tgt_entity="B",
                rel_type="R",
                keywords="k",
                description="d",
                source_id="s1",
                weight=3.5,
            ),
        ]
        await store.upsert_relationships(rels, embedder, source_id="src-1")

        bulk_ops = client.bulk.call_args.kwargs["operations"]
        doc = bulk_ops[1]
        assert doc["weight"] == 3.5

    async def test_relationship_source_ids_in_bulk_doc(self):
        """source_ids field contains the provided source_id."""
        mget_resp = {"docs": [{"found": False}]}
        store, client = _make_store(mget_response=mget_resp)
        embedder = _mock_embedder()

        rels = [
            RelationshipVDBRecord(
                src_entity="X",
                tgt_entity="Y",
                rel_type="R",
                keywords="k",
                description="d",
                source_id="s1",
            ),
        ]
        await store.upsert_relationships(rels, embedder, source_id="doc-99")

        bulk_ops = client.bulk.call_args.kwargs["operations"]
        doc = bulk_ops[1]
        assert doc["source_ids"] == ["doc-99"]


# ===========================================================================
# TestFilterUnchanged — Edge Cases
# ===========================================================================


class TestFilterUnchangedEdgeCases:
    async def test_filter_unchanged_missing_content_hash(self):
        """Doc exists but has no content_hash field → treated as changed."""
        mget_resp = {"docs": [{"found": True, "_source": {}}]}
        store, _ = _make_store(mget_response=mget_resp)

        _, changed_indices = await store._filter_unchanged("pam_entities", ["entity-1"], ["abc123"])

        assert changed_indices == [0]
