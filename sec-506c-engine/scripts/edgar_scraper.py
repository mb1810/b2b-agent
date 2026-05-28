#!/usr/bin/env python3
"""
EDGAR 506(c) Form D Scraper
Fetches recent Rule 506(c) private placement filings from SEC EDGAR.
Outputs a JSON file of companies ready for Apollo enrichment.

Usage:
    python3 edgar_scraper.py                          # last 90 days, all industries
    python3 edgar_scraper.py --days 180               # last 180 days
    python3 edgar_scraper.py --industry "Pooled Investment Fund"
    python3 edgar_scraper.py --min-offering 1000000   # $1M+ offerings only
    python3 edgar_scraper.py --dry-run                # show counts, don't fetch XMLs
"""

import json, os, sys, time, re, argparse
from pathlib import Path
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

SCRIPT_DIR   = Path(__file__).resolve().parent
DATA_DIR     = SCRIPT_DIR.parent / "data"
CACHE_DIR    = DATA_DIR / "edgar-cache"
OUTPUT_DIR   = DATA_DIR / "enriched"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT   = "MoneyShow-B2B-Research/1.0 mberger@moneyshow.com"
EFTS_BASE    = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

# Industry groups most likely to want to reach MoneyShow's investor audience
INVESTMENT_INDUSTRIES = {
    "Pooled Investment Fund",
    "Other Investment Fund",
    "Investment Fund",
}

# Industry groups to skip (not relevant to MoneyShow sponsors)
SKIP_INDUSTRIES = {
    "Other Real Estate", "Residential", "Commercial",
    "Restaurant", "Agriculture", "Mining & Extraction",
    "Oil and Gas", "Retail", "Health Care",
    "Manufacturing", "Travel", "Automotive",
    "Resorts & Leisure", "Lodging & Conventions",
    "Telecommunications",
}

# Industry groups that are high-fit for MoneyShow sponsors
HIGH_FIT_INDUSTRIES = {
    "Pooled Investment Fund",
    "Other Investment Fund",
    "Other Banking and Financial Services",
    "Investing",
    "REITS and Finance",
    "Investment Fund",
    "Other Technology",   # fintech
    "Business Services",  # financial services firms
}


def fetch_url(url, timeout=15, retries=3):
    req = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt * 5
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  HTTP {e.code} for {url}", file=sys.stderr)
                return None
        except (URLError, Exception) as e:
            print(f"  Error fetching {url}: {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(2)
    return None


def search_edgar(start_date, end_date, page=1, per_page=50):
    """Query EFTS for Form D filings with 06C (Rule 506c) exemption."""
    from_offset = (page - 1) * per_page
    params = (
        f"?q=%2206c%22"
        f"&forms=D"
        f"&dateRange=custom"
        f"&startdt={start_date}"
        f"&enddt={end_date}"
        f"&from={from_offset}"
    )
    url = EFTS_BASE + params
    content = fetch_url(url)
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def get_filing_xml(cik, adsh):
    """Fetch Form D XML for a specific filing. Caches for 7 days."""
    cache_file = CACHE_DIR / f"{adsh.replace('-', '')}.json"
    if cache_file.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        if age.days < 7:
            return json.loads(cache_file.read_text())

    adsh_path = adsh.replace("-", "")
    url = f"{ARCHIVES_BASE}/{cik}/{adsh_path}/primary_doc.xml"
    content = fetch_url(url)
    if not content:
        return None

    def extract(tag, text):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL)
        return m.group(1).strip() if m else None

    def extract_int(tag, text):
        val = extract(tag, text)
        if val:
            try:
                return int(float(val.replace(",", "")))
            except (ValueError, AttributeError):
                pass
        return None

    # Extract related persons (fund principals)
    related_persons = []
    rp_block = re.search(r"<relatedPersonsList>(.*?)</relatedPersonsList>", content, re.DOTALL)
    if rp_block:
        for rp in re.findall(r"<relatedPersonInfo>(.*?)</relatedPersonInfo>", rp_block.group(1), re.DOTALL):
            fn = extract("firstName", rp) or ""
            ln = extract("lastName", rp) or ""
            rels = re.findall(r"<relationship>(.*?)</relationship>", rp)
            if fn or ln:
                related_persons.append({
                    "first_name": fn,
                    "last_name":  ln,
                    "roles":      rels,
                })

    data = {
        "issuer_name":       extract("issuerName", content),
        "industry_group":    extract("industryGroupType", content),
        "offering_amount":   extract_int("totalOfferingAmount", content),
        "amount_sold":       extract_int("totalAmountSold", content),
        "city":              extract("city", content),
        "state":             extract("stateOrCountry", content),
        "zip":               extract("zipCode", content),
        "phone":             extract("issuerPhoneNumber", content),
        "entity_type":       extract("entityType", content),
        "signer_name":       extract("signatureName", content),
        "signer_title":      extract("signatureTitle", content),
        "related_persons":   related_persons,
    }

    cache_file.write_text(json.dumps(data))
    return data


def parse_display_name(raw):
    """Extract company name and CIK from 'Company Name  (CIK 0001234567)'."""
    m = re.match(r"^(.*?)\s+\(CIK\s+(\d+)\)$", raw.strip())
    if m:
        return m.group(1).strip(), m.group(2).lstrip("0")
    return raw.strip(), None


