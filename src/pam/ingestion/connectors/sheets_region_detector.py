"""Region detector for Google Sheets — identifies tables, notes, and config sections.

A "region" is a contiguous block of cells with a consistent structure.
Types:
  - table: structured data with headers and rows
  - notes: free-text content (paragraphs, bullet points)
  - config: key-value pairs (2 columns, many rows)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()


@dataclass
class SheetRegion:
    """A detected region within a sheet tab."""

    type: str  # "table", "notes", "config"
    start_row: int
    end_row: int  # inclusive
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    raw_text: str = ""  # for notes regions


def detect_regions(cells: list[list[str]], tab_name: str = "Sheet1") -> list[SheetRegion]:
    """Detect regions in a 2D grid of cell values.

    Strategy:
    1. Split into blocks separated by blank rows.
    2. Classify each block by structure.
    """
    if not cells:
        return []

    blocks = _split_into_blocks(cells)
    regions = []

    for start_row, block in blocks:
        region = _classify_block(block, start_row)
        if region is not None:
            regions.append(region)

    logger.info(
        "regions_detected",
        tab=tab_name,
        count=len(regions),
        types=[r.type for r in regions],
    )
    return regions


def _split_into_blocks(cells: list[list[str]]) -> list[tuple[int, list[list[str]]]]:
    """Split the grid into contiguous non-empty blocks, separated by blank rows.

    Returns list of (start_row_index, block_rows).
    """
    blocks: list[tuple[int, list[list[str]]]] = []
    current_block: list[list[str]] = []
    block_start = 0

    for i, row in enumerate(cells):
        if _is_blank_row(row):
            if current_block:
                blocks.append((block_start, current_block))
                current_block = []
        else:
            if not current_block:
                block_start = i
            current_block.append(row)

    if current_block:
        blocks.append((block_start, current_block))

    return blocks


def _is_blank_row(row: list[str]) -> bool:
    """Check if a row is entirely empty or whitespace."""
    return all(cell.strip() == "" for cell in row)


def _classify_block(block: list[list[str]], start_row: int) -> SheetRegion | None:
    """Classify a block as table, config, or notes."""
    if not block:
        return None

    # Single row — could be a title/note or single-row table
    if len(block) == 1:
        non_empty = [c for c in block[0] if c.strip()]
        if len(non_empty) <= 2:
            return SheetRegion(
                type="notes",
                start_row=start_row,
                end_row=start_row,
                raw_text=" ".join(non_empty),
            )
        # Single row with many columns — likely a header-only table
        return SheetRegion(
                type="table",
                start_row=start_row,
                end_row=start_row,
                headers=[c.strip() for c in block[0]],
                rows=[],
            )

    # Check if it's a config (key-value pairs): exactly 2 non-empty columns consistently
    if _is_config_block(block):
        return SheetRegion(
            type="config",
            start_row=start_row,
            end_row=start_row + len(block) - 1,
            headers=[block[0][0].strip(), block[0][1].strip()] if len(block[0]) >= 2 else ["Key", "Value"],
            rows=[[c.strip() for c in row[:2]] for row in block[1:]],
        )

    # Check if it's a table (consistent column count, header row)
    if _is_table_block(block):
        headers = [c.strip() for c in block[0]]
        rows = [[c.strip() for c in row] for row in block[1:]]
        return SheetRegion(
            type="table",
            start_row=start_row,
            end_row=start_row + len(block) - 1,
            headers=headers,
            rows=rows,
        )

    # Check for notes: mostly single-column text, bullets, paragraphs
    if _is_notes_block(block):
        lines = []
        for row in block:
            non_empty = [c.strip() for c in row if c.strip()]
            if non_empty:
                lines.append(" ".join(non_empty))
        return SheetRegion(
            type="notes",
            start_row=start_row,
            end_row=start_row + len(block) - 1,
            raw_text="\n".join(lines),
        )

    # Default: treat as table (best effort)
    headers = [c.strip() for c in block[0]]
    rows = [[c.strip() for c in row] for row in block[1:]]
    return SheetRegion(
        type="table",
        start_row=start_row,
        end_row=start_row + len(block) - 1,
        headers=headers,
        rows=rows,
    )


def _is_config_block(block: list[list[str]]) -> bool:
    """A config block has exactly 2 non-empty columns per row (key-value pairs)."""
    if len(block) < 2:
        return False

    for row in block:
        non_empty = [c for c in row if c.strip()]
        if len(non_empty) != 2:
            return False
    return True


def _is_table_block(block: list[list[str]]) -> bool:
    """A table block has a consistent number of non-empty columns and >= 3 columns or >= 3 rows."""
    if len(block) < 2:
        return False

    header = block[0]
    non_empty_header = sum(1 for c in header if c.strip())
    if non_empty_header < 2:
        return False

    # Check that data rows have similar column occupancy
    consistent = 0
    for row in block[1:]:
        non_empty_row = sum(1 for c in row if c.strip())
        if non_empty_row >= non_empty_header - 1:  # Allow some flexibility
            consistent += 1

    return consistent >= len(block[1:]) * 0.6  # At least 60% consistent


def _is_notes_block(block: list[list[str]]) -> bool:
    """A notes block has mostly single-column text or free-form content."""
    single_col_rows = 0
    for row in block:
        non_empty = [c for c in row if c.strip()]
        if len(non_empty) <= 1:
            single_col_rows += 1

    return single_col_rows >= len(block) * 0.7  # 70%+ rows are single-column
