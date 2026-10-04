"""
Price history tracking: store & analyze flight prices over time.
Enables trend detection, percentage-below-average alerts, price predictions.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median, stdev


def _history_path() -> Path:
    """Store price history."""
    p = Path(__file__).resolve().parent.parent / "data" / "price_history.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _route_key(origin: str, destination: str, cabin: str) -> str:
    """Unique key for a route (ignoring dates)."""
    return f"{origin}→{destination}|{cabin}"


def load_history() -> dict:
    """Load all price history. {route_key: [{date: ISO8601, price: float}, ...]}"""
    p = _history_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except:
        return {}


def save_history(history: dict) -> None:
    """Persist price history."""
    p = _history_path()
    p.write_text(json.dumps(history, indent=2), encoding="utf-8")


def record_price(origin: str, destination: str, cabin: str, price_eur: float) -> None:
    """Record a price observation for a route."""
    history = load_history()
    key = _route_key(origin, destination, cabin)

    if key not in history:
        history[key] = []

    # Avoid duplicates on same day
    today = datetime.now().date().isoformat()
    if history[key] and history[key][-1].get("date") == today:
        # Update if same day (keep lowest price seen)
        if price_eur < history[key][-1]["price"]:
            history[key][-1]["price"] = price_eur
    else:
        # New day, add entry
        history[key].append({"date": today, "price": price_eur})

    save_history(history)


def get_recent_prices(origin: str, destination: str, cabin: str, days: int = 7) -> list[float]:
    """Get last N days of prices for a route."""
    history = load_history()
    key = _route_key(origin, destination, cabin)

    if key not in history:
        return []

    cutoff = (datetime.now().date() - timedelta(days=days)).isoformat()
    prices = [
        entry["price"]
        for entry in history[key]
        if entry.get("date", "") >= cutoff
    ]
    return prices


def get_price_stats(origin: str, destination: str, cabin: str, days: int = 30) -> dict | None:
    """Get statistics (min, max, mean, median, trend) for a route."""
    prices = get_recent_prices(origin, destination, cabin, days)

    if len(prices) < 2:
        return None

    avg = mean(prices)
    med = median(prices)
    mn = min(prices)
    mx = max(prices)
    trend = "falling" if prices[-1] < prices[0] else "rising"
    volatility = stdev(prices) if len(prices) > 1 else 0

    return {
        "min": mn,
        "max": mx,
        "mean": avg,
        "median": med,
        "volatility": volatility,
        "trend": trend,
        "samples": len(prices),
        "days": days,
    }


def price_percentile(price: float, origin: str, destination: str, cabin: str, days: int = 30) -> float | None:
    """What percentile is this price in recent history? (0-100, higher = more expensive)"""
    prices = get_recent_prices(origin, destination, cabin, days)

    if len(prices) < 2:
        return None

    rank = sum(1 for p in prices if p <= price)
    return (rank / len(prices)) * 100
