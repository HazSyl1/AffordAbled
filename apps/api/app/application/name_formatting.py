from __future__ import annotations


def capitalize_name(value: str) -> str:
    """Trim a display name and capitalize its first character without altering the rest."""
    clean = value.strip()
    return clean[:1].upper() + clean[1:] if clean else clean
