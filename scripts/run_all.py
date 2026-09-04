"""
Main orchestrator. Run with:
  python -m scripts.run_all
  python -m scripts.run_all --dry-run   (build email but don't send)
  python -m scripts.run_all --no-google (skip Google Flights source)
  python -m scripts.run_all --no-amadeus
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .models import FlightResult
from . import fetch_amadeus, fetch_playwright, consolidate as consolidate_mod, prepare_email, send_email

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

_log_fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
_con = logging.StreamHandler(sys.stdout)
_con.stream.reconfigure(encoding="utf-8", errors="replace")
_con.setFormatter(_log_fmt)
_file = logging.FileHandler(
    BASE / "data" / "logs" / f"run_{datetime.now():%Y%m%d_%H%M%S}.log",
    encoding="utf-8",
)
_file.setFormatter(_log_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_con, _file])
log = logging.getLogger(__name__)


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_results(results: dict[str, list[FlightResult]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"results_{stamp}.json"
    data = {
        name: [
            {k: v for k, v in vars(r).items() if k != "raw"}
            for r in rs
        ]
        for name, rs in results.items()
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    log.info(f"Results cached → {path}")


def _build_amadeus_client(settings: dict):
    try:
        from amadeus import Client
        env = settings["amadeus"].get("environment", "test")
        return Client(
            client_id=os.environ["AMADEUS_API_KEY"],
            client_secret=os.environ["AMADEUS_API_SECRET"],
            hostname=env,
        )
    except KeyError as e:
        log.warning(f"Amadeus env var missing ({e}) — Amadeus source disabled")
        return None
    except ImportError:
        log.warning("amadeus package not installed — run: pip install amadeus")
        return None


def main(args=None) -> None:
    p = argparse.ArgumentParser(description="Flight price tracker")
    p.add_argument("--dry-run",     action="store_true", help="Build email but don't send it")
    p.add_argument("--no-google",   action="store_true", help="Skip Google Flights (Playwright) source")
    p.add_argument("--with-amadeus",action="store_true", help="Enable Amadeus (enterprise API only)")
    opts = p.parse_args(args)

    searches_cfg = _load_json(BASE / "config" / "searches.json")
    settings     = _load_json(BASE / "config" / "settings.json")
    searches     = [s for s in searches_cfg["searches"] if s.get("enabled", True)]

    if not searches:
        log.info("No enabled searches — nothing to do.")
        return

    run_cfg = settings.get("run", {})
    per_search_email = run_cfg.get("per_search_email", True)
    timeout_sec = run_cfg.get("request_timeout_sec", 60)
    only_alerts = run_cfg.get("send_email_only_if_alerts", False)
    cache = run_cfg.get("cache_results", True)
    results_dir = BASE / run_cfg.get("results_dir", "data/results")

    amadeus_client = _build_amadeus_client(settings) if opts.with_amadeus else None
    all_consolidated: dict[str, list[FlightResult]] = {}

    for search in searches:
        name = search["name"]
        log.info(f"=== {name} ===")

        raw_this: list[FlightResult] = []

        if not opts.no_google:
            g_results = fetch_playwright.fetch(search, timeout_sec=timeout_sec)
            log.info(f"  Google:  {len(g_results)} raw results")
            raw_this.extend(g_results)

        if amadeus_client:
            a_results = fetch_amadeus.fetch(search, amadeus_client)
            log.info(f"  Amadeus: {len(a_results)} raw results")
            raw_this.extend(a_results)

        consolidated = consolidate_mod.consolidate_all({name: raw_this}, [search])
        all_consolidated.update(consolidated)

        n_results = len(consolidated.get(name, []))
        n_alerts = sum(1 for r in consolidated.get(name, []) if r.alert)
        log.info(f"  {n_results} results, {n_alerts} alert(s)")

        if per_search_email:
            if only_alerts and n_alerts == 0:
                log.info("  No alerts — email skipped")
                continue

            if n_results == 0:
                log.info("  No results after filtering — email skipped")
                continue

            subject, html = prepare_email.build(consolidated, [search])
            log.info(f"  Subject: {subject}")

            if opts.dry_run:
                safe = name.replace(" ", "_").replace("/", "-").replace("→", "to")
                preview = results_dir / f"email_preview_{safe}.html"
                preview.parent.mkdir(parents=True, exist_ok=True)
                preview.write_text(html, encoding="utf-8")
                log.info(f"  Dry run → {preview}")
            else:
                send_email.send(subject, html, settings)

    if cache:
        _save_results(all_consolidated, results_dir)

    if not per_search_email:
        total = sum(len(v) for v in all_consolidated.values())
        alerts = sum(1 for v in all_consolidated.values() for r in v if r.alert)
        log.info(f"All searches done: {total} results, {alerts} alert(s)")

        if only_alerts and alerts == 0:
            log.info("No alerts and send_email_only_if_alerts=true — email skipped.")
            return

        subject, html = prepare_email.build(all_consolidated, searches)
        log.info(f"Subject: {subject}")

        if opts.dry_run:
            preview_path = results_dir / "email_preview.html"
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            preview_path.write_text(html, encoding="utf-8")
            log.info(f"Dry run — email preview saved to {preview_path}")
        else:
            send_email.send(subject, html, settings)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Unhandled error in main: %s", e)
        sys.exit(0)  # Always exit 0 so the scheduled task doesn't block future runs.
