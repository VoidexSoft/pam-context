"""Shared utility functions."""


def escape_like(value: str) -> str:
    """Escape SQL ILIKE/LIKE wildcard characters.

    Prevents user-controlled input from being interpreted as wildcard patterns
    when used in ILIKE queries.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
