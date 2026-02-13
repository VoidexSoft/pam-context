"""Tests for FastAPI dependency injection singletons."""

from unittest.mock import MagicMock, patch

import pam.api.deps as deps_module


class TestGetDuckdbService:
    def setup_method(self):
        """Reset singleton state before each test."""
        deps_module._duckdb_service = None
        deps_module._duckdb_initialized = False

    def teardown_method(self):
        """Reset singleton state after each test."""
        deps_module._duckdb_service = None
        deps_module._duckdb_initialized = False

    @patch.object(deps_module.settings, "duckdb_data_dir", "")
    def test_returns_none_when_no_data_dir(self):
        result = deps_module.get_duckdb_service()
        assert result is None

    @patch.object(deps_module.settings, "duckdb_data_dir", "/some/dir")
    @patch("pam.api.deps.DuckDBService", create=True)
    def test_returns_singleton(self, mock_duckdb_cls):
        mock_instance = MagicMock()
        mock_duckdb_cls.return_value = mock_instance

        with patch.dict("sys.modules", {"pam.agent.duckdb_service": MagicMock(DuckDBService=mock_duckdb_cls)}):
            first = deps_module.get_duckdb_service()
            second = deps_module.get_duckdb_service()

        assert first is second
        # DuckDBService constructor called only once
        assert mock_duckdb_cls.call_count == 1
        mock_instance.register_files.assert_called_once()

    @patch.object(deps_module.settings, "duckdb_data_dir", "")
    def test_none_result_is_cached(self):
        """Even None result should be cached (not re-evaluated)."""
        first = deps_module.get_duckdb_service()
        assert first is None
        assert deps_module._duckdb_initialized is True

        # Second call should not re-check
        second = deps_module.get_duckdb_service()
        assert second is None
