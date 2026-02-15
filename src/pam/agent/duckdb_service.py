"""DuckDB query service for analytics over data files."""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import structlog

from pam.common.config import settings

logger = structlog.get_logger()

# SQL injection guard: block write operations and dangerous commands
_FORBIDDEN_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE"
    r"|EXEC|EXECUTE|COPY|ATTACH|DETACH|PRAGMA|INSTALL|LOAD|SET)\b",
    re.IGNORECASE,
)


def _contains_multiple_statements(sql: str) -> bool:
    """Reject SQL containing semicolons (multi-statement chaining)."""
    # Strip trailing whitespace/semicolons, then check for remaining semicolons
    stripped = sql.strip().rstrip(";").strip()
    return ";" in stripped


class DuckDBService:
    """Manages DuckDB connections and runs guarded SQL queries over registered data files."""

    def __init__(self, data_dir: str | None = None, max_rows: int | None = None) -> None:
        self.data_dir = Path(data_dir or settings.duckdb_data_dir) if (data_dir or settings.duckdb_data_dir) else None
        self.max_rows = max_rows or settings.duckdb_max_rows
        self._tables: dict[str, Path] = {}

    def register_files(self) -> None:
        """Scan data_dir for CSV, Parquet, and JSON files and register them as tables."""
        if self.data_dir is None or not self.data_dir.is_dir():
            return

        for ext in ("*.csv", "*.parquet", "*.json"):
            for path in self.data_dir.glob(ext):
                table_name = path.stem.lower().replace("-", "_").replace(" ", "_")
                self._tables[table_name] = path

        logger.info("duckdb_tables_registered", count=len(self._tables), tables=list(self._tables.keys()))

    def list_tables(self) -> list[dict]:
        """List all registered tables with their schemas."""
        if not self._tables:
            self.register_files()

        result = []
        for name, path in self._tables.items():
            conn = None
            try:
                conn = duckdb.connect(":memory:")
                rel = self._read_file(conn, path)
                columns = [
                    {"name": col, "type": str(dtype)}
                    for col, dtype in zip(rel.columns, rel.dtypes, strict=True)
                ]
                row_count = rel.count("*").fetchone()[0]
                result.append(
                    {
                        "table": name,
                        "file": str(path.name),
                        "columns": columns,
                        "row_count": row_count,
                    }
                )
            except Exception as e:
                result.append({"table": name, "file": str(path.name), "error": str(e)})
            finally:
                if conn is not None:
                    conn.close()

        return result

    def execute_query(self, sql: str) -> dict:
        """Execute a read-only SQL query and return results.

        Returns:
            {"columns": [...], "rows": [...], "row_count": int, "truncated": bool}
        """
        # Guard 1: reject forbidden keywords
        if _FORBIDDEN_PATTERNS.search(sql):
            return {"error": "Only SELECT queries are allowed. Write operations are forbidden."}

        # Guard 2: reject multi-statement SQL (semicolon chaining)
        if _contains_multiple_statements(sql):
            return {"error": "Multi-statement queries are not allowed."}

        if not self._tables:
            self.register_files()

        if not self._tables:
            return {
                "error": "No data files registered. "
                "Set DUCKDB_DATA_DIR to a directory containing CSV/Parquet/JSON files."
            }

        conn = None
        try:
            conn = duckdb.connect(":memory:")

            # Materialize each file as an in-memory table
            for name, path in self._tables.items():
                rel = self._read_file(conn, path)
                rel.create(name)

            # Lock down: disable external access after data is loaded
            conn.execute("SET enable_external_access = false")
            conn.execute("SET lock_configuration = true")

            # Strip trailing semicolons before wrapping
            clean_sql = sql.strip().rstrip(";").strip()

            # Execute with row limit
            limited_sql = f"SELECT * FROM ({clean_sql}) AS _q LIMIT {self.max_rows + 1}"  # noqa: S608
            result = conn.execute(limited_sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()

            truncated = len(rows) > self.max_rows
            if truncated:
                rows = rows[: self.max_rows]

            # Convert to serializable format
            serializable_rows = [[_serialize_value(v) for v in row] for row in rows]

            logger.info("duckdb_query", sql=sql[:200], rows=len(serializable_rows), truncated=truncated)
            return {
                "columns": columns,
                "rows": serializable_rows,
                "row_count": len(serializable_rows),
                "truncated": truncated,
            }

        except Exception as e:
            logger.warning("duckdb_query_error", sql=sql[:200], error=str(e))
            return {"error": str(e)}

        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _read_file(conn: duckdb.DuckDBPyConnection, path: Path):
        """Read a data file into a DuckDB relation based on extension."""
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return conn.read_csv(str(path))
        if suffix == ".parquet":
            return conn.read_parquet(str(path))
        if suffix == ".json":
            return conn.read_json(str(path))
        raise ValueError(f"Unsupported file type: {suffix}")


def _serialize_value(v):
    """Convert DuckDB values to JSON-serializable types."""
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)
