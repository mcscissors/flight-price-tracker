# Flight Price Tracker

Monitors flight prices across configurable routes/dates, merges results from
Amadeus (official API) and Google Flights (fast-flights, unofficial), and
emails a digest to schaar000@gmail.com.

## Run

```bash
# Install deps (once)
pip install -r requirements.txt

# Dry run — builds email preview, doesn't send
python -m scripts.run_all --dry-run

# Full run
python -m scripts.run_all

# Skip one source
python -m scripts.run_all --no-google
python -m scripts.run_all --no-amadeus
```

## Setup (first time)

1. Copy `.env.example` → `.env` and fill in credentials:
   - **Amadeus**: register free at https://developers.amadeus.com → My Apps → Create app
     Set `environment` in `config/settings.json` to `"test"` (simulated prices) or `"production"` (real, needs production access approval)
   - **Gmail App Password**: myaccount.google.com/apppasswords (needs 2-Step Verification)

2. Edit `config/searches.json` to define your routes, dates, and alert thresholds.

3. Register the Windows Scheduled Task (runs Mon & Thu 08:00 by default):
   ```powershell
   .\setup_task.ps1
   ```

## Structure

- `config/searches.json` — routes, windows, cabin, alert thresholds (edit this)
- `config/settings.json` — email settings, Amadeus environment, run options
- `scripts/fetch_amadeus.py` — Amadeus Flight Offers Search
- `scripts/fetch_google.py` — Google Flights via fast-flights (unofficial)
- `scripts/consolidate.py` — merge, deduplicate, rank, flag alerts
- `scripts/prepare_email.py` — HTML email builder
- `scripts/send_email.py` — Gmail SMTP sender
- `scripts/run_all.py` — main orchestrator
- `data/results/` — JSON cache of each run's results (gitignored)
- `data/logs/` — per-run log files (gitignored)

## Gotchas

- **Amadeus test environment uses simulated prices** — they look real but are
  not. Switch `environment` to `"production"` for live data (requires applying
  for production access on the Amadeus developer portal; free tier = 2,000 calls/month).
- **Google Flights (fast-flights) is unofficial** — it reverse-engineers Google's
  internal protobuf API and can break when Google updates their backend.
  Amadeus is the authoritative source; Google is supplementary.
- **Prices are per person, 1 adult, round-trip in EUR.** Always verify on the
  airline's site before booking — ancillary fees, baggage, and seat selection
  are not included.
- **`sample_departure_dates`** controls how many departure dates within the
  outbound window are sampled. Higher = more API calls but wider coverage.
  Amadeus free tier: 2,000 calls/month, so be conservative.
