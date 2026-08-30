from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_FB_CACHE: dict | None = None

def _fb_lookup() -> dict[str, dict]:
    global _FB_CACHE
    if _FB_CACHE is None:
        p = Path(__file__).resolve().parent.parent / "config" / "flying_blue_partners.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        _FB_CACHE = {a["iata"]: a for a in data["partners"]}
    return _FB_CACHE


@dataclass
class FlightResult:
    source: str                    # "amadeus" or "google"
    search_name: str
    origin: str
    destination: str
    departure_date: str            # YYYY-MM-DD
    return_date: Optional[str]     # YYYY-MM-DD or None for one-way
    cabin: str
    total_price_eur: float
    airline_codes: list[str]
    stops: int
    duration_outbound: str         # human-readable, e.g. "10h 35m"
    duration_return: Optional[str]
    booking_url: Optional[str]
    alert: bool = False            # set by consolidate.py when below threshold
    raw: dict = field(default_factory=dict, repr=False)

    def fb_partner(self) -> Optional[dict]:
        """Return Flying Blue partner data for the primary airline, or None."""
        db = _fb_lookup()
        for code in self.airline_codes:
            if code in db:
                return db[code]
        return None

    def fb_miles_score(self) -> int:
        """Higher = better miles-earning. Used for tie-breaking in sort."""
        p = self.fb_partner()
        if p is None:
            return -1
        return p.get("max_miles_pct", 0)

    def fb_rating(self) -> str:
        p = self.fb_partner()
        if p is None:
            return "–"
        return p.get("rating", "–")

    def fb_xp(self) -> bool:
        p = self.fb_partner()
        return bool(p and p.get("xp"))

    def trip_days(self) -> Optional[int]:
        if not self.return_date:
            return None
        from datetime import date
        d = date.fromisoformat(self.return_date) - date.fromisoformat(self.departure_date)
        return d.days

    def airlines_display(self) -> str:
        return " / ".join(self.airline_codes)

    def stops_display(self) -> str:
        if self.stops == 0:
            return "nonstop"
        return f"{self.stops} stop{'s' if self.stops > 1 else ''}"
