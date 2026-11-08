"""Work out which hold events to fire by comparing two polls (no Home Assistant needed)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .api import Hold
from .const import (
    EVENT_HOLD_ADDED,
    EVENT_HOLD_READY,
    EVENT_HOLD_REMOVED,
    EVENT_HOLD_STATUS_CHANGED,
    EVENT_PICKUP_DEADLINE,
    STATUS_READY,
)

HoldEvent = tuple[str, Hold, dict[str, Any]]


def diff_holds(
    previous: list[Hold] | None,
    current: list[Hold],
    now: datetime,
    deadline_days: int,
    notified: set[tuple[str, datetime]],
) -> list[HoldEvent]:
    """Return (event type, hold, extra data) for everything that changed.

    ``previous`` is None on the first poll after setup or a restart: nothing fires
    then, so books that were already waiting do not trigger a flood of alerts.
    ``notified`` remembers deadline warnings already sent and is updated in place.
    """
    events: list[HoldEvent] = []

    if previous is not None:
        before = {h.id: h for h in previous}
        after = {h.id for h in current}
        for hold in current:
            old = before.get(hold.id)
            if old is None:
                events.append((EVENT_HOLD_ADDED, hold, {}))
                if hold.status_name == STATUS_READY:
                    events.append((EVENT_HOLD_READY, hold, {"previous_status": None}))
            elif old.status_name != hold.status_name:
                extra = {"previous_status": old.status_name}
                events.append((EVENT_HOLD_STATUS_CHANGED, hold, extra))
                if hold.status_name == STATUS_READY:
                    events.append((EVENT_HOLD_READY, hold, extra))
        events.extend(
            (EVENT_HOLD_REMOVED, hold, {}) for hold in previous if hold.id not in after
        )

    if deadline_days > 0:
        window = timedelta(days=deadline_days)
        for hold in current:
            if hold.status_name != STATUS_READY or not hold.expires:
                continue
            if not now < hold.expires <= now + window:
                continue
            key = (hold.id, hold.expires)
            if key in notified:
                continue
            notified.add(key)
            if previous is not None:
                days_left = (hold.expires - now).total_seconds() / 86400
                events.append((EVENT_PICKUP_DEADLINE, hold, {"days_left": round(days_left, 1)}))

    return events
