"""Cursor-based pagination utilities for list endpoints."""

import base64
import json
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 50


def encode_cursor(last_id: str, sort_value: str) -> str:
    """Encode a pagination cursor from the last item's ID and sort value."""
    payload = json.dumps({"id": last_id, "sv": sort_value}, sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> dict:
    """Decode a pagination cursor into its ID and sort value components."""
    raw = base64.urlsafe_b64decode(cursor.encode())
    return json.loads(raw)


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response envelope."""

    items: list[T]
    total: int
    cursor: str = ""
