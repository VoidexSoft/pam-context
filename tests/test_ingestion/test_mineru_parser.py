"""Tests for MinerU parser."""

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, mock_open

import pytest

from pam.common.models import RawDocument
from pam.ingestion.parsers.mineru_parser import MineruParser


@pytest.fixture
def raw_pdf():
    return RawDocument(
        content=b"%PDF-1.4 fake pdf content",
        content_type="application/pdf",
        metadata={},
        source_id="test.pdf",
        title="Test PDF",
    )


class TestMineruParser:
    @patch("pam.ingestion.parsers.mineru_parser.subprocess.run")
    def test_parse_calls_cli(self, mock_run, raw_pdf):
        """Test that parse calls the MinerU CLI with correct args."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        parser = MineruParser(method="auto")

        # We need to mock the output file reading too
        with patch.object(parser, "_read_output") as mock_read:
            mock_read.return_value = MagicMock(
                markdown_content="# Parsed",
                images=[],
                tables=[],
                _docling_doc=None,
            )
            result = parser.parse(raw_pdf)

        # Verify CLI was called
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "mineru"
        assert "-p" in cmd
        assert "-o" in cmd
        assert "-m" in cmd
        assert "auto" in cmd

    @patch("pam.ingestion.parsers.mineru_parser.subprocess.run")
    def test_parse_cli_not_found(self, mock_run, raw_pdf):
        """Test error when MinerU is not installed."""
        mock_run.side_effect = FileNotFoundError()

        parser = MineruParser()
        with pytest.raises(RuntimeError, match="MinerU CLI not found"):
            parser.parse(raw_pdf)

    @patch("pam.ingestion.parsers.mineru_parser.subprocess.run")
    def test_parse_cli_failure(self, mock_run, raw_pdf):
        """Test error when MinerU CLI fails."""
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "mineru", stderr="Error")

        parser = MineruParser()
        with pytest.raises(RuntimeError, match="MinerU parsing failed"):
            parser.parse(raw_pdf)

    @patch("pam.ingestion.parsers.mineru_parser.subprocess.run")
    def test_parse_timeout(self, mock_run, raw_pdf):
        """Test error on timeout."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("mineru", 300)

        parser = MineruParser()
        with pytest.raises(RuntimeError, match="timed out"):
            parser.parse(raw_pdf)

    def test_read_output(self, tmp_path):
        """Test reading MinerU output files."""
        parser = MineruParser()

        # Create mock output structure
        stem = "input"
        result_dir = tmp_path / stem
        result_dir.mkdir()

        # Create markdown file
        md_content = "# Test Document\n\nSome content here."
        (result_dir / f"{stem}.md").write_text(md_content)

        # Create content list
        content_list = [
            {"type": "text", "text": "Some text"},
            {"type": "table", "text": "| A | B |\n|---|---|\n| 1 | 2 |", "page_idx": 0},
            {"type": "image", "img_path": "img_0.png", "caption": "Figure 1", "page_idx": 1},
        ]
        (result_dir / f"{stem}_content_list.json").write_text(json.dumps(content_list))

        # Create a fake image
        (result_dir / "img_0.png").write_bytes(b"fake png data")

        result = parser._read_output(tmp_path, stem)

        assert result.markdown_content == md_content
        assert len(result.tables) == 1
        assert "| A | B |" in result.tables[0].markdown
        assert len(result.images) == 1
        assert result.images[0].image_data == b"fake png data"
        assert result.images[0].caption == "Figure 1"
        assert result._docling_doc is None

    def test_read_output_no_content_list(self, tmp_path):
        """Test reading output without content_list.json."""
        parser = MineruParser()

        stem = "input"
        result_dir = tmp_path / stem
        result_dir.mkdir()
        (result_dir / f"{stem}.md").write_text("# Simple doc")

        result = parser._read_output(tmp_path, stem)
        assert result.markdown_content == "# Simple doc"
        assert result.images == []
        assert result.tables == []

    def test_check_installation(self):
        """Test installation check."""
        with patch("pam.ingestion.parsers.mineru_parser.shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/mineru"
            assert MineruParser.check_installation() is True

            mock_which.return_value = None
            assert MineruParser.check_installation() is False
