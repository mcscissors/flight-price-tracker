"""
Fetch flight offers from the Amadeus Flight Offers Search API.
Docs: https://developers.amadeus.com/self-service/category/flights/api-doc/flight-offers-search
"""
from __future__ import annotations
import logging
import re
from datetime import date, timedelta
from typing import Optional

from .models import FlightResult

log = logging.getLogger(__name__)


def _parse_iso_duration(iso: str) -> str:
    """Convert PT10H30M → '10h 30m'."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", iso or "")
    if not m:
        return iso
    h, mn = m.group(1) or "0", m.group(2) or "0"
    parts = []
    if h != "0":
        parts.append(f"{h}h")
    if mn != "0":
        parts.append(f"{mn}m")
    return " ".join(parts) or "0m"


def _sample_dates(window_from: str, window_to: str, n: int) -> list[date]:
    d0 = date.fromisoformat(window_from)
    d1 = date.fromisoformat(window_to)
    total = (d1 - d0).days
    if total <= 0:
        return [d0]
    step = max(1, total // max(1, n - 1))
    dates = []
    for i in range(n):
        d = d0 + timedelta(days=i * step)
        if d > d1:
            break
        dates.append(d)
    if dates[-1] != d1:
        dates.append(d1)
    return dates[:n]


def _parse_offer(offer: dict, search_name: str, origin: str, dest: str, cabin: str) -> FlightResult:
    price = float(offer["price"]["grandTotal"])
    itins = offer["itineraries"]
    out_itin = itins[0]
    ret_itin = itins[1] if len(itins) > 1 else None

    out_segs = out_itin["segments"]
    carriers = list(dict.fromkeys(s["carrierCode"] for s in out_segs))
    stops = len(out_segs) - 1

    dep_date = out_segs[0]["departure"]["at"][:10]
    ret_date = ret_itin["segments"][0]["departure"]["at"][:10] if ret_itin else None

    return FlightResult(
        source="amadeus",
        search_name=search_name,
        origin=origin,
        destination=dest,
        departure_date=dep_date,
        return_date=ret_date,
        cabin=cabin,
        total_price_eur=price,
        airline_codes=carriers,
        stops=stops,
        duration_outbound=_parse_iso_duration(out_itin.get("duration", "")),
        duration_return=_parse_iso_duration(ret_itin.get("duration", "")) if ret_itin else None,
        booking_url=None,
        raw=offer,
    )


def fetch(search: dict, client) -> list[FlightResult]:
    """Fetch offers for one search config block. Returns [] on any error."""
    results: list[FlightResult] = []
    cabin = search["cabin"]
    n_dates = search.get("sample_departure_dates", 6)
    max_per_date = search.get("max_results_per_date", 3)
    max_stops = search.get("max_stops", 1)

    dep_dates = _sample_dates(
        search["outbound_window"]["from"],
        search["outbound_window"]["to"],
        n_dates,
    )
    in_from = date.fromisoformat(search["inbound_window"]["from"]) if "inbound_window" in search else None
    in_to   = date.fromisoformat(search["inbound_window"]["to"])   if "inbound_window" in search else None
    min_days = search["trip_duration_days"]["min"]
    max_days = search["trip_duration_days"]["max"]
    mid_days = (min_days + max_days) // 2

    for origin in search["origins"]:
        for dest in search["destinations"]:
            for dep in dep_dates:
                ret = dep + timedelta(days=mid_days)
                if in_from and in_to and not (in_from <= ret <= in_to):
                    continue

                try:
                    resp = client.shopping.flight_offers_search.get(
                        originLocationCode=origin,
                        destinationLocationCode=dest,
                        departureDate=dep.isoformat(),
                        returnDate=ret.isoformat(),
                        adults=1,
                        travelClass=cabin,
                        max=max_per_date,
                        currencyCode="EUR",
                        nonStop=(max_stops == 0),
                    )
                    for offer in resp.data:
                        results.append(_parse_offer(offer, search["name"], origin, dest, cabin))
                    log.info(f"  Amadeus {origin}→{dest} {dep}: {len(resp.data)} offers")
                except Exception as e:
                    log.warning(f"  Amadeus {origin}→{dest} {dep}: {e}")

    return results
