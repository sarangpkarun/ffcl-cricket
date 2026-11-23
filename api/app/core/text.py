"""Checks on text people type, so a name or message cannot hide characters that change how it is shown."""

import re

# control characters (except tab and newline, allowed in messages), zero-width and direction-changing characters, BOM
_HIDDEN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_LINE = re.compile(r"[\r\n\t\u2028\u2029]")


def has_hidden(v: str) -> bool:
    return bool(_HIDDEN.search(v))


def single_line(v: str) -> str:
    """A name, title or label: trimmed, one line, no hidden or direction-changing characters."""
    v = v.strip()
    if has_hidden(v) or _LINE.search(v):
        raise ValueError("Contains characters that are not allowed (control or direction-changing)")
    return v


def message(v: str) -> str:
    """A longer text: line breaks are fine, hidden and direction-changing characters are not."""
    if has_hidden(v):
        raise ValueError("Contains characters that are not allowed (control or direction-changing)")
    return v
