"""
CLI for quick one-off flight searches without editing searches.json.
Usage:
  python -m scripts.travel_cli bru hav economy dec
  python -m scripts.travel_cli ams sin business jan-feb
  python -m scripts.travel_cli dus nyc premium dec --alert 1500
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from .models import FlightResult
from . import fetch_playwright, consolidate as consolidate_mod, prepare_email_v2, send_email

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")


def parse_month(month_str: str) -> int:
    """Parse 'jan', 'dec', '12', etc. to month number (1-12)."""
    month_names = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    }
    month_str = month_str.lower()
    if month_str in month_names:
        return month_names[month_str]
    try:
        return int(month_str)
    except ValueError:
        raise ValueError(f"Unknown month: {month_str}")


def build_date_window(month_spec: str, year: int = 2026) -> tuple[str, str]:
    """
    Parse month spec like 'dec', 'jan-feb', etc. into (from, to) dates.
    """
    if '-' in month_spec:
        start_month_str, end_month_str = month_spec.split('-')
        start_month = parse_month(start_month_str)
        end_month = parse_month(end_month_str)
    else:
        start_month = parse_month(month_spec)
        end_month = start_month

    from_date = datetime(year, start_month, 1).date().isoformat()

    # Last day of end month
    if end_month == 12:
        to_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        to_date = datetime(year, end_month + 1, 1).date() - timedelta(days=1)
    to_date = to_date.isoformat()

    return from_date, to_date


def main():
    parser = argparse.ArgumentParser(
        description="Quick one-off flight search"
    )
    parser.add_argument("origins", help="Comma-separated origins (e.g. 'ams,bru,dus')")
    parser.add_argument("destination", help="Destination (e.g. 'hav')")
    parser.add_argument("cabin", choices=["economy", "premium", "business"], help="Cabin class")
    parser.add_argument("months", help="Month(s) (e.g. 'dec', 'jan-feb')")
    parser.add_argument("--alert", type=int, default=None, help="Alert threshold in EUR")
    parser.add_argument("--dry-run", action="store_true", help="Build email but don't send")
    parser.add_argument("--max-stops", type=int, default=2, help="Maximum stops allowed")

    args = parser.parse_args()

    cabin_map = {"economy": "ECONOMY", "premium": "PREMIUM_ECONOMY", "business": "BUSINESS"}
    cabin = cabin_map[args.cabin]

    from_date, to_date = build_date_window(args.months)

    search = {
        "name": f"CLI: {args.origins.upper()} → {args.destination.upper()} ({args.cabin})",
        "enabled": True,
        "origins": [o.strip().upper() for o in args.origins.split(",")],
        "destinations": [args.destination.upper()],
        "cabin": cabin,
        "outbound_window": {"from": from_date, "to": to_date},
        "inbound_window": {"from": from_date, "to": to_date},
        "trip_duration_days": {"min": 0, "max": 30},
        "preferred_airlines": [],
        "max_stops": args.max_stops,
        "alert_below_eur": args.alert or 999999,
        "max_results_per_date": 10,
        "sample_departure_dates": 7,
    }

    (BASE / "data" / "logs").mkdir(parents=True, exist_ok=True)

    # Run fetch
    print(f"Searching {search['origins']} → {search['destination']} ({search['cabin']})...")
    print(f"  Dates: {from_date} to {to_date}")
    print(f"  Alert: below €{args.alert or 'off'}")

    try:
        results = fetch_playwright.fetch(search, timeout_sec=60)
        print(f"  Found: {len(results)} results")
    except Exception as e:
        print(f"  Error: {e}")
        return

    consolidated = consolidate_mod.consolidate_all({search["name"]: results}, [search])

    # For CLI, group by destination (same as dedup behavior)
    by_destination = {}
    for r in results:
        dest = r.destination
        if dest not in by_destination:
            by_destination[dest] = []
        by_destination[dest].append(r)

    for dest in by_destination:
        by_destination[dest].sort(key=lambda x: x.total_price_eur)

    # Build and print email
    settings = {"email": {"to": "schaar000@gmail.com"}}  # Dummy, won't send
    subject, html = prepare_email_v2.build_by_destination(by_destination)

    print(f"\nSubject: {subject}")
    print(f"\n--- Email preview ({len(results)} results) ---")

    if not args.dry_run:
        print("\nSending email...")
        send_email.send(subject, html, settings)
        print("Sent!")
    else:
        preview_path = BASE / "data" / "results" / f"cli_preview_{datetime.now():%Y%m%d_%H%M%S}.html"
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(html, encoding="utf-8")
        print(f"Dry run → {preview_path}")


if __name__ == "__main__":
    main()
