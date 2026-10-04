"""
Merge results from all sources, deduplicate, rank by price, flag alerts.
Supports both simple threshold alerts and smarter percentage-based alerts.
"""
from __future__ import annotations
from .models import FlightResult
from . import smart_alerts


def consolidate(results: list[FlightResult], search: dict) -> list[FlightResult]:
    """
    For a single search block: deduplicate, sort by price, mark alerts.
    Deduplication key: (origin, dest, dep_date, ret_date, airlines, stops).
    If two sources return the same flight, keep the lower-priced entry.
    """
    threshold = search.get("alert_below_eur")
    preferred = set(search.get("preferred_airlines", []))

    seen: dict[tuple, FlightResult] = {}
    for r in results:
        key = (
            r.origin, r.destination,
            r.departure_date, r.return_date or "",
            ",".join(sorted(r.airline_codes)),
            r.stops,
        )
        if key not in seen or r.total_price_eur < seen[key].total_price_eur:
            seen[key] = r

    unique = list(seen.values())

    # Sort by price, with a 5% price band where miles generosity breaks the tie.
    # Within the band: preferred airlines first, then highest FB miles score.
    if unique:
        cheapest = min(r.total_price_eur for r in unique)
        band = cheapest * 1.05

        def sort_key(r: FlightResult):
            in_band = r.total_price_eur <= band
            has_preferred = any(c in preferred for c in r.airline_codes) if preferred else True
            # Primary: price. Secondary within band: preferred flag + miles score.
            return (
                r.total_price_eur,
                0 if (in_band and has_preferred) else 1,
                -r.fb_miles_score() if in_band else 0,
            )
    else:
        def sort_key(r: FlightResult):
            return (r.total_price_eur,)

    unique.sort(key=sort_key)

    # Only keep flights operated by a Flying Blue partner airline.
    unique = [r for r in unique if r.fb_partner() is not None]

    # Mark alerts: simple threshold or smart percentage-based.
    use_smart_alerts = search.get("smart_alerts", False)
    if unique and threshold is not None:
        # Gather recent prices for percentage baseline (if using smart alerts).
        all_prices = [r.total_price_eur for r in unique]

        for r in unique:
            # Suppress repeated alerts for same route within 24h.
            route_key = smart_alerts.make_route_key(r.origin, r.destination, r.departure_date, r.cabin)
            if smart_alerts.should_suppress_repeat_alert(route_key):
                continue

            # Check alert condition: threshold or percentage-based.
            if use_smart_alerts:
                should_alert = smart_alerts.should_alert_percentage(r.total_price_eur, all_prices)
            else:
                should_alert = smart_alerts.should_alert_threshold(r.total_price_eur, threshold)

            if should_alert:
                r.alert = True
                smart_alerts.record_alert(route_key)

    # Only return results that meet the threshold (all results if no threshold set).
    if threshold is not None:
        unique = [r for r in unique if r.alert]

    return unique


def consolidate_all(
    all_results: dict[str, list[FlightResult]],
    searches: list[dict],
) -> dict[str, list[FlightResult]]:
    """Consolidate per search name. all_results keys are search names."""
    out = {}
    search_map = {s["name"]: s for s in searches}
    for name, results in all_results.items():
        search = search_map.get(name, {})
        out[name] = consolidate(results, search)
    return out
