#!/usr/bin/env python3
"""
506(c) Full Pipeline Orchestrator
Runs: EDGAR scrape → Apollo enrich → Account research → Smartlead deploy.

Usage:
    python3 pipeline.py                          # 90 days, high-fit only, new leads only
    python3 pipeline.py --days 180 --limit 200
    python3 pipeline.py --skip-scrape            # re-use latest EDGAR file
    python3 pipeline.py --skip-enrich            # re-use latest enriched file
    python3 pipeline.py --dry-run                # scrape only, no API calls
    python3 pipeline.py --all                    # ignore seen cache, re-process everything
"""

import json, os, sys, subprocess, argparse
from pathlib import Path
from datetime import datetime

SCRIPT_DIR   = Path(__file__).resolve().parent
DATA_DIR     = SCRIPT_DIR.parent / "data"
REPO_ROOT    = SCRIPT_DIR.parent.parent

EDGAR_SCRIPT      = SCRIPT_DIR / "edgar_scraper.py"
ENRICHER_SCRIPT   = SCRIPT_DIR / "apollo_enricher.py"
DEPLOYER_SCRIPT   = SCRIPT_DIR / "smartlead_deployer.py"
RESEARCHER_SCRIPT = REPO_ROOT / "lead-dossier" / "scripts" / "account-researcher.py"

