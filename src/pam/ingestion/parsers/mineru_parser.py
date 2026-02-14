"""MinerU document parser -- CLI wrapper for high-fidelity PDF parsing."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import structlog

from pam.common.config import settings
from pam.common.models import RawDocument
from pam.ingestion.parsers.base import BaseParser, ParsedDocument, ParsedImage, ParsedTable

logger = structlog.get_logger()


class MineruParser(BaseParser):
    """Parses documents using MinerU CLI for high-fidelity extraction.

    MinerU is especially good at preserving document structure from PDFs,
    including tables, images, and reading order.
    """

    def __init__(self, method: str | None = None) -> None:
        self._method = method or settings.mineru_method

    def parse(self, raw_document: RawDocument) -> ParsedDocument:
        """Parse a raw document using MinerU CLI.

        Writes content to temp file, runs `mineru` CLI, reads output.
        """
        ext_map = {
            "text/markdown": ".md",
            "application/pdf": ".pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        }
        ext = ext_map.get(raw_document.content_type, ".bin")

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / f"input{ext}"
            input_path.write_bytes(raw_document.content)
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            # Run MinerU CLI
            cmd = [
                "mineru",
                "-p", str(input_path),
                "-o", str(output_dir),
                "-m", self._method,
            ]

            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=True,
                )
                logger.info(
                    "mineru_parse",
                    source_id=raw_document.source_id,
                    method=self._method,
                )
            except FileNotFoundError:
                raise RuntimeError(
                    "MinerU CLI not found. Install with: pip install 'pam-context[mineru]'"
                )
            except subprocess.CalledProcessError as e:
                logger.error("mineru_parse_failed", stderr=e.stderr[:500])
                raise RuntimeError(f"MinerU parsing failed: {e.stderr[:200]}")
            except subprocess.TimeoutExpired:
                raise RuntimeError("MinerU parsing timed out after 300 seconds")

            # Read output files
            return self._read_output(output_dir, input_path.stem)

    def _read_output(self, output_dir: Path, stem: str) -> ParsedDocument:
        """Read MinerU output files and construct ParsedDocument."""
        # MinerU outputs: {stem}/{stem}.md and {stem}/{stem}_content_list.json
        result_dir = output_dir / stem
        if not result_dir.exists():
            # Sometimes MinerU puts output directly in output_dir
            result_dir = output_dir

        # Find markdown file
        md_path = result_dir / f"{stem}.md"
        if not md_path.exists():
            # Try to find any .md file
            md_files = list(result_dir.glob("*.md"))
            if md_files:
                md_path = md_files[0]
            else:
                raise RuntimeError(f"No markdown output found in {result_dir}")

        markdown_content = md_path.read_text(encoding="utf-8")

        # Find content list JSON
        content_list_path = result_dir / f"{stem}_content_list.json"
        images: list[ParsedImage] = []
        tables: list[ParsedTable] = []

        if content_list_path.exists():
            content_list = json.loads(content_list_path.read_text(encoding="utf-8"))
            images, tables = self._extract_from_content_list(content_list, result_dir)

        return ParsedDocument(
            markdown_content=markdown_content,
            images=images,
            tables=tables,
        )

    def _extract_from_content_list(
        self, content_list: list[dict], result_dir: Path
    ) -> tuple[list[ParsedImage], list[ParsedTable]]:
        """Extract images and tables from MinerU's content_list.json."""
        images: list[ParsedImage] = []
        tables: list[ParsedTable] = []

        for i, item in enumerate(content_list):
            item_type = item.get("type", "")

            if item_type == "image":
                img_path_str = item.get("img_path", "")
                img_data = None
                if img_path_str:
                    img_path = result_dir / img_path_str
                    if img_path.exists():
                        img_data = img_path.read_bytes()

                images.append(
                    ParsedImage(
                        image_data=img_data,
                        caption=item.get("caption"),
                        page_number=item.get("page_idx"),
                        position=i,
                    )
                )

            elif item_type == "table":
                table_md = item.get("text", "") or item.get("table_body", "")
                if table_md.strip():
                    tables.append(
                        ParsedTable(
                            markdown=table_md,
                            caption=item.get("caption"),
                            page_number=item.get("page_idx"),
                            position=i,
                        )
                    )

        return images, tables

    @staticmethod
    def check_installation() -> bool:
        """Check if MinerU CLI is available."""
        return shutil.which("mineru") is not None
