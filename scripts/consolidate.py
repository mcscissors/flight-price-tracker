"""
Merge results from all sources, deduplicate, rank by price, flag alerts.
"""
from __future__ import annotations
from .models import FlightResult


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
        cheapest = unique[0].total_price_eur
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

    for r in unique:
        if threshold is not None and r.total_price_eur < threshold:
            r.alert = True

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
