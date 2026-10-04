"""
Post-fetch filtering: remove results that don't meet quality criteria.
- Too many stops
- Excessive flight duration
- Unrealistic layovers (implied by duration vs stops)
- Low Flying Blue score
"""
from __future__ import annotations
from .models import FlightResult


def _parse_duration_minutes(duration_str: str) -> int | None:
    """Convert '15h 30m' to 930 minutes."""
    if not duration_str or duration_str == "?":
        return None
    try:
        parts = duration_str.split()
        total = 0
        for i, part in enumerate(parts):
            if part.endswith("h"):
                total += int(part[:-1]) * 60
            elif part.endswith("m"):
                total += int(part[:-1])
        return total
    except:
        return None


def filter_excessive_stops(results: list[FlightResult], max_stops: int = 2) -> list[FlightResult]:
    """Remove flights with more than max_stops."""
    return [r for r in results if r.stops <= max_stops]


def filter_excessive_duration(
    results: list[FlightResult],
    max_hours: int = 18,
    consider_both_legs: bool = True,
) -> list[FlightResult]:
    """
    Remove flights where outbound or return exceeds max_hours.
    If consider_both_legs=False, only check outbound.
    """
    filtered = []
    for r in results:
        out_mins = _parse_duration_minutes(r.duration_outbound)
        ret_mins = _parse_duration_minutes(r.duration_return) if r.duration_return else None

        max_mins = max_hours * 60
        out_ok = out_mins is None or out_mins <= max_mins
        ret_ok = ret_mins is None or ret_mins <= max_mins

        if out_ok and (not consider_both_legs or ret_ok):
            filtered.append(r)

    return filtered


def filter_low_fb_score(results: list[FlightResult], min_score: int = -1) -> list[FlightResult]:
    """Remove flights with FB score below threshold. -1 means allow unknown partners."""
    return [r for r in results if r.fb_miles_score() >= min_score]


def filter_results(
    results: list[FlightResult],
    max_stops: int = 2,
    max_flight_hours: int = 18,
    min_fb_score: int = -1,
) -> list[FlightResult]:
    """Apply all filters. Returns filtered list."""
    results = filter_excessive_stops(results, max_stops)
    results = filter_excessive_duration(results, max_flight_hours)
    results = filter_low_fb_score(results, min_fb_score)
    return results
