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
from dataclasses import dataclass
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
    # Prefer reject. Once a reject button is found, we commit to it — even if
    # the click itself fails (e.g. the button detaches mid-transition), we do
    # NOT fall through to the accept labels below. Falling through there would
    # silently turn a failed rejection into an accepted one.
    for label in ["Reject all", "Alles weigeren", "Alles afwijzen"]:
        btn = page.get_by_role("button", name=label, exact=True)
        try:
            visible = await btn.is_visible(timeout=2000)
        except Exception:
            continue
        if not visible:
            continue
        try:
            await btn.click()
            await page.wait_for_timeout(1000)
        except Exception as e:
            log.warning("  Reject button '%s' was visible but click failed: %s", label, e)
        return

    # No reject button found at all — fall back to accept so the session is
    # not permanently blocked.
    for label in ["Accept all", "Alles accepteren", "Agree", "Akkoord"]:
        try:
            btn = page.get_by_role("button", name=label, exact=True)
            if await btn.is_visible(timeout=2000):
                log.debug("  No reject button found — clicking '%s' to unblock session", label)
                await btn.click()
                await page.wait_for_timeout(1000)
                return
        except Exception:
            continue


async def _capture_ds1_response(page, url: str, timeout_ms: int) -> Optional[str]:
    """
    Navigate to `url` and capture the HTML response body containing the ds:1
    AF_initDataCallback payload, dismissing the consent dialog if it appears.

    Shared by the primary navigation and the post-redirect retry in
    _get_ds1_text so both paths dismiss consent identically and can't drift
    apart.
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

    return captured[0] if captured else None


async def _get_ds1_text(page, url: str, timeout_ms: int) -> Optional[str]:
    """
    Navigate to a Google Flights URL and return the page text containing the
    ds:1 AF_initDataCallback payload.

    The flight data is embedded in the main HTML response.  We intercept the
    primary page response to get the full HTML (before JavaScript runs) and
    then search it for the ds:1 callback.  This is more reliable than reading
    DOM script elements, which may reflect post-JS state.
    """
    text = await _capture_ds1_response(page, url, timeout_ms)
    if text:
        return text

    # Fallback: the page may have redirected (e.g. to the consent domain).
    # Retry against the final URL through the same capture path, so consent
    # gets dismissed there too instead of leaving the page stuck on it.
    final_url = page.url
    if final_url != url:
        text = await _capture_ds1_response(page, final_url, timeout_ms)
        if text:
            return text

    # Last resort: get the current page HTML via JavaScript.
    try:
        html = await page.content()
        if _is_ds1_payload(html):
            return html
    except Exception:
        pass

    return None


@dataclass(frozen=True)
class _FetchParams:
    """Bundles the values _fetch_all derives from `search`, shared by every
    (origin, destination, date) combination fetched for that search."""
    dep_dates: list
    in_from: Optional[date]
    in_to: Optional[date]
    cabin_key: str
    mid_days: int
    max_res: int
    max_stops: Optional[int]
    timeout_ms: int


def _build_fetch_params(search: dict, timeout_sec: int) -> _FetchParams:
    n_dates = search.get("sample_departure_dates", 6)
    inbound = search.get("inbound_window")
    return _FetchParams(
        dep_dates=_sample_dates(
            search["outbound_window"]["from"],
            search["outbound_window"]["to"],
            n_dates,
        ),
        in_from=date.fromisoformat(inbound["from"]) if inbound else None,
        in_to=date.fromisoformat(inbound["to"]) if inbound else None,
        cabin_key=_CABIN_MAP.get(search["cabin"], "economy"),
        mid_days=(search["trip_duration_days"]["min"] + search["trip_duration_days"]["max"]) // 2,
        max_res=search.get("max_results_per_date", 3),
        max_stops=search.get("max_stops", None),
        timeout_ms=timeout_sec * 1000,
    )


async def _fetch_destination_date(
    page, search: dict, origin: str, dest: str, dep: date, ret: date,
    params: _FetchParams,
) -> list[FlightResult]:
    """
    Fetch one (destination, departure date) pair. Never lets an exception
    escape — logs and returns [] on any failure, so one bad pair (a config
    error, a parser mismatch, a malformed result) can't take down the whole
    origin or leak the browser it belongs to.
    """
    try:
        query = create_filter(
            flights=[
                FlightQuery(date=dep.isoformat(), from_airport=origin, to_airport=dest),
                FlightQuery(date=ret.isoformat(), from_airport=dest,   to_airport=origin),
            ],
            trip="round-trip",
            seat=params.cabin_key,
            passengers=Passengers(adults=1),
            currency="EUR",
            max_stops=params.max_stops,
        )
        url = query.url()
    except Exception as e:
        log.warning("  PW %s->%s %s: filter/URL build error: %s", origin, dest, dep, e)
        return []

    try:
        js_text = await _get_ds1_text(page, url, params.timeout_ms)
    except Exception as e:
        log.warning("  PW %s->%s %s: load error: %s", origin, dest, dep, e)
        js_text = None
    finally:
        # Always reset page state so a stale redirect (e.g. consent.google.com
        # queued mid-navigation) cannot interrupt the next goto() — this
        # matters whether or not this attempt succeeded, not just on error.
        try:
            await page.goto("about:blank", wait_until="load", timeout=5000)
        except Exception:
            pass

    if not js_text:
        log.warning("  PW %s->%s %s: no data script found", origin, dest, dep)
        return []

    flights = _parse_flights(js_text)
    if not flights:
        log.warning("  PW %s->%s %s: parser returned 0 results", origin, dest, dep)
        return []

    try:
        offers = [
            FlightResult(
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
            )
            for gf in flights[:params.max_res]
        ]
    except Exception as e:
        log.warning("  PW %s->%s %s: result build error: %s", origin, dest, dep, e)
        return []

    log.info("  PW %s->%s %s: %d offers", origin, dest, dep, len(offers))
    return offers


async def _fetch_origin(pw, search: dict, origin: str, params: _FetchParams) -> list[FlightResult]:
    """
    Fetch all destinations/dates for one origin. Uses its own browser
    instance, guaranteed closed (via try/finally) whether this returns
    normally, raises, or is cancelled by a sibling task's failure.
    """
    browser = await pw.chromium.launch(headless=True)
    try:
        ctx = await browser.new_context(
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        try:
            page = await ctx.new_page()
            results: list[FlightResult] = []

            for dest in search["destinations"]:
                for dep in params.dep_dates:
                    ret = dep + timedelta(days=params.mid_days)
                    if params.in_from and params.in_to and not (params.in_from <= ret <= params.in_to):
                        continue
                    results.extend(
                        await _fetch_destination_date(page, search, origin, dest, dep, ret, params)
                    )

            return results
        finally:
            await ctx.close()
    finally:
        await browser.close()


async def _fetch_all(search: dict, timeout_sec: int) -> list[FlightResult]:
    params = _build_fetch_params(search, timeout_sec)

    # Max 2 origins in parallel — keeps Google from rate-limiting the IP.
    sem = asyncio.Semaphore(2)

    async with async_playwright() as pw:
        # Defined inside the `async with` block (not before it) so `pw` is a
        # real bound name at both definition and call time — no forward
        # reference to rely on gather() happening to run inside this block.
        async def bounded(origin: str) -> list[FlightResult]:
            async with sem:
                return await _fetch_origin(pw, search, origin, params)

        # return_exceptions=True: one origin failing outright (e.g. browser
        # launch error) must not cancel the other origins' in-flight fetches
        # and discard their already-gathered results.
        batches = await asyncio.gather(
            *[bounded(o) for o in search["origins"]],
            return_exceptions=True,
        )

    results: list[FlightResult] = []
    for origin, batch in zip(search["origins"], batches):
        if isinstance(batch, BaseException):
            log.warning("  PW origin %s failed entirely: %s", origin, batch)
            continue
        results.extend(batch)
    return results


def fetch(search: dict, timeout_sec: int = 60) -> list[FlightResult]:
    """Fetch from Google Flights using Playwright. Returns [] if unavailable."""
    if not _FF_AVAILABLE or not _PW_AVAILABLE:
        return []
    return asyncio.run(_fetch_all(search, timeout_sec))
