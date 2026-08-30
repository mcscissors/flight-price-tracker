"""
Fetch flight prices from Google Flights via the fast-flights library.
Uses an unofficial reverse-engineered API — treat as supplementary to Amadeus.
Library: https://github.com/AWeirdDev/flights  (package: fast-flights)

API as of fast-flights >= 0.5:
  create_filter / create_query -> Query
  get_flights(query) -> ResultList[Flights]
  Flights: .price (str "EUR 1,234"), .airlines (list[Airline]), .flights (list[SingleFlight])
  SingleFlight: .from_airport, .to_airport, .departure, .arrival, .duration
  Airline: .code, .name
"""
from __future__ import annotations
import concurrent.futures
import logging
import re
from datetime import date, timedelta
from typing import Optional

from .models import FlightResult

log = logging.getLogger(__name__)

try:
    from fast_flights import (
        FlightQuery,
        Passengers,
        create_filter,  # alias for create_query
        get_flights,
    )
    from fast_flights.model import Flights as GFlights
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    log.warning("fast-flights not installed — Google Flights source disabled. Run: pip install fast-flights")

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


_CABIN_MAP = {
    "ECONOMY":         "economy",
    "PREMIUM_ECONOMY": "premium-economy",
    "BUSINESS":        "business",
    "FIRST":           "first",
}


def _parse_price_eur(price_str: str) -> Optional[float]:
    """Parse a price string like 'EUR 1,234' or '€ 1.234' into a float."""
    if not price_str:
        return None
    digits = re.sub(r"[^\d.]", "", price_str.replace(",", ""))
    try:
        return float(digits)
    except ValueError:
        return None


def _duration_str(dur) -> str:
    """Convert whatever duration field we get to a readable string."""
    if dur is None:
        return "?"
    s = str(dur)
    # Already "10 hr 30 min" style
    if "hr" in s or "min" in s or "h" in s:
        return s
    # ISO PT10H30M
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", s)
    if m:
        parts = []
        if m.group(1):
            parts.append(f"{m.group(1)}h")
        if m.group(2):
            parts.append(f"{m.group(2)}m")
        return " ".join(parts) or "?"
    return s


def _sample_dates(window_from: str, window_to: str, n: int) -> list[date]:
    d0 = date.fromisoformat(window_from)
    d1 = date.fromisoformat(window_to)
    total = (d1 - d0).days
    if total <= 0:
        return [d0]
    step = max(1, total // max(1, n - 1))
    dates = [d0 + timedelta(days=i * step) for i in range(n)]
    return [d for d in dates if d <= d1][:n]


def fetch(search: dict, timeout_sec: int = 60) -> list[FlightResult]:
    """Fetch from Google Flights for one search block. Returns [] if unavailable."""
    if not _AVAILABLE:
        return []

    results: list[FlightResult] = []
    cabin_key  = _CABIN_MAP.get(search["cabin"], "economy")
    n_dates    = search.get("sample_departure_dates", 6)
    max_results = search.get("max_results_per_date", 3)
    min_days   = search["trip_duration_days"]["min"]
    max_days   = search["trip_duration_days"]["max"]
    mid_days   = (min_days + max_days) // 2
    max_stops  = search.get("max_stops", None)

    dep_dates = _sample_dates(
        search["outbound_window"]["from"],
        search["outbound_window"]["to"],
        n_dates,
    )
    in_from = date.fromisoformat(search["inbound_window"]["from"]) if "inbound_window" in search else None
    in_to   = date.fromisoformat(search["inbound_window"]["to"])   if "inbound_window" in search else None

    for origin in search["origins"]:
        for dest in search["destinations"]:
            for dep in dep_dates:
                ret = dep + timedelta(days=mid_days)
                if in_from and in_to and not (in_from <= ret <= in_to):
                    continue

                try:
                    query = create_filter(
                        flights=[
                            FlightQuery(date=dep.isoformat(), from_airport=origin, to_airport=dest),
                            FlightQuery(date=ret.isoformat(), from_airport=dest,   to_airport=origin),
                        ],
                        trip="round-trip",
                        seat=cabin_key,
                        passengers=Passengers(adults=1),
                        currency="EUR",
                        max_stops=max_stops,
                    )
                    try:
                        result_list = _pool.submit(get_flights, query).result(timeout=timeout_sec)
                    except concurrent.futures.TimeoutError:
                        log.warning("  Google %s->%s %s: timed out after %ds", origin, dest, dep, timeout_sec)
                        continue

                    if not result_list:
                        continue

                    count = 0
                    for gf in result_list:
                        if count >= max_results:
                            break
                        price = _parse_price_eur(str(getattr(gf, "price", "") or ""))
                        if price is None:
                            continue

                        airlines = getattr(gf, "airlines", []) or []
                        codes    = [getattr(a, "code", str(a)) for a in airlines]
                        flights  = getattr(gf, "flights", []) or []
                        stops    = max(0, len(flights) - 1) if flights else 0

                        # Duration from first leg
                        dur_out = "?"
                        if flights:
                            dur_out = _duration_str(getattr(flights[0], "duration", None))

                        results.append(FlightResult(
                            source="google",
                            search_name=search["name"],
                            origin=origin,
                            destination=dest,
                            departure_date=dep.isoformat(),
                            return_date=ret.isoformat(),
                            cabin=search["cabin"],
                            total_price_eur=price,
                            airline_codes=codes or ["?"],
                            stops=stops,
                            duration_outbound=dur_out,
                            duration_return=None,
                            booking_url=None,
                            raw={},
                        ))
                        count += 1

                    log.info("  Google %s->%s %s: %d offers", origin, dest, dep, count)

                except Exception as e:
                    log.warning("  Google %s->%s %s: %s", origin, dest, dep, e)

    return results
