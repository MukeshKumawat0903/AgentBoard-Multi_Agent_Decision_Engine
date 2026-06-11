"""Lightweight in-process application metrics."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from threading import Lock


class AppMetrics:
    """Collect request and business event counters for the running process."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        """Reset all counters. Intended for tests and process startup."""
        with self._lock:
            self._started_at = datetime.now(UTC)
            self._requests_total = 0
            self._request_duration_total_ms = 0.0
            self._responses_by_status: Counter[str] = Counter()
            self._routes: dict[str, dict[str, float | int | str]] = {}
            self._events: Counter[str] = Counter()

    def record_request(self, method: str, path: str, status_code: int, duration_ms: float) -> None:
        """Record one handled HTTP request."""
        route_key = f"{method.upper()} {path}"
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._requests_total += 1
            self._request_duration_total_ms += duration_ms
            self._responses_by_status[str(status_code)] += 1
            route_metrics = self._routes.setdefault(
                route_key,
                {
                    "count": 0,
                    "duration_total_ms": 0.0,
                    "avg_duration_ms": 0.0,
                    "last_status": status_code,
                    "last_seen_at": now,
                },
            )
            route_metrics["count"] = int(route_metrics["count"]) + 1
            route_metrics["duration_total_ms"] = float(route_metrics["duration_total_ms"]) + duration_ms
            route_metrics["avg_duration_ms"] = round(
                float(route_metrics["duration_total_ms"]) / int(route_metrics["count"]),
                2,
            )
            route_metrics["last_status"] = status_code
            route_metrics["last_seen_at"] = now

    def increment_event(self, event_name: str, amount: int = 1) -> None:
        """Increment an application business event counter."""
        with self._lock:
            self._events[event_name] += amount

    def snapshot(self) -> dict:
        """Return a JSON-serializable metrics snapshot."""
        with self._lock:
            uptime = (datetime.now(UTC) - self._started_at).total_seconds()
            avg_duration = (
                round(self._request_duration_total_ms / self._requests_total, 2)
                if self._requests_total
                else 0.0
            )
            routes: dict[str, dict[str, float | int | str]] = {}
            for route_key, route_metrics in self._routes.items():
                routes[route_key] = {
                    "count": int(route_metrics["count"]),
                    "avg_duration_ms": float(route_metrics["avg_duration_ms"]),
                    "last_status": int(route_metrics["last_status"]),
                    "last_seen_at": str(route_metrics["last_seen_at"]),
                }

            return {
                "started_at": self._started_at.isoformat(),
                "uptime_seconds": round(uptime, 3),
                "requests_total": self._requests_total,
                "avg_request_duration_ms": avg_duration,
                "responses_by_status": dict(self._responses_by_status),
                "events": dict(self._events),
                "routes": routes,
            }


app_metrics = AppMetrics()
