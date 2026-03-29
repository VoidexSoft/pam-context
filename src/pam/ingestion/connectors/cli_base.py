"""Base class for CLI-backed connectors (gh, gws)."""

from __future__ import annotations

import asyncio
import json
from abc import ABC

import structlog

from pam.common.config import settings
from pam.ingestion.connectors.base import BaseConnector

logger = structlog.get_logger()

_RATE_LIMIT_KEYWORDS = ("rate limit", "rate_limit", "secondary rate", "abuse detection")
_AUTH_KEYWORDS = ("auth", "login", "credentials", "token")
_MAX_RETRIES = 3
_BACKOFF_BASE = 5  # seconds: 5, 15, 45


class ConnectorError(Exception):
    """Raised when a CLI connector encounters an error."""

    def __init__(self, message: str, *, command: list[str] | None = None) -> None:
        super().__init__(message)
        self.command = command


class CliConnector(BaseConnector, ABC):
    """Abstract base for connectors that shell out to CLI tools."""

    cli_binary: str  # Subclass must set: "gh" or "gws"

    async def check_available(self) -> bool:
        """Verify the CLI binary is installed and reachable."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.cli_binary, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    async def run_cli(
        self, args: list[str], *, timeout: int | None = None,
    ) -> dict | list:
        """Run CLI command, parse JSON stdout, raise ConnectorError on failure.

        Retries up to 3 times on rate limit errors with exponential backoff.
        """
        timeout = timeout or settings.cli_timeout
        full_cmd = [self.cli_binary, *args]

        for attempt in range(_MAX_RETRIES):
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                async with asyncio.timeout(timeout):
                    stdout, stderr = await proc.communicate()
            except (asyncio.TimeoutError, TimeoutError):
                proc.kill()
                raise ConnectorError(
                    f"Command timed out after {timeout}s: {' '.join(full_cmd)}",
                    command=full_cmd,
                )

            stderr_text = stderr.decode(errors="replace").strip()

            if proc.returncode == 0:
                logger.info(
                    "cli_run",
                    binary=self.cli_binary,
                    args=args,
                    exit_code=0,
                )
                return json.loads(stdout)

            # Check rate limit — retry with backoff
            stderr_lower = stderr_text.lower()
            if any(kw in stderr_lower for kw in _RATE_LIMIT_KEYWORDS):
                if attempt < _MAX_RETRIES - 1:
                    delay = _BACKOFF_BASE * (3 ** attempt)  # 5, 15, 45
                    logger.warning(
                        "cli_rate_limited",
                        binary=self.cli_binary,
                        attempt=attempt + 1,
                        retry_in=delay,
                    )
                    await asyncio.sleep(delay)
                    continue

            # Check auth error — don't retry
            if any(kw in stderr_lower for kw in _AUTH_KEYWORDS):
                raise ConnectorError(
                    f"Run '{self.cli_binary} auth login' first: {stderr_text}",
                    command=full_cmd,
                )

            # Generic failure
            logger.error(
                "cli_run_failed",
                binary=self.cli_binary,
                args=args,
                exit_code=proc.returncode,
                stderr=stderr_text,
            )
            raise ConnectorError(stderr_text or f"CLI exited with code {proc.returncode}", command=full_cmd)

        # Exhausted retries (only reached on rate limit)
        raise ConnectorError(
            f"Rate limited after {_MAX_RETRIES} retries: {' '.join(full_cmd)}",
            command=full_cmd,
        )

    async def run_cli_raw(
        self, args: list[str], *, timeout: int | None = None,
    ) -> bytes:
        """Run CLI command, return raw stdout bytes (for file content)."""
        timeout = timeout or settings.cli_timeout
        full_cmd = [self.cli_binary, *args]

        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(timeout):
                stdout, stderr = await proc.communicate()
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            raise ConnectorError(
                f"Command timed out after {timeout}s: {' '.join(full_cmd)}",
                command=full_cmd,
            )

        if proc.returncode != 0:
            stderr_text = stderr.decode(errors="replace").strip()
            raise ConnectorError(stderr_text or f"CLI exited with code {proc.returncode}", command=full_cmd)

        logger.info(
            "cli_run_raw",
            binary=self.cli_binary,
            args=args,
            bytes_received=len(stdout),
        )
        return stdout
