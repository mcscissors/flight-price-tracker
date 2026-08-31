"""
Fetch flight prices from Google Flights via Playwright (headless Chromium).

Reuses fast-flights URL generation (Query.url()) but parses the response
with its own parser — the fast-flights parse_js() targets an older Google
JSON structure; this file handles the current ds:1 layout directly.

Install once:
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import date, timedelta
from typing import Optional

from .models import FlightResult

log = logging.getLogger(__name__)

try:
    from fast_flights import FlightQuery, Passengers, create_filter
    _FF_AVAILABLE = True
except ImportError:
    _FF_AVAILABLE = False
    log.warning("fast-flights not installed — run: pip install fast-flights")

try:
    from playwright.async_api import async_playwright
    _PW_AVAILABLE = True
except ImportError:
    _PW_AVAILABLE = False
    log.warning("playwright not installed — run: pip install playwright && playwright install chromium")

_CABIN_MAP = {
    "ECONOMY":         "economy",
    "PREMIUM_ECONOMY": "premium-economy",
    "BUSINESS":        "business",
    "FIRST":           "first",
}


def _sample_dates(window_from: str, window_to: str, n: int) -> list[date]:
    d0 = date.fromisoformat(window_from)
    d1 = date.fromisoformat(window_to)
    total = (d1 - d0).days
    if total <= 0:
        return [d0]
    step = max(1, total // max(1, n - 1))
    dates = [d0 + timedelta(days=i * step) for i in range(n)]
    return [d for d in dates if d <= d1][:n]


def _duration_str(minutes) -> str:
    if minutes is None:
        return "?"
    try:
        m = int(minutes)
        return f"{m // 60}h {m % 60}m"
    except (ValueError, TypeError):
        return str(minutes)


def _extract_json_data(js_text: str) -> Optional[list]:
    """
    Extract the data array from the ds:1 AF_initDataCallback payload.

    The callback may appear in a standalone script or embedded in HTML.
    The key names may be surrounded by escaped quotes (backslash-escaped
    when the callback sits inside a JavaScript string literal).

    Uses raw_decode to parse exactly the JSON array and nothing beyond it,
    avoiding issues with rsplit on complex sideChannel payloads.
    """
    # Try both unescaped ('ds:1') and JS-string-escaped (\'ds:1\') forms.
    for marker in [
        "AF_initDataCallback({key: 'ds:1'",
        r"AF_initDataCallback({key: \'ds:1\'",
        'AF_initDataCallback({key: "ds:1"',
    ]:
        idx = js_text.find(marker)
        if idx != -1:
            break
    else:
        return None

    # Find "data:" after the marker, then the opening "[" of the array.
    snippet = js_text[idx:]
    data_idx = snippet.find("data:")
    if data_idx == -1:
        return None

    array_start = snippet.find("[", data_idx)
    if array_start == -1:
        return None

    # raw_decode parses exactly one JSON value and returns (value, end_pos).
    try:
        value, _ = json.JSONDecoder().raw_decode(snippet, array_start)
        return value
    except json.JSONDecodeError:
        return None


def _parse_flights(js_text: str) -> list[dict]:
    """
    Parse flight results from the current Google Flights ds:1 JSON structure.

    Payload layout (as observed 2026-08-30):
      payload[0]  metadata
      payload[1]  airport info
      payload[2]  [[outbound_flight_entry, ...], null, 0, 0, [1]]
      payload[3]  [[[ return_flight_entry, ...]], ...]

    Each flight entry:
      entry[0]  [airline_code, [airline_names], [segments], origin,
                 dep_date, dep_time, dest, arr_date, arr_time,
                 elapsed_min, ...]
      entry[1]  [[null, price_eur], "booking_token"]

    Returns list of dicts with keys: price_eur, airline_codes, stops,
    duration_min, segments.
    """
    payload = _extract_json_data(js_text)
    if not isinstance(payload, list):
        return []

    # Find the outbound flights list — try outer indices 2, 3, 4 in order.
    flight_entries: list = []
    for outer_idx in range(2, min(6, len(payload))):
        try:
            outer = payload[outer_idx]
            if not isinstance(outer, list) or not outer:
                continue
            # The outbound block is [[entry, entry, ...], null, 0, 0, [1]]
            # so outer[0] is the list of flight entries.
            candidate = outer[0]
            if not isinstance(candidate, list) or not candidate:
                continue
            first = candidate[0]
            if not isinstance(first, list) or len(first) < 2:
                continue
            # Validate: first[0] must be flight data (list), first[1] must be
            # price data [[null, int], token_str].
            if not isinstance(first[0], list) or not isinstance(first[1], list):
                continue
            price_block = first[1]
            if (
                len(price_block) >= 1
                and isinstance(price_block[0], list)
                and len(price_block[0]) >= 2
                and isinstance(price_block[0][1], (int, float))
            ):
                flight_entries = candidate
                log.debug("  Found flight list at payload[%d][0] (%d entries)", outer_idx, len(candidate))
                break
        except (IndexError, TypeError):
            continue

    results = []
    for entry in flight_entries:
        try:
            flight_data = entry[0]   # itinerary array
            price_block = entry[1]   # [[null, price], token]
            price_eur = float(price_block[0][1])

            airline_code  = flight_data[0]  # "QR"
            airline_names = flight_data[1] if isinstance(flight_data[1], list) else []
            segments      = flight_data[2] if isinstance(flight_data[2], list) else []
            duration_min  = flight_data[9] if len(flight_data) > 9 else None
            stops         = max(0, len(segments) - 1)

            codes = [airline_code] if isinstance(airline_code, str) and airline_code else []

            results.append({
                "price_eur":     price_eur,
                "airline_codes": codes,
                "stops":         stops,
                "duration_min":  duration_min,
                "segments":      segments,
            })
        except (IndexError, TypeError, ValueError, AttributeError):
            continue

    return results


def _is_ds1_payload(text: str) -> bool:
    """Check whether a text blob contains a Google Flights ds:1 data payload."""
    if not text or "AF_initDataCallback" not in text or "data:" not in text:
        return False
    return any(m in text for m in ("key: 'ds:1'", r"key: \'ds:1\'", 'key: "ds:1"'))


async def _dismiss_consent(page) -> None:
    """Dismiss Google's cookie consent dialog (tries EN + NL button labels)."""
    for label in ["Reject all", "Alles weigeren"]:
        try:
            btn = page.get_by_role("button", name=label, exact=True)
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await page.wait_for_timeout(1000)
                return
        except Exception:
            continue


