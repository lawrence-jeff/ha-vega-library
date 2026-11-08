"""Anonymous summary of holds for diagnostics (no titles, authors or IDs)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .api import Hold


def summarize_holds(holds: list[Hold]) -> dict[str, Any]:
    """Counts and raw codes only, so a diagnostics file never reveals what someone is reading."""
    codes = Counter((h.status, h.status_name) for h in holds)
    return {
        "count": len(holds),
        "by_status": dict(Counter(h.status_name for h in holds)),
        "raw_status_codes": [
            {"code": code, "treated_as": status, "count": n}
            for (code, status), n in sorted(codes.items(), key=lambda kv: str(kv[0]))
        ],
        "vendors": dict(Counter(str(h.vendor) for h in holds)),
        "holds": [
            {
                "treated_as": h.status_name,
                "raw_status": h.status,
                "position": h.priority,
                "queue_length": h.queue_length,
                "vendor": h.vendor,
                "frozen": h.frozen,
                "has_pickup_by": h.expires is not None,
                "has_cover": h.cover_url is not None,
            }
            for h in holds
        ],
    }
