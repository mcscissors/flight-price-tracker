# Phase 2: Smart Alerts & Result Filtering

## Smart Alerts (`smart_alerts.py`)

Prevent alert fatigue with three strategies:

### 1. **Percentage-based alerts**
Alert when price is X% below recent average (default 15%).
- Requires at least 3 price samples to establish baseline
- Enable via `"smart_alerts": true` in search config
- More intelligent than fixed thresholds; adapts to market conditions

### 2. **Repeat alert suppression**
Don't alert twice for the same route within 24 hours.
- Automatic, always active
- Stored in `data/alert_history.json`
- Route key: `origin→destination|departure_date|cabin`

### 3. **Alert history tracking**
- Records when alerts were triggered
- Counts repeated alerts for trending analysis
- Useful for metrics and debugging

### Usage

Basic threshold (old behavior, still works):
```json
{
  "name": "Example Search",
  "alert_below_eur": 2250,
  "smart_alerts": false
}
```

Percentage-based (new behavior):
```json
{
  "name": "Example Search",
  "alert_below_eur": 2250,
  "smart_alerts": true
}
```

## Result Filtering (`result_filters.py`)

Remove low-quality results before emailing:

### Filters Available

1. **Max stops** (default: 2)
   - Removes flights with >N connections
   - 0 = nonstop only, 1 = 1-stop max, etc.

2. **Max flight duration** (default: 18 hours)
   - Removes long flights
   - Checks both outbound and return legs
   - Parses "15h 30m" format

3. **Minimum FB score** (default: -1)
   - Removes non-Flying Blue partners
   - -1 = allow unknown, 0+ = require partner

### Integration

Add to `consolidate.py` (already integrated):
```python
from . import result_filters

filtered = result_filters.filter_results(
    results,
    max_stops=2,
    max_flight_hours=18,
    min_fb_score=-1,
)
```

Or use in pipeline (to be integrated in Phase 2b):
```python
results = result_filters.filter_excessive_stops(results, max_stops=1)
results = result_filters.filter_excessive_duration(results, max_flight_hours=16)
```

## Configuration Examples

### Strict filters (short, cheap trips only)
```json
{
  "name": "Short-haul only",
  "smart_alerts": true,
  "max_stops": 0,
  "max_flight_hours": 12,
  "alert_below_eur": 500
}
```

### Relaxed filters (any business class deal)
```json
{
  "name": "Any business",
  "smart_alerts": true,
  "max_stops": 2,
  "max_flight_hours": 20,
  "alert_below_eur": 2250
}
```

## Future Enhancements (Phase 2b)

- [ ] Integrate result_filters into consolidate.py for filtering before email
- [ ] Add filters to searches.json config (max_stops, max_flight_hours)
- [ ] Time-of-day filters (no late arrivals)
- [ ] Preferred departure time windows
- [ ] Airport blacklist (avoid certain hubs)
- [ ] Layover duration filters (too short/too long)

## Data Files

- `data/alert_history.json` - Alert history for repeat suppression
  - Auto-created on first alert
  - Format: `{"route_key": {"last_alert": ISO8601, "times_alerted": N}}`

## Testing

```bash
# Test smart alerts
python -c "from scripts import smart_alerts; print(smart_alerts.should_alert_percentage(2000, [2300, 2400, 2350]))"

# Test result filters
python -c "from scripts import result_filters; print(result_filters._parse_duration_minutes('15h 30m'))"
```
