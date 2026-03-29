"""GitHub connector — ingests files from GitHub repos via gh CLI."""

from __future__ import annotations

from pathlib import PurePosixPath

import structlog

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.cli_base import CliConnector

logger = structlog.get_logger()


class GitHubConnector(CliConnector):
    """Ingest .md/.txt files from a GitHub repo using the gh CLI."""

    cli_binary = "gh"

    def __init__(
        self,
        repo: str,
        branch: str = "main",
        paths: list[str] | None = None,
        extensions: list[str] | None = None,
    ) -> None:
        self.repo = repo  # "owner/repo" format
        self.branch = branch
        self.paths = paths or []
        self.extensions = extensions or [".md", ".txt"]
        self._tree_cache: dict[str, str] = {}  # source_id -> git SHA

    async def list_documents(self) -> list[DocumentInfo]:
        tree_data = await self.run_cli(
            ["api", f"/repos/{self.repo}/git/trees/{self.branch}?recursive=1"]
        )

        docs: list[DocumentInfo] = []
        for entry in tree_data.get("tree", []):
            if entry.get("type") != "blob":
                continue

            path = entry["path"]
            ext = PurePosixPath(path).suffix.lower()
            if ext not in self.extensions:
                continue

            if self.paths and not any(path.startswith(prefix) for prefix in self.paths):
                continue

            source_id = f"{self.repo}:{path}"
            self._tree_cache[source_id] = entry["sha"]

            docs.append(DocumentInfo(
                source_id=source_id,
                title=PurePosixPath(path).name,
                source_url=f"https://github.com/{self.repo}/blob/{self.branch}/{path}",
            ))

        logger.info("github_list_documents", repo=self.repo, count=len(docs))
        return docs

    async def fetch_document(self, source_id: str) -> RawDocument:
        _, path = source_id.split(":", 1)
        ext = PurePosixPath(path).suffix.lower()

        content = await self.run_cli_raw([
            "api", f"/repos/{self.repo}/contents/{path}?ref={self.branch}",
            "-H", "Accept: application/vnd.github.raw+json",
        ])

        content_type = "text/markdown" if ext == ".md" else "text/plain"

        return RawDocument(
            content=content,
            content_type=content_type,
            source_id=source_id,
            title=PurePosixPath(path).name,
            source_url=f"https://github.com/{self.repo}/blob/{self.branch}/{path}",
        )

    async def get_content_hash(self, source_id: str) -> str:
        return self._tree_cache[source_id]
