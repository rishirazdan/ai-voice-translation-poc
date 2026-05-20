from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from statistics import mean
from threading import Lock


@dataclass(frozen=True)
class TurnLatencyMetric:
    session_id: str
    leg: str
    event_type: str
    source_language: str
    target_language: str
    input_text_length: int
    output_text_length: int
    token_count: int
    ingest_to_translate_start_ms: float
    translate_ms: float
    token_emit_ms: float
    estimated_tts_ms: float
    total_estimated_turn_ms: float


class LatencyTracker:
    def __init__(self, sample_size: int = 500) -> None:
        self._items: deque[TurnLatencyMetric] = deque(maxlen=max(sample_size, 1))
        self._lock = Lock()

    def add(self, metric: TurnLatencyMetric) -> None:
        with self._lock:
            self._items.append(metric)

    def reset(self) -> None:
        with self._lock:
            self._items.clear()

    def recent(self, limit: int = 20) -> list[dict[str, object]]:
        if limit < 1:
            limit = 1
        with self._lock:
            items = list(self._items)[-limit:]
        return [asdict(item) for item in items]

    def summary(self) -> dict[str, object]:
        with self._lock:
            items = list(self._items)
        count = len(items)
        if not items:
            return {
                "count": 0,
                "avg_total_estimated_turn_ms": None,
                "p95_total_estimated_turn_ms": None,
                "avg_translate_ms": None,
                "avg_token_emit_ms": None,
            }

        totals = sorted(item.total_estimated_turn_ms for item in items)
        idx95 = max(int(round(0.95 * (count - 1))), 0)
        return {
            "count": count,
            "avg_total_estimated_turn_ms": round(mean(totals), 2),
            "p95_total_estimated_turn_ms": round(totals[idx95], 2),
            "avg_translate_ms": round(mean(item.translate_ms for item in items), 2),
            "avg_token_emit_ms": round(mean(item.token_emit_ms for item in items), 2),
        }
