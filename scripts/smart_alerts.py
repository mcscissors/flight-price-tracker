"""
Smarter alert logic beyond simple threshold comparison.
- Percentage-based alerts (X% below rolling average)
- Suppress repeated alerts for same route within N hours
- Track alert history to detect trends
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


def _alert_history_path() -> Path:
    """Store alert history per search/route to suppress spam."""
    p = Path(__file__).resolve().parent.parent / "data" / "alert_history.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_alert_history() -> dict:
    """Load historical alerts. Returns {route_key: {"last_alert": ISO8601, "times_alerted": int}}."""
    p = _alert_history_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except:
        return {}


def _save_alert_history(history: dict) -> None:
    """Persist alert history."""
    p = _alert_history_path()
    p.write_text(json.dumps(history, indent=2, default=str), encoding="utf-8")


def should_alert_threshold(
    price_eur: float,
    threshold_eur: float,
) -> bool:
    """Simple threshold check. True if price <= threshold."""
    return price_eur <= threshold_eur


def should_alert_percentage(
    price_eur: float,
    recent_prices: list[float],
    threshold_pct: float = 15,
) -> bool:
    """
    Alert if price is X% below recent average.
    Requires at least 3 price samples to establish baseline.
    """
    if len(recent_prices) < 3:
        return False
    avg = sum(recent_prices) / len(recent_prices)
    pct_below = ((avg - price_eur) / avg) * 100
    return pct_below >= threshold_pct


def should_suppress_repeat_alert(
    route_key: str,
    hours_between_alerts: int = 24,
) -> bool:
    """
    Suppress alert if we alerted for this route recently.
    Returns True if we should SUPPRESS (don't alert).
    """
    history = _load_alert_history()
    if route_key not in history:
        return False

    last_alert_str = history[route_key].get("last_alert")
    if not last_alert_str:
        return False

    try:
        last_alert = datetime.fromisoformat(last_alert_str)
        time_since = datetime.now() - last_alert
        return time_since < timedelta(hours=hours_between_alerts)
    except:
        return False


def record_alert(route_key: str) -> None:
    """Record that we alerted for this route/date combo."""
    history = _load_alert_history()
    if route_key not in history:
        history[route_key] = {"last_alert": None, "times_alerted": 0}

    history[route_key]["last_alert"] = datetime.now().isoformat()
    history[route_key]["times_alerted"] += 1
    _save_alert_history(history)


def make_route_key(origin: str, destination: str, departure_date: str, cabin: str) -> str:
    """Unique key for a route (ignoring return date for simplicity)."""
    return f"{origin}→{destination}|{departure_date}|{cabin}"