async def _get_ds1_text(page, url: str, timeout_ms: int) -> Optional[str]:
    """
    Navigate to a Google Flights URL and return the page text containing the
    ds:1 AF_initDataCallback payload.

    The flight data is embedded in the main HTML response.  We intercept the
    primary page response to get the full HTML (before JavaScript runs) and
    then search it for the ds:1 callback.  This is more reliable than reading
    DOM script elements, which may reflect post-JS state.
    """
    captured: list[str] = []

    async def on_response(resp):
        if captured:
            return
        try:
            if resp.url != url and not resp.url.startswith(url.split("?")[0]):
                return
            ct = resp.headers.get("content-type", "")
            if "html" not in ct:
                return
            body = await resp.text()
            if _is_ds1_payload(body):
                captured.append(body)
        except Exception:
            pass

    page.on("response", on_response)
    try:
        await page.goto(url, wait_until="load", timeout=timeout_ms)
        await _dismiss_consent(page)
        # Give Google a moment after consent to fully render the page.
        await page.wait_for_timeout(2000)
    finally:
        page.remove_listener("response", on_response)

    if captured:
        return captured[0]

    # Fallback: the page may redirect (consent domain).  Try the final URL.
    final_url = page.url
    if final_url != url:
        captured2: list[str] = []
        async def on_response2(resp):
            if captured2:
                return
            try:
                if resp.url != final_url and not resp.url.startswith(final_url.split("?")[0]):
                    return
                ct = resp.headers.get("content-type", "")
                if "html" not in ct:
                    return
                body = await resp.text()
                if _is_ds1_payload(body):
                    captured2.append(body)
            except Exception:
                pass
        page.on("response", on_response2)
        try:
            await page.goto(final_url, wait_until="load", timeout=timeout_ms)
            await page.wait_for_timeout(2000)
        finally:
            page.remove_listener("response", on_response2)
        if captured2:
            return captured2[0]

    # Last resort: get the current page HTML via JavaScript.
    try:
        html = await page.content()
        if _is_ds1_payload(html):
            return html
    except Exception:
        pass

    return None


async def _fetch_all(search: dict, timeout_sec: int) -> list[FlightResult]:
    cabin_key = _CABIN_MAP.get(search["cabin"], "economy")
    n_dates   = search.get("sample_departure_dates", 6)
    max_res   = search.get("max_results_per_date", 3)
    mid_days  = (search["trip_duration_days"]["min"] + search["trip_duration_days"]["max"]) // 2
    max_stops = search.get("max_stops", None)

    dep_dates = _sample_dates(
        search["outbound_window"]["from"],
        search["outbound_window"]["to"],
        n_dates,
    )
    in_from = date.fromisoformat(search["inbound_window"]["from"]) if "inbound_window" in search else None
    in_to   = date.fromisoformat(search["inbound_window"]["to"])   if "inbound_window" in search else None

    results: list[FlightResult] = []
    timeout_ms = timeout_sec * 1000

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = await ctx.new_page()

        for origin in search["origins"]:
            for dest in search["destinations"]:
                for dep in dep_dates:
                    ret = dep + timedelta(days=mid_days)
                    if in_from and in_to and not (in_from <= ret <= in_to):
                        continue

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
                    url = query.url()

                    try:
                        js_text = await _get_ds1_text(page, url, timeout_ms)
                    except Exception as e:
                        log.warning("  PW %s->%s %s: load error: %s", origin, dest, dep, e)
                        continue

                    if not js_text:
                        log.warning("  PW %s->%s %s: no data script found", origin, dest, dep)
                        continue

                    flights = _parse_flights(js_text)
                    if not flights:
                        log.warning("  PW %s->%s %s: parser returned 0 results", origin, dest, dep)
                        continue

                    count = 0
                    for gf in flights:
                        if count >= max_res:
                            break

                        results.append(FlightResult(
                            source="google",
                            search_name=search["name"],
                            origin=origin,
                            destination=dest,
                            departure_date=dep.isoformat(),
                            return_date=ret.isoformat(),
                            cabin=search["cabin"],
                            total_price_eur=gf["price_eur"],
                            airline_codes=gf["airline_codes"] or ["?"],
                            stops=gf["stops"],
                            duration_outbound=_duration_str(gf["duration_min"]),
                            duration_return=None,
                            booking_url=url,
                            raw={},
                        ))
                        count += 1

                    log.info("  PW %s->%s %s: %d offers", origin, dest, dep, count)

        await browser.close()

    return results


def fetch(search: dict, timeout_sec: int = 60) -> list[FlightResult]:
    """Fetch from Google Flights using Playwright. Returns [] if unavailable."""
    if not _FF_AVAILABLE or not _PW_AVAILABLE:
        return []
    return asyncio.run(_fetch_all(search, timeout_sec))
