"""Base class for CLI-backed connectors (gh, gws)."""

from __future__ import annotations


class ConnectorError(Exception):
    """Raised when a CLI connector encounters an error."""

    def __init__(self, message: str, *, command: list[str] | None = None) -> None:
        super().__init__(message)
        self.command = command
