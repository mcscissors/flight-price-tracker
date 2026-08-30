"""
Build the HTML email body from consolidated flight results.
"""
from __future__ import annotations
from datetime import datetime
from .models import FlightResult


_CSS = """
  body { font-family: -apple-system, Arial, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }
  .wrapper { max-width: 700px; margin: 0 auto; }
  .header { background: #1a237e; color: #fff; padding: 20px 24px; border-radius: 8px 8px 0 0; }
  .header h1 { margin: 0; font-size: 22px; }
  .header .sub { font-size: 13px; opacity: .75; margin-top: 4px; }
  .section { background: #fff; padding: 20px 24px; margin-top: 2px; }
  .section h2 { margin: 0 0 14px; font-size: 16px; color: #1a237e; border-bottom: 2px solid #e8eaf6; padding-bottom: 8px; }
  .no-results { color: #888; font-style: italic; font-size: 14px; }
  .card { border: 1px solid #e0e0e0; border-radius: 6px; padding: 14px 16px; margin-bottom: 10px; position: relative; }
  .card.alert { border-color: #2e7d32; background: #f1f8e9; }
  .alert-badge { display: inline-block; background: #2e7d32; color: #fff; font-size: 11px;
                 font-weight: bold; padding: 2px 8px; border-radius: 12px; margin-bottom: 8px; }
  .route { font-size: 18px; font-weight: bold; color: #212121; }
  .dates { font-size: 13px; color: #555; margin: 4px 0; }
  .details { font-size: 13px; color: #444; margin: 6px 0 10px; }
  .price { font-size: 22px; font-weight: bold; color: #1a237e; }
  .price.alert { color: #2e7d32; }
  .source { font-size: 11px; color: #999; float: right; margin-top: 4px; }
  .book-link { display: inline-block; margin-top: 8px; padding: 6px 14px; background: #1a237e;
               color: #fff; text-decoration: none; border-radius: 4px; font-size: 13px; }
  .fb-badge { display: inline-block; font-size: 11px; padding: 2px 7px; border-radius: 10px;
              background: #e8f5e9; color: #1b5e20; border: 1px solid #a5d6a7; margin-left: 8px; vertical-align: middle; }
  .fb-badge.no-xp { background: #fff8e1; color: #e65100; border-color: #ffcc80; }
  .fb-badge.unknown { background: #f5f5f5; color: #888; border-color: #e0e0e0; }
  .footer { background: #fff; padding: 14px 24px; border-radius: 0 0 8px 8px; font-size: 12px;
            color: #888; border-top: 1px solid #eee; margin-top: 2px; }
  .summary-bar { background: #e8eaf6; padding: 12px 24px; font-size: 13px; margin-top: 2px; }
"""


def _fb_badge(r: FlightResult) -> str:
    score = r.fb_miles_score()
    rating = r.fb_rating()
    xp = r.fb_xp()
    if score <= 0 and rating in ("–", "afwijkend"):
        return f'<span class="fb-badge unknown">FB: {rating}</span>'
    xp_tag = " + XP" if xp else " no XP"
    css = "fb-badge" if xp else "fb-badge no-xp"
    return f'<span class="{css}">FB {rating} {score}%{xp_tag}</span>'


def _card(r: FlightResult) -> str:
    cabin_label = r.cabin.replace("_", " ").title()
    trip_days = r.trip_days()
    days_str = f"  ·  {trip_days} nights" if trip_days else ""
    alert_badge = '<span class="alert-badge">🔔 BELOW THRESHOLD</span><br>' if r.alert else ""
    price_cls = "price alert" if r.alert else "price"
    book_btn = f'<a class="book-link" href="{r.booking_url}">Book</a>' if r.booking_url else ""
    return f"""
    <div class="card{'  alert' if r.alert else ''}">
      {alert_badge}
      <span class="route">{r.origin} → {r.destination}</span>
      <span class="source">{r.source}</span>
      <div class="dates">✈ {r.departure_date} → {r.return_date or '?'}{days_str}</div>
      <div class="details">
        {r.airlines_display()} &nbsp;·&nbsp; {cabin_label} &nbsp;·&nbsp; {r.stops_display()}
        &nbsp;·&nbsp; outbound {r.duration_outbound}
        {('&nbsp;·&nbsp; return ' + r.duration_return) if r.duration_return else ''}
        {_fb_badge(r)}
      </div>
      <span class="{price_cls}">€ {r.total_price_eur:,.0f}</span>
      {book_btn}
    </div>"""


def build(
    consolidated: dict[str, list[FlightResult]],
    searches: list[dict],
) -> tuple[str, str]:
    """
    Returns (subject, html_body).
    consolidated: {search_name: [FlightResult, ...]}
    """
    now = datetime.now().strftime("%d %b %Y, %H:%M")
    total_alerts = sum(1 for results in consolidated.values() for r in results if r.alert)
    total_results = sum(len(v) for v in consolidated.values())

    if len(searches) == 1:
        # Single search: use the destination region as the subject
        region = searches[0]["name"].split("→")[-1].strip() if "→" in searches[0]["name"] else searches[0]["name"]
        threshold = searches[0].get("alert_below_eur")
        subject_parts = [f"✈ {region}"]
        if total_alerts:
            subject_parts.append(f"{total_alerts} deal{'s' if total_alerts > 1 else ''} below €{threshold:,}")
        elif total_results:
            subject_parts.append(f"{total_results} result{'s' if total_results != 1 else ''}")
        else:
            subject_parts.append("no results")
        subject_parts.append(now[:11])
    else:
        subject_parts = ["✈ Flight Tracker"]
        if total_alerts:
            subject_parts.append(f"{total_alerts} deal{'s' if total_alerts > 1 else ''} below threshold")
        subject_parts.append(now[:11])
    subject = " — ".join(subject_parts)

    sections_html = []
    search_cfg = {s["name"]: s for s in searches}

    for name, results in consolidated.items():
        cfg = search_cfg.get(name, {})
        threshold = cfg.get("alert_below_eur")
        threshold_str = f"  (alert: €{threshold:,})" if threshold else ""
        cards = "".join(_card(r) for r in results) if results else '<p class="no-results">No results found for this search.</p>'
        sections_html.append(f"""
      <div class="section">
        <h2>{name}{threshold_str}</h2>
        {cards}
      </div>""")

    alerts_line = (
        f"🔔 <strong>{total_alerts} result{'s' if total_alerts > 1 else ''} below threshold</strong> &nbsp;·&nbsp; "
        if total_alerts else ""
    )
    summary = f"""
    <div class="summary-bar">
      {alerts_line}{total_results} total result{'s' if total_results != 1 else ''} across {len(consolidated)} search{'es' if len(consolidated) != 1 else ''} &nbsp;·&nbsp; Run: {now}
    </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>{_CSS}</style></head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>✈ Flight Price Tracker</h1>
    <div class="sub">{now}</div>
  </div>
  {summary}
  {''.join(sections_html)}
  <div class="footer">
    Prices are per person (1 adult), round-trip, in EUR. Amadeus test-environment prices are simulated.
    Always verify final price on the airline's site before booking.
  </div>
</div>
</body>
</html>"""

    return subject, html
