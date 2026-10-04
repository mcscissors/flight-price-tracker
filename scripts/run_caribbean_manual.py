"""
Manual Caribbean search runner (no preferred airlines filter).
Run with:
  python -m scripts.run_caribbean_manual
  python -m scripts.run_caribbean_manual --dry-run
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

(BASE / "data" / "logs").mkdir(parents=True, exist_ok=True)

_log_fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
_con = logging.StreamHandler(sys.stdout)
_con.stream.reconfigure(encoding="utf-8", errors="replace")
_con.setFormatter(_log_fmt)
_file = logging.FileHandler(
    BASE / "data" / "logs" / f"caribbean_{datetime.now():%Y%m%d_%H%M%S}.log",
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
    p = argparse.ArgumentParser(description="Caribbean manual search (no preferred airlines)")
    p.add_argument("--dry-run",     action="store_true", help="Build email but don't send it")
    p.add_argument("--no-google",   action="store_true", help="Skip Google Flights source")
    p.add_argument("--with-amadeus",action="store_true", help="Enable Amadeus")
    opts = p.parse_args(args)

    searches_cfg = _load_json(BASE / "config" / "searches.json")
    settings     = _load_json(BASE / "config" / "settings.json")

    # Find Caribbean Business search
    caribbean = None
    for s in searches_cfg["searches"]:
        if "Caribbean & Central America Business" in s.get("name", ""):
            caribbean = s.copy()
            break

    if not caribbean:
        log.error("Caribbean search not found in config")
        sys.exit(1)

    # Remove preferred airlines filter
    caribbean["preferred_airlines"] = []
    search_name = caribbean["name"] + " (manual, no preference)"
    caribbean["name"] = search_name

    log.info(f"=== {search_name} ===")

    run_cfg = settings.get("run", {})
    timeout_sec = run_cfg.get("request_timeout_sec", 60)
    results_dir = BASE / run_cfg.get("results_dir", "data/results")

    amadeus_client = _build_amadeus_client(settings) if opts.with_amadeus else None
    raw_results: list[FlightResult] = []

    if not opts.no_google:
        try:
            g_results = fetch_playwright.fetch(caribbean, timeout_sec=timeout_sec)
            log.info(f"  Google:  {len(g_results)} raw results")
            raw_results.extend(g_results)
        except Exception:
            log.exception(f"  Google fetch failed — skipping")

    if amadeus_client:
        a_results = fetch_amadeus.fetch(caribbean, amadeus_client)
        log.info(f"  Amadeus: {len(a_results)} raw results")
        raw_results.extend(a_results)

    consolidated = consolidate_mod.consolidate_all({search_name: raw_results}, [caribbean])
    n_results = len(consolidated.get(search_name, []))
    n_alerts = sum(1 for r in consolidated.get(search_name, []) if r.alert)

    log.info(f"  {n_results} results, {n_alerts} alert(s)")

    if n_results == 0:
        log.info("  No results after filtering — email skipped")
        return

    subject, html = prepare_email.build(consolidated, [caribbean])
    log.info(f"  Subject: {subject}")

    if opts.dry_run:
        safe = search_name.replace(" ", "_").replace("/", "-").replace("→", "to")
        preview = results_dir / f"email_preview_{safe}.html"
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_text(html, encoding="utf-8")
        log.info(f"  Dry run → {preview}")
    else:
        send_email.send(subject, html, settings)

    _save_results(consolidated, results_dir)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Unhandled error: %s", e)
        sys.exit(1)
