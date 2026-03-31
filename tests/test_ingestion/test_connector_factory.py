"""Tests for connector factory functions."""

import os
from unittest.mock import patch

from pam.common.config import Settings
from pam.ingestion.connectors.factory import (
    get_google_docs_connector,
    get_google_sheets_connector,
)
from pam.ingestion.connectors.google_docs import GoogleDocsConnector
from pam.ingestion.connectors.google_sheets import GoogleSheetsConnector
from pam.ingestion.connectors.gws_docs import GwsDocsConnector
from pam.ingestion.connectors.gws_sheets import GwsSheetsConnector


def _make_settings(**overrides) -> Settings:
    defaults = {
        "database_url": "postgresql+psycopg://x:x@localhost/x",
        "openai_api_key": "test",
        "anthropic_api_key": "test",
    }
    with patch.dict(os.environ, {}, clear=True):
        return Settings(**{**defaults, **overrides})


class TestGetGoogleDocsConnector:
    def test_returns_gws_when_cli_enabled(self):
        cfg = _make_settings(use_cli_connectors=True)
        conn = get_google_docs_connector(cfg)
        assert isinstance(conn, GwsDocsConnector)

    def test_returns_api_when_cli_disabled(self):
        cfg = _make_settings(use_cli_connectors=False)
        conn = get_google_docs_connector(cfg)
        assert isinstance(conn, GoogleDocsConnector)


class TestGetGoogleSheetsConnector:
    def test_returns_gws_when_cli_enabled(self):
        cfg = _make_settings(use_cli_connectors=True)
        conn = get_google_sheets_connector(cfg)
        assert isinstance(conn, GwsSheetsConnector)

    def test_returns_api_when_cli_disabled(self):
        cfg = _make_settings(use_cli_connectors=False)
        conn = get_google_sheets_connector(cfg)
        assert isinstance(conn, GoogleSheetsConnector)
