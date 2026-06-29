"""Stateful newly-assigned tracking. No Home Assistant imports."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


class NewlyAssignedTracker:
    def __init__(self, window_hours: int):
        self._window = timedelta(hours=window_hours)
        self._known: set[str] | None = None      # None => no prior poll yet
        self._recent: dict[str, str] = {}        # key -> first_seen ISO ts

    def update(self, current: set[str], now: datetime | None = None) -> dict[str, Any]:
        if now is None:
            now = datetime.now(timezone.utc)

        if self._known is None:
            new_keys: list[str] = []
        else:
            new_keys = sorted(current - self._known)

        for k in new_keys:
            self._recent[k] = now.isoformat()

        self._known = set(current)
        self._prune(now)

        return {
            "newly_assigned": len(new_keys),
            "new_keys": new_keys,
            "new_last_window": len(self._recent),
        }

    def _prune(self, now: datetime) -> None:
        cutoff = now - self._window
        self._recent = {
            k: ts for k, ts in self._recent.items()
            if datetime.fromisoformat(ts) >= cutoff
        }

    def serialize(self) -> dict[str, Any]:
        return {
            "known": sorted(self._known) if self._known is not None else None,
            "recent": self._recent,
        }

    @classmethod
    def deserialize(cls, blob: dict[str, Any], window_hours: int) -> "NewlyAssignedTracker":
        t = cls(window_hours)
        known = blob.get("known")
        t._known = set(known) if known is not None else None
        t._recent = dict(blob.get("recent", {}))
        return t