SEEN_FILE = DATA_DIR / "seen_adsh.json"


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def run(cmd, label):
    print(f"\n{'='*60}")
    print(f"STEP: {label}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"ERROR: {label} failed (exit {result.returncode})")
        sys.exit(1)


def latest_file(directory, pattern):
    files = sorted(Path(directory).glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    return str(files[0]) if files else None


def main():
    parser = argparse.ArgumentParser(description="506(c) → Apollo → Research pipeline")
    parser.add_argument("--days",         type=int, default=90,   help="EDGAR lookback days")
    parser.add_argument("--min-offering", type=int, default=0,    help="Min offering amount ($)")
    parser.add_argument("--limit",        type=int, default=100,  help="Max leads to enrich")
    parser.add_argument("--skip-scrape",  action="store_true",    help="Skip EDGAR scrape, use latest file")
    parser.add_argument("--skip-enrich",  action="store_true",    help="Skip Apollo enrich, use latest file")
    parser.add_argument("--dry-run",       action="store_true",   help="EDGAR dry run only")
    parser.add_argument("--no-research",   action="store_true",   help="Skip account research step")
    parser.add_argument("--no-deploy",     action="store_true",   help="Skip Smartlead deployment step")
    parser.add_argument("--campaign-name", default="MoneyShow 506c Sponsors - May 2026", help="Smartlead campaign name")
    parser.add_argument("--domain",        default=None,          help="Sending domain filter (e.g. MoneyShowExhibitor.com)")
    parser.add_argument("--all",           action="store_true",   help="Ignore seen cache, re-process everything")
    args = parser.parse_args()

    today = datetime.today().strftime("%Y%m%d")

    # --- Step 1: EDGAR Scrape ---
    if args.dry_run:
        run([sys.executable, str(EDGAR_SCRIPT), "--days", str(args.days), "--dry-run"], "EDGAR 506(c) Scrape (dry run)")
        return

    if args.skip_scrape:
        edgar_file = latest_file(DATA_DIR / "enriched", "edgar_506c_*.json")
        if not edgar_file:
            print("No existing EDGAR file found. Run without --skip-scrape first.")
            sys.exit(1)
        print(f"Using existing EDGAR file: {edgar_file}")
    else:
        edgar_file = str(DATA_DIR / "enriched" / f"edgar_506c_{today}.json")
        run([
            sys.executable, str(EDGAR_SCRIPT),
            "--days",         str(args.days),
            "--min-offering", str(args.min_offering),
            "--max-results",  "500",
            "--output",       edgar_file,
        ], "EDGAR 506(c) Scrape")

    # --- Filter to new filings only ---
    seen = set() if args.all else load_seen()
    if not args.skip_enrich:
        all_companies = json.loads(Path(edgar_file).read_text())
        new_companies = [c for c in all_companies if c.get("adsh") not in seen]
        skipped = len(all_companies) - len(new_companies)
        if skipped:
            print(f"\nSeen cache: skipping {skipped} already-processed filings, {len(new_companies)} new")
        if not new_companies:
            print("No new filings since last run. Nothing to do.")
            sys.exit(0)
        # Write new-only file for enricher
        new_file = edgar_file.replace(".json", "_new.json")
        Path(new_file).write_text(json.dumps(new_companies, indent=2))
        edgar_file = new_file

    # --- Step 2: Apollo Enrich ---
    if args.skip_enrich:
        enriched_file = latest_file(DATA_DIR / "enriched", "*_enriched.json")
        if not enriched_file:
            print("No existing enriched file found. Run without --skip-enrich first.")
            sys.exit(1)
        print(f"Using existing enriched file: {enriched_file}")
    else:
        enriched_file = edgar_file.replace("_new.json", "_enriched.json").replace(".json", "_enriched.json")
        run([
            sys.executable, str(ENRICHER_SCRIPT),
            "--input",        edgar_file,
            "--output",       enriched_file,
            "--high-fit-only",
            "--limit",        str(args.limit),
        ], "Apollo Enrichment")

        # Update seen cache with newly processed ADSHs
        if not args.all:
            new_adsh = {c["adsh"] for c in json.loads(Path(edgar_file).read_text()) if c.get("adsh")}
            seen.update(new_adsh)
            save_seen(seen)
            print(f"Seen cache updated: {len(seen)} total filings tracked")

    # --- Step 3: Account Research ---
    if not args.no_research and RESEARCHER_SCRIPT.exists():
        enriched = json.loads(Path(enriched_file).read_text())
        ready = [c for c in enriched if c.get("domain") and c.get("contact_email")]

        if ready:
            # Build prospects.json for account-researcher
            prospects_file = str(DATA_DIR / "enriched" / f"prospects_{today}.json")
            prospects = [{"domain": c["domain"], "company": c["company_name"]} for c in ready]
            Path(prospects_file).write_text(json.dumps(prospects, indent=2))

            run([
                sys.executable, str(RESEARCHER_SCRIPT),
                prospects_file,
            ], f"Account Research ({len(prospects)} companies)")
        else:
            print("\nNo enriched leads with emails found — skipping account research")
    elif not RESEARCHER_SCRIPT.exists():
        print(f"\nSkipping account research (script not found at {RESEARCHER_SCRIPT})")

    # --- Step 4: Smartlead Deploy ---
    if not args.no_deploy:
        deploy_cmd = [
            sys.executable, str(DEPLOYER_SCRIPT),
            "--input", enriched_file,
        ]
        if args.campaign_name:
            deploy_cmd += ["--campaign-name", args.campaign_name]
        if args.domain:
            deploy_cmd += ["--domain", args.domain]
        run(deploy_cmd, "Smartlead Campaign Deploy")

    # --- Summary ---
    enriched = json.loads(Path(enriched_file).read_text())
    ready = [c for c in enriched if c.get("contact_email")]

    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE")
    print(f"{'='*60}")
    print(f"Total enriched:          {len(enriched)}")
    print(f"Leads with email:        {len(ready)}")
    print(f"Enriched file:           {enriched_file}")
    print(f"\nReady for sequencing (top 15):")
    print(f"{'Name':<25} {'Title':<35} {'Company':<35} {'Offering':<15} {'Email'}")
    print("-" * 130)
    for c in ready[:15]:
        name     = f"{c.get('contact_first_name','')} {c.get('contact_last_name','')}".strip()
        title    = (c.get("contact_title") or "")[:34]
        company  = c["company_name"][:34]
        offering = f"${c['offering_amount']:,}" if c.get("offering_amount") else "?"
        email    = c.get("contact_email", "")
        print(f"{name:<25} {title:<35} {company:<35} {offering:<15} {email}")

    if args.no_deploy:
        print(f"\nNext step: python3 scripts/smartlead_deployer.py --input {enriched_file}")


if __name__ == "__main__":
    main()
