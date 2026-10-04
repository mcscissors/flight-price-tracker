"""
Auto-calculate search date windows based on today's date.
No more manual editing of searches.json — just set 'days_ahead' on each search.
"""
from datetime import datetime, timedelta
import json
from pathlib import Path


def apply_auto_dates(searches_config: dict) -> dict:
    """
    Apply auto-calculated date windows.
    Each search can specify 'days_from_today' and 'days_duration' instead of fixed dates.
    Example:
      "outbound_window_config": {"days_from_today": 0, "days_duration": 90}
    becomes:
      "outbound_window": {"from": "2026-10-04", "to": "2027-01-02"}
    """
    today = datetime.now().date()

    for search in searches_config.get("searches", []):
        # Outbound window
        if "outbound_window_config" in search:
            cfg = search.pop("outbound_window_config")
            start_days = cfg.get("days_from_today", 0)
            duration = cfg.get("days_duration", 90)

            from_date = (today + timedelta(days=start_days)).isoformat()
            to_date = (today + timedelta(days=start_days + duration)).isoformat()
            search["outbound_window"] = {"from": from_date, "to": to_date}

        # Inbound window
        if "inbound_window_config" in search:
            cfg = search.pop("inbound_window_config")
            start_days = cfg.get("days_from_today", 0)
            duration = cfg.get("days_duration", 90)

            from_date = (today + timedelta(days=start_days)).isoformat()
            to_date = (today + timedelta(days=start_days + duration)).isoformat()
            search["inbound_window"] = {"from": from_date, "to": to_date}

    return searches_config
