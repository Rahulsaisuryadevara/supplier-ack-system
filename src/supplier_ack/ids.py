"""Stable, readable identifier helpers."""

from __future__ import annotations

from datetime import date
import re


def make_id(prefix: str, sequence: int, width: int = 6) -> str:
    """Return a deterministic identifier such as PO-000123."""
    if not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
        raise ValueError("prefix must contain uppercase letters/digits and start with a letter")
    if sequence < 1:
        raise ValueError("sequence must be >= 1")
    if width < 1:
        raise ValueError("width must be >= 1")
    return f"{prefix}-{sequence:0{width}d}"


def dated_id(prefix: str, sequence: int, on_date: date, width: int = 6) -> str:
    """Return an identifier with a date segment, useful for events and exports."""
    return f"{prefix}-{on_date:%Y%m%d}-{sequence:0{width}d}"
