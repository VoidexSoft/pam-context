"""Factory functions for selecting between API and CLI connectors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pam.ingestion.connectors.base import BaseConnector

if TYPE_CHECKING:
    from pam.common.config import Settings


def get_google_docs_connector(config: Settings) -> BaseConnector:
    """Return GwsDocsConnector when CLI connectors enabled, else GoogleDocsConnector."""
    if config.use_cli_connectors:
        from pam.ingestion.connectors.gws_docs import GwsDocsConnector

        return GwsDocsConnector(folder_ids=getattr(config, "google_folder_ids", []))

    from pam.ingestion.connectors.google_docs import GoogleDocsConnector

    return GoogleDocsConnector(
        credentials_path=getattr(config, "google_credentials_path", None),
        folder_ids=getattr(config, "google_folder_ids", []),
    )


def get_google_sheets_connector(config: Settings) -> BaseConnector:
    """Return GwsSheetsConnector when CLI connectors enabled, else GoogleSheetsConnector.

    Note: GoogleSheetsConnector uses ``folder_id`` (singular) and ``credentials_path``.
    """
    if config.use_cli_connectors:
        from pam.ingestion.connectors.gws_sheets import GwsSheetsConnector

        return GwsSheetsConnector(folder_ids=getattr(config, "google_folder_ids", []))

    from pam.ingestion.connectors.google_sheets import GoogleSheetsConnector

    folder_ids: list[str] = getattr(config, "google_folder_ids", [])
    return GoogleSheetsConnector(
        credentials_path=getattr(config, "google_credentials_path", None),
        # GoogleSheetsConnector takes a single folder_id; pass the first one if present
        folder_id=folder_ids[0] if folder_ids else None,
    )
