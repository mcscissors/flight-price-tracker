# Phase 2c: True One-Way Flights

## Overview

Add native one-way flight search support instead of the workaround (trip_duration_days: 1-1).

## Configuration

### One-way search config:
```json
{
  "name": "AMS → HAV One-Way",
  "enabled": true,
  "origins": ["AMS"],
  "destinations": ["HAV"],
  "cabin": "ECONOMY",
  "outbound_window_config": {
    "days_from_today": 58,
    "days_duration": 61
  },
  "is_oneway": true,
  "preferred_airlines": [],
  "max_stops": 2,
  "alert_below_eur": 525,
  "max_results_per_date": 5,
  "sample_departure_dates": 10
}
```

Key difference: `"is_oneway": true` instead of `trip_duration_days` and `inbound_window_config`.

### Round-trip search config (existing):
```json
{
  "name": "AMS → BKK Round-Trip",
  "outbound_window_config": {...},
  "inbound_window_config": {...},
  "trip_duration_days": {"min": 12, "max": 22},
  "is_oneway": false
}
```

## Implementation

### Changes in fetch_playwright.py:
- Detect `is_oneway` flag in search config
- Skip return query generation for one-way searches
- Handle single-leg results correctly

### Changes in consolidate.py:
- Deduplication key handles `return_date: None` for one-way
- Filtering & alerts work for one-way flights

### Changes in models.py:
- Already supports `return_date: Optional[str]`
- trip_days() already returns None for one-way

## Data Flow

**Round-trip (existing):**
```
Query: (AMS, BKK, 2026-12-10) + (BKK, AMS, 2026-12-20)
Result: FlightResult(departure_date="2026-12-10", return_date="2026-12-20", ...)
```

**One-way (new):**
```
Query: (AMS, HAV, 2026-12-01)
Result: FlightResult(departure_date="2026-12-01", return_date=None, ...)
```

## Email Rendering

prepare_email_v2.py already handles one-way:
- `trip_days()` returns None for one-way
- Price display shows single leg
- "Return" leg omitted from display

## Search Examples

### Cuba economy one-way (new style):
```json
{
  "name": "AMS/DUS/BRU → Cuba Economy (One-Way)",
  "enabled": true,
  "is_oneway": true,
  "outbound_window_config": {"days_from_today": 58, "days_duration": 61},
  "alert_below_eur": 525
}
```

### Asia one-way:
```json
{
  "name": "BKK → AMS One-Way (Return)",
  "enabled": false,
  "is_oneway": true,
  "origins": ["BKK"],
  "destinations": ["AMS"],
  "outbound_window_config": {"days_from_today": 150, "days_duration": 90}
}
```

## Testing

```bash
# Test one-way price recording
python -c "
from scripts import price_history
price_history.record_price('AMS', 'HAV', 'ECONOMY', 525)
stats = price_history.get_price_stats('AMS', 'HAV', 'ECONOMY')
print(stats)
"
```

## Next: Phase 3

- Price history analysis (already implemented)
- Trend-based alerts
- Price predictions
- Fallback sources (Kayak, Skyscanner)
