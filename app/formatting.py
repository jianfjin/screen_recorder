"""Pure formatting helpers (no Qt)."""
from __future__ import annotations


def format_duration(seconds: float) -> str:
    """Format elapsed seconds for the recording timer label.

    < 1 hour  -> "MM:SS" (minutes zero-padded to 2 digits)
    >= 1 hour -> "HH:MM:SS"
    Fractional seconds are truncated (floor).
    """
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
