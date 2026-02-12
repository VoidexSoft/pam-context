"""Tests for the DuckDB query service."""

import csv
import json
from pathlib import Path

import pytest

from pam.agent.duckdb_service import DuckDBService


@pytest.fixture
def data_dir(tmp_path):
    """Create a temp directory with sample data files."""
    # CSV file
    csv_path = tmp_path / "sales.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["region", "product", "revenue", "units"])
        writer.writerow(["North", "Widget A", 125000, 500])
        writer.writerow(["South", "Widget A", 98000, 392])
        writer.writerow(["North", "Widget B", 210000, 700])
        writer.writerow(["South", "Widget B", 175000, 583])

    # JSON file
    json_path = tmp_path / "users.json"
    json_path.write_text(json.dumps([
        {"name": "Alice", "age": 30, "city": "NYC"},
        {"name": "Bob", "age": 25, "city": "LA"},
        {"name": "Charlie", "age": 35, "city": "NYC"},
    ]))

    return tmp_path


@pytest.fixture
def service(data_dir):
    svc = DuckDBService(data_dir=str(data_dir), max_rows=100)
    svc.register_files()
    return svc


class TestRegisterFiles:
    def test_discovers_files(self, service):
        tables = service.list_tables()
        table_names = {t["table"] for t in tables}
        assert "sales" in table_names
        assert "users" in table_names

    def test_schema_detection(self, service):
        tables = service.list_tables()
        sales = next(t for t in tables if t["table"] == "sales")
        col_names = [c["name"] for c in sales["columns"]]
        assert "region" in col_names
        assert "revenue" in col_names
        assert sales["row_count"] == 4

    def test_empty_dir(self, tmp_path):
        svc = DuckDBService(data_dir=str(tmp_path))
        svc.register_files()
        assert svc.list_tables() == []


class TestExecuteQuery:
    def test_simple_select(self, service):
        result = service.execute_query("SELECT * FROM sales")
        assert "error" not in result
        assert result["row_count"] == 4
        assert "region" in result["columns"]

    def test_aggregate_query(self, service):
        result = service.execute_query("SELECT region, SUM(revenue) as total FROM sales GROUP BY region")
        assert "error" not in result
        assert result["row_count"] == 2

    def test_where_clause(self, service):
        result = service.execute_query("SELECT * FROM sales WHERE region = 'North'")
        assert result["row_count"] == 2

    def test_json_table(self, service):
        result = service.execute_query("SELECT * FROM users WHERE city = 'NYC'")
        assert result["row_count"] == 2

    def test_cross_table_query(self, service):
        result = service.execute_query(
            "SELECT COUNT(*) as cnt FROM sales UNION ALL SELECT COUNT(*) FROM users"
        )
        assert result["row_count"] == 2

    def test_row_limit(self, data_dir):
        svc = DuckDBService(data_dir=str(data_dir), max_rows=2)
        svc.register_files()
        result = svc.execute_query("SELECT * FROM sales")
        assert result["row_count"] == 2
        assert result["truncated"] is True

    def test_invalid_sql(self, service):
        result = service.execute_query("SELECT * FROM nonexistent_table")
        assert "error" in result


class TestSQLGuardrails:
    def test_blocks_insert(self, service):
        result = service.execute_query("INSERT INTO sales VALUES ('X', 'Y', 1, 1)")
        assert "error" in result
        assert "SELECT" in result["error"]

    def test_blocks_delete(self, service):
        result = service.execute_query("DELETE FROM sales")
        assert "error" in result

    def test_blocks_drop(self, service):
        result = service.execute_query("DROP TABLE sales")
        assert "error" in result

    def test_blocks_update(self, service):
        result = service.execute_query("UPDATE sales SET revenue = 0")
        assert "error" in result

    def test_allows_select(self, service):
        result = service.execute_query("SELECT 1 as test")
        assert "error" not in result

    def test_blocks_create(self, service):
        result = service.execute_query("CREATE TABLE evil (id INT)")
        assert "error" in result


class TestNoDataDir:
    def test_returns_error_without_data(self):
        svc = DuckDBService(data_dir="")
        result = svc.execute_query("SELECT 1")
        assert "error" in result
        assert "No data" in result["error"]
