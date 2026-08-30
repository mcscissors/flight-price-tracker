"""
Fetch flight prices from Google Flights via Playwright (headless Chromium).

Reuses fast-flights URL generation (Query.url()) and its parser (parse_js),
but loads the page in a real browser so Google bot-detection doesn't block it.

Install once:
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations
import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from .models import FlightResult

log = logging.getLogger(__name__)

try:
    from fast_flights import FlightQuery, Passengers, create_filter
    from fast_flights.parser import parse_js
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


def _duration_str(dur) -> str:
    if dur is None:
        return "?"
    if isinstance(dur, int):
        return f"{dur // 60}h {dur % 60}m"
    return str(dur)


def _parse_price(price_val) -> Optional[float]:
    if price_val is None:
        return None
    try:
        return float(str(price_val).replace(",", "").replace("€", "").strip())
    except (ValueError, TypeError):
        return None


async def _dismiss_consent(page) -> None:
    """Click 'Reject all' on Google's cookie consent dialog if it appears."""
    try:
        btn = page.get_by_role("button", name="Reject all")
        if await btn.is_visible(timeout=4000):
            await btn.click()
            await page.wait_for_timeout(500)
    except Exception:
        pass


async def _get_script_text(page, url: str, timeout_ms: int) -> Optional[str]:
    """Navigate to a Google Flights URL and return the ds:1 script content."""
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    await _dismiss_consent(page)
    try:
        el = await page.wait_for_selector("script.ds\\:1", timeout=timeout_ms)
        return await el.inner_text() if el else None
    except Exception:
        return None


async def _fetch_all(search: dict, timeout_sec: int) -> list[FlightResult]:
    cabin_key  = _CABIN_MAP.get(search["cabin"], "economy")
    n_dates    = search.get("sample_departure_dates", 6)
    max_res    = search.get("max_results_per_date", 3)
    mid_days   = (search["trip_duration_days"]["min"] + search["trip_duration_days"]["max"]) // 2
    max_stops  = search.get("max_stops", None)

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
                        js_text = await _get_script_text(page, url, timeout_ms)
                    except Exception as e:
                        log.warning("  PW %s->%s %s: load error: %s", origin, dest, dep, e)
                        continue

                    if not js_text:
                        log.warning("  PW %s->%s %s: no data script found", origin, dest, dep)
                        continue

                    try:
                        result_list = parse_js(js_text)
                    except Exception as e:
                        log.warning("  PW %s->%s %s: parse error: %s", origin, dest, dep, e)
                        continue

                    count = 0
                    for gf in result_list:
                        if count >= max_res:
                            break
                        price = _parse_price(getattr(gf, "price", None))
                        if price is None:
                            continue

                        airlines = getattr(gf, "airlines", []) or []
                        codes    = [getattr(a, "code", str(a)) for a in airlines]
                        flights  = getattr(gf, "flights", []) or []
                        stops    = max(0, len(flights) - 1) if flights else 0
                        dur_out  = _duration_str(getattr(flights[0], "duration", None)) if flights else "?"

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
