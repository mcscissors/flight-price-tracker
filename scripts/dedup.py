"""
Deduplicate flights across searches.
Same route + date + airline = same flight, show only once with lowest price.
"""
from .models import FlightResult


def deduplicate(consolidated: dict[str, list[FlightResult]]) -> dict[str, list[FlightResult]]:
    """
    Deduplicate flights across all searches.
    Keeps the result with the lowest price for each unique flight.
    Returns a new dict with 'dedup' as the key (not per-search anymore).
    """
    seen = {}  # (origin, destination, dep_date, ret_date, airlines_tuple, stops) -> FlightResult

    for search_name, results in consolidated.items():
        for r in results:
            key = (
                r.origin,
                r.destination,
                r.departure_date,
                r.return_date or "",
                tuple(r.airline_codes),  # tuple of airline codes
                r.stops,
            )

            if key not in seen or r.total_price_eur < seen[key].total_price_eur:
                seen[key] = r

    # Group deduped results by destination for the new email layout
    by_destination = {}
    for r in seen.values():
        dest = r.destination
        if dest not in by_destination:
            by_destination[dest] = []
        by_destination[dest].append(r)

    # Sort by destination, then by price within each destination
    result = {}
    for dest in sorted(by_destination.keys()):
        result[dest] = sorted(by_destination[dest], key=lambda x: x.total_price_eur)

    return result
