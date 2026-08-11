from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SourceMetadata:
    source_name: str
    series_name: str
    source_url: str
    frequency: str
    unit: str
    delay: str
    transformation: str = "None"
    licence_note: str = "See the source's reuse terms."
    observation_time: str | None = None
    retrieved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


@dataclass
class MarketDataset:
    key: str
    frame: pd.DataFrame
    metadata: SourceMetadata
    stale: bool = False
    from_cache: bool = False
    error: str | None = None
    raw_reference: str | None = None

    @property
    def available(self) -> bool:
        return not self.frame.empty

    @property
    def latest_date(self) -> pd.Timestamp | None:
        if self.frame.empty or "date" not in self.frame:
            return None
        values = pd.to_datetime(self.frame["date"], errors="coerce").dropna()
        return values.max() if not values.empty else None

    def status_label(self) -> str:
        if not self.available:
            return "Unavailable"
        if self.stale:
            return "Stale cached data"
        if self.from_cache:
            return "Cached official data"
        return "Official data loaded"


def unavailable_dataset(
    key: str,
    metadata: SourceMetadata,
    error: Exception | str,
) -> MarketDataset:
    return MarketDataset(
        key=key,
        frame=pd.DataFrame(),
        metadata=metadata,
        stale=True,
        error=str(error),
    )


@dataclass(frozen=True)
class HttpPayload:
    content: bytes
    retrieved_at: str
    from_cache: bool
    stale: bool
    cache_path: str
    content_type: str | None = None
    response_headers: dict[str, Any] = field(default_factory=dict)

