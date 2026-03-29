"""Document connectors — abstract base and implementations."""

from pam.ingestion.connectors.base import BaseConnector
from pam.ingestion.connectors.cli_base import CliConnector, ConnectorError
from pam.ingestion.connectors.factory import (
    get_google_docs_connector,
    get_google_sheets_connector,
)
from pam.ingestion.connectors.github import GitHubConnector
from pam.ingestion.connectors.google_docs import GoogleDocsConnector
from pam.ingestion.connectors.google_sheets import GoogleSheetsConnector
from pam.ingestion.connectors.gws_docs import GwsDocsConnector
from pam.ingestion.connectors.gws_sheets import GwsSheetsConnector
from pam.ingestion.connectors.markdown import MarkdownConnector

__all__ = [
    "BaseConnector",
    "CliConnector",
    "ConnectorError",
    "GitHubConnector",
    "GoogleDocsConnector",
    "GoogleSheetsConnector",
    "GwsDocsConnector",
    "GwsSheetsConnector",
    "MarkdownConnector",
    "get_google_docs_connector",
    "get_google_sheets_connector",
]