def scrape(days=90, min_offering=0, industry_filter=None, dry_run=False, max_results=500):
    end_date   = datetime.today().strftime("%Y-%m-%d")
    start_date = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    print(f"Searching EDGAR Form D 506(c) filings: {start_date} → {end_date}")

    # --- Phase 1: collect filing metadata from EFTS ---
    all_hits = []
    page = 1
    per_page = 50
    while True:
        result = search_edgar(start_date, end_date, page=page, per_page=per_page)
        if not result:
            break
        hits = result["hits"]["hits"]
        total = result["hits"]["total"]["value"]
        if page == 1:
            print(f"Found {total} total 506(c) Form D filings in window")
        all_hits.extend(hits)
        if len(all_hits) >= total or len(all_hits) >= max_results or len(hits) < per_page:
            break
        page += 1
        time.sleep(0.2)

    print(f"Retrieved {len(all_hits)} filing stubs")

    if dry_run:
        print("[dry-run] Skipping XML fetch. Sample companies:")
        for h in all_hits[:5]:
            name_raw = h["_source"].get("display_names", ["Unknown"])[0]
            name, cik = parse_display_name(name_raw)
            print(f"  {name} ({h['_source'].get('biz_locations', ['?'])[0]}) filed {h['_source']['file_date']}")
        return []

    # --- Phase 2: fetch XML for each filing ---
    companies = []
    skipped = 0
    print(f"Fetching XML details for up to {len(all_hits)} filings...")

    for i, hit in enumerate(all_hits):
        src = hit["_source"]
        name_raw = src.get("display_names", ["Unknown"])[0]
        name, cik = parse_display_name(name_raw)
        adsh = src.get("adsh", "")
        file_date = src.get("file_date", "")
        location = src.get("biz_locations", [""])[0]

        if not cik or not adsh:
            skipped += 1
            continue

        time.sleep(0.15)  # stay well under SEC's 10 req/sec limit
        xml_data = get_filing_xml(cik, adsh)

        if not xml_data:
            skipped += 1
            continue

        industry = xml_data.get("industry_group") or ""
        offering = xml_data.get("offering_amount") or 0
        amount_sold = xml_data.get("amount_sold") or 0

        # Apply filters
        if industry_filter and industry_filter.lower() not in industry.lower():
            skipped += 1
            continue
        if industry in SKIP_INDUSTRIES:
            skipped += 1
            continue
        if offering < min_offering:
            skipped += 1
            continue

        company = {
            "company_name":    xml_data.get("issuer_name") or name,
            "icp_fit":         "high" if industry in HIGH_FIT_INDUSTRIES else "medium",
            "signer_name":     xml_data.get("signer_name") or "",
            "signer_title":    xml_data.get("signer_title") or "",
            "related_persons": xml_data.get("related_persons") or [],
            "cik":             cik,
            "adsh":            adsh,
            "file_date":       file_date,
            "location":        location,
            "city":            xml_data.get("city") or "",
            "state":           xml_data.get("state") or src.get("biz_states", [""])[0],
            "zip":             xml_data.get("zip") or "",
            "phone":           xml_data.get("phone") or "",
            "industry_group":  industry,
            "entity_type":     xml_data.get("entity_type") or "",
            "offering_amount": offering,
            "amount_sold":     amount_sold,
            "edgar_url":       f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=D",
        }
        companies.append(company)

        if (i + 1) % 25 == 0:
            print(f"  Processed {i+1}/{len(all_hits)}, kept {len(companies)}, skipped {skipped}")

    print(f"\nDone. Kept {len(companies)} companies, skipped {skipped}")
    return companies


def main():
    parser = argparse.ArgumentParser(description="Scrape SEC EDGAR for 506(c) Form D filings")
    parser.add_argument("--days",         type=int,   default=90,    help="Lookback window in days (default: 90)")
    parser.add_argument("--min-offering", type=int,   default=0,     help="Minimum offering amount in $ (default: 0)")
    parser.add_argument("--industry",     type=str,   default=None,  help="Filter to specific industry group (partial match)")
    parser.add_argument("--max-results",  type=int,   default=500,   help="Max filings to process (default: 500)")
    parser.add_argument("--output",       type=str,   default=None,  help="Output JSON file path")
    parser.add_argument("--dry-run",      action="store_true",       help="Show counts only, skip XML fetch")
    args = parser.parse_args()

    companies = scrape(
        days=args.days,
        min_offering=args.min_offering,
        industry_filter=args.industry,
        dry_run=args.dry_run,
        max_results=args.max_results,
    )

    if args.dry_run or not companies:
        return

    output_path = args.output or str(OUTPUT_DIR / f"edgar_506c_{datetime.today().strftime('%Y%m%d')}.json")
    with open(output_path, "w") as f:
        json.dump(companies, f, indent=2)

    print(f"\nSaved {len(companies)} companies → {output_path}")
    print("\nSample output:")
    for c in companies[:3]:
        amt = f"${c['offering_amount']:,}" if c['offering_amount'] else "undisclosed"
        sold = f"${c['amount_sold']:,}" if c['amount_sold'] else "$0"
        print(f"  {c['company_name']} | {c['industry_group']} | Offering: {amt} | Sold: {sold} | {c['city']}, {c['state']}")


if __name__ == "__main__":
    main()
