"""Tests for Google Sheets region detection and connector."""

import json

import pytest

from pam.ingestion.connectors.google_sheets import LocalSheetsConnector
from pam.ingestion.connectors.sheets_region_detector import (
    _is_blank_row,
    _is_config_block,
    _is_notes_block,
    _is_table_block,
    _split_into_blocks,
    detect_regions,
)
from tests.fixtures.sheets.mock_sheets import ALL_FIXTURES

# ── Region Detection Tests ─────────────────────────────────────────────


class TestBlankRow:
    def test_empty_list(self):
        assert _is_blank_row([]) is True

    def test_all_empty(self):
        assert _is_blank_row(["", "", ""]) is True

    def test_whitespace_only(self):
        assert _is_blank_row(["  ", "\t", ""]) is True

    def test_has_content(self):
        assert _is_blank_row(["", "data", ""]) is False


class TestSplitIntoBlocks:
    def test_single_block(self):
        cells = [["a", "b"], ["c", "d"]]
        blocks = _split_into_blocks(cells)
        assert len(blocks) == 1
        assert blocks[0] == (0, [["a", "b"], ["c", "d"]])

    def test_two_blocks_with_blank_row(self):
        cells = [["a"], [""], ["b"]]
        blocks = _split_into_blocks(cells)
        assert len(blocks) == 2
        assert blocks[0] == (0, [["a"]])
        assert blocks[1] == (2, [["b"]])

    def test_leading_blank_rows(self):
        cells = [[""], [""], ["data"]]
        blocks = _split_into_blocks(cells)
        assert len(blocks) == 1
        assert blocks[0][0] == 2

    def test_empty_input(self):
        assert _split_into_blocks([]) == []


class TestClassifiers:
    def test_config_block(self):
        block = [["Key", "Value"], ["timeout", "30"], ["retries", "3"]]
        assert _is_config_block(block) is True

    def test_config_block_too_many_columns(self):
        block = [["A", "B", "C"], ["1", "2", "3"]]
        assert _is_config_block(block) is False

    def test_table_block(self):
        block = [
            ["Name", "Age", "City"],
            ["Alice", "30", "NYC"],
            ["Bob", "25", "LA"],
        ]
        assert _is_table_block(block) is True

    def test_table_block_single_row(self):
        block = [["Name", "Age"]]
        assert _is_table_block(block) is False  # needs >= 2 rows

    def test_notes_block(self):
        block = [["This is a note"], ["Another line"], ["Third line"]]
        assert _is_notes_block(block) is True

    def test_notes_block_multi_column(self):
        block = [["A", "B", "C"], ["D", "E", "F"]]
        assert _is_notes_block(block) is False


# ── Fixture-Based Region Detection Tests ───────────────────────────────


class TestCleanTable:
    def test_detects_single_table(self):
        data = ALL_FIXTURES["clean_table"]()
        regions = detect_regions(data["tabs"]["Sales"])
        assert len(regions) == 1
        assert regions[0].type == "table"
        assert regions[0].headers[0] == "Region"
        assert len(regions[0].rows) == 5


class TestMultiTable:
    def test_detects_multiple_regions(self):
        data = ALL_FIXTURES["multi_table"]()
        regions = detect_regions(data["tabs"]["Data"])
        # Should detect at least 2 table regions (separated by blank rows)
        table_regions = [r for r in regions if r.type == "table"]
        assert len(table_regions) >= 2


class TestNotesAndTable:
    def test_detects_notes_and_table(self):
        data = ALL_FIXTURES["notes_and_table"]()
        regions = detect_regions(data["tabs"]["Sheet1"])
        types = [r.type for r in regions]
        assert "notes" in types
        assert "table" in types


class TestConfigSheet:
    def test_detects_config(self):
        data = ALL_FIXTURES["config_sheet"]()
        regions = detect_regions(data["tabs"]["Config"])
        assert len(regions) == 1
        assert regions[0].type == "config"
        assert len(regions[0].rows) == 7  # 7 config rows after header


class TestMultiTab:
    def test_all_tabs_detect(self):
        data = ALL_FIXTURES["multi_tab"]()
        for tab_name, rows in data["tabs"].items():
            regions = detect_regions(rows, tab_name)
            assert len(regions) >= 1, f"No regions detected in tab '{tab_name}'"


class TestMixedContent:
    def test_detects_multiple_types(self):
        data = ALL_FIXTURES["mixed_content"]()
        regions = detect_regions(data["tabs"]["Sheet1"])
        types = set(r.type for r in regions)
        # Should detect at least 2 different types
        assert len(types) >= 2


class TestSparseData:
    def test_handles_sparse(self):
        data = ALL_FIXTURES["sparse_data"]()
        regions = detect_regions(data["tabs"]["Sheet1"])
        # Should not crash and should detect at least 1 region
        assert len(regions) >= 1


class TestEdgeCases:
    def test_empty_sheet(self):
        data = ALL_FIXTURES["edge_cases"]()
        regions = detect_regions(data["tabs"]["Empty"])
        assert regions == []

    def test_single_row(self):
        data = ALL_FIXTURES["edge_cases"]()
        regions = detect_regions(data["tabs"]["Single Row"])
        assert len(regions) == 1

    def test_single_column(self):
        data = ALL_FIXTURES["edge_cases"]()
        regions = detect_regions(data["tabs"]["Single Column"])
        assert len(regions) == 1


# ── Local Connector Tests ──────────────────────────────────────────────


class TestLocalSheetsConnector:
    @pytest.fixture
    def connector(self):
        sheets = {
            "sheet1": ALL_FIXTURES["clean_table"](),
            "sheet2": ALL_FIXTURES["multi_tab"](),
        }
        return LocalSheetsConnector(sheets)

    async def test_list_documents(self, connector):
        docs = await connector.list_documents()
        assert len(docs) == 2
        titles = {d.title for d in docs}
        assert "Q1 Sales Report" in titles
        assert "Monthly Report" in titles

    async def test_fetch_document(self, connector):
        doc = await connector.fetch_document("sheet1")
        assert doc.content_type == "application/vnd.google-sheets+json"
        data = json.loads(doc.content)
        assert data["title"] == "Q1 Sales Report"
        assert "Sales" in data["tabs"]
        assert len(data["tabs"]["Sales"]["regions"]) >= 1

    async def test_fetch_multi_tab(self, connector):
        doc = await connector.fetch_document("sheet2")
        data = json.loads(doc.content)
        assert len(data["tabs"]) == 3
        assert "Summary" in data["tabs"]
        assert "Raw Data" in data["tabs"]
        assert "Config" in data["tabs"]

    async def test_content_hash_deterministic(self, connector):
        hash1 = await connector.get_content_hash("sheet1")
        hash2 = await connector.get_content_hash("sheet1")
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256

    async def test_content_hash_different_sheets(self, connector):
        hash1 = await connector.get_content_hash("sheet1")
        hash2 = await connector.get_content_hash("sheet2")
        assert hash1 != hash2

    async def test_all_fixtures_through_connector(self):
        """Smoke test: every fixture runs through the connector without errors."""
        for name, fixture_fn in ALL_FIXTURES.items():
            connector = LocalSheetsConnector({"test": fixture_fn()})
            docs = await connector.list_documents()
            assert len(docs) == 1, f"Failed for fixture: {name}"

            doc = await connector.fetch_document("test")
            data = json.loads(doc.content)
            assert "tabs" in data, f"No tabs in fixture: {name}"
