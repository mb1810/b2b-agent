#!/usr/bin/env python3
"""
Apollo Enricher for 506(c) Pipeline
Takes EDGAR company list, finds domain + CMO/marketing contact via Apollo REST API.

Usage:
    python3 apollo_enricher.py --input data/enriched/edgar_506c_YYYYMMDD.json
    python3 apollo_enricher.py --input data/enriched/edgar_506c_YYYYMMDD.json --high-fit-only
    python3 apollo_enricher.py --input data/enriched/edgar_506c_YYYYMMDD.json --limit 50

Requires:
    APOLLO_API_KEY in .env or environment
"""

import json, os, sys, time, argparse
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR   = SCRIPT_DIR.parent / "data"

# Load .env — check skill dir first, then repo root
env_file = SCRIPT_DIR.parent / ".env"
if not env_file.exists():
    env_file = SCRIPT_DIR.parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
APOLLO_BASE    = "https://api.apollo.io/v1"

TARGET_TITLES = [
    "CMO", "Chief Marketing Officer",
    "VP Marketing", "VP of Marketing", "Vice President Marketing",
    "Head of Marketing", "Director of Marketing",
    "Head of Investor Relations", "Head of Distribution",
    "Head of Advisor Relations", "Director of Distribution",
    "CEO", "Founder", "President",
    "Managing Director", "Managing Partner",
]


def apollo_request(endpoint, payload, retries=3):
    if not APOLLO_API_KEY:
        print("ERROR: APOLLO_API_KEY not set. Add it to .env or export it.", file=sys.stderr)
        sys.exit(1)

    url  = f"{APOLLO_BASE}/{endpoint}"
    body = json.dumps(payload).encode("utf-8")
    req  = Request(url, data=body, headers={
        "Content-Type":  "application/json",
        "X-Api-Key":     APOLLO_API_KEY,
        "Cache-Control": "no-cache",
    })

    for attempt in range(retries):
        try:
            with urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt * 5
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            elif e.code in (401, 403):
                print(f"  Auth error — check APOLLO_API_KEY", file=sys.stderr)
                return None
            else:
                body_txt = e.read().decode("utf-8", errors="replace")[:200]
                print(f"  HTTP {e.code}: {body_txt}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"  Request error: {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(2)
    return None


def enrich_organization(company_name, city=None, state=None):
    """Search Apollo for an organization by name, return domain + Apollo org ID."""
    payload = {
        "q_organization_name": company_name,
        "per_page": 5,
    }
    if state:
        payload["organization_locations"] = [f"{city}, {state}" if city else state]

    result = apollo_request("mixed_companies/search", payload)
    if not result or not result.get("organizations"):
        return None

    orgs = result["organizations"]
    # Prefer exact or close name match
    name_lower = company_name.lower()
    for org in orgs:
        if org.get("name", "").lower() in name_lower or name_lower in org.get("name", "").lower():
            return {
                "apollo_org_id":    org.get("id"),
                "domain":           org.get("primary_domain") or org.get("website_url", "").replace("https://", "").replace("http://", "").split("/")[0],
                "apollo_org_name":  org.get("name"),
                "employee_count":   org.get("estimated_num_employees"),
                "linkedin_url":     org.get("linkedin_url"),
                "description":      org.get("short_description") or org.get("seo_description"),
            }
    # Fall back to first result
    org = orgs[0]
    return {
        "apollo_org_id":    org.get("id"),
        "domain":           org.get("primary_domain") or "",
        "apollo_org_name":  org.get("name"),
        "employee_count":   org.get("estimated_num_employees"),
        "linkedin_url":     org.get("linkedin_url"),
        "description":      org.get("short_description") or org.get("seo_description"),
    }


def find_contact(org_id, company_name, domain=None):
    """Find CMO/marketing/CEO contact at the organization via Apollo people search."""
    payload = {
        "person_titles":    TARGET_TITLES,
        "person_seniorities": ["c_suite", "vp", "director", "owner"],
        "per_page":         5,
        "contact_email_status": ["verified", "likely to engage"],
    }
    if org_id:
        payload["organization_ids"] = [org_id]
    elif company_name:
        payload["q_keywords"] = company_name

    result = apollo_request("mixed_people/search", payload)
    if not result or not result.get("people"):
        return None

    people = result["people"]
    if not people:
        return None

    # Pick best title match (CMO > VP Marketing > CEO)
    priority = ["cmo", "chief marketing", "vp marketing", "vp of marketing",
                "head of marketing", "head of distribution", "head of investor",
                "director of marketing", "ceo", "founder", "president"]
    for target in priority:
        for p in people:
            if target in (p.get("title") or "").lower():
                return _extract_person(p)

    return _extract_person(people[0])


def match_email(first_name, last_name, domain, org_id=None):
    """Use Apollo people_match to get verified email."""
    payload = {
        "first_name": first_name,
        "last_name":  last_name,
        "domain":     domain,
        "reveal_personal_emails": False,
    }
    if org_id:
        payload["organization_id"] = org_id

    result = apollo_request("people/match", payload)
    if not result or not result.get("person"):
        return None
    person = result["person"]
    return person.get("email") or person.get("personal_emails", [None])[0]


def _extract_person(p):
    last = p.get("last_name") or p.get("last_name_obfuscated", "")
    return {
        "contact_first_name": p.get("first_name"),
        "contact_last_name":  last,
        "contact_title":      p.get("title"),
        "contact_linkedin":   p.get("linkedin_url"),
        "apollo_person_id":   p.get("id"),
        "has_email":          p.get("has_email", False),
    }


def enrich_company(company, resolve_emails=True):
    """
    Enrichment strategy for 506(c) fund vehicles:
    1. Extract principal name from Form D (signer or related person)
    2. Use Apollo people/match with name + company name to find their profile + email
    3. Fall back to org search if no named principal found
    """
    company_name = company["company_name"]

    # Build candidate contacts from Form D data
    candidates = []
    signer = company.get("signer_name", "")
    signer_title = company.get("signer_title", "")
    if signer and " " in signer:
        parts = signer.strip().split(" ", 1)
        candidates.append({"first_name": parts[0], "last_name": parts[1], "title": signer_title})

    for rp in company.get("related_persons", []):
        if rp.get("first_name") and rp.get("last_name"):
            roles = ", ".join(rp.get("roles", []))
            candidates.append({"first_name": rp["first_name"], "last_name": rp["last_name"], "title": roles})

    if not candidates:
        # Fall back to org search
        org_data = enrich_organization(company_name, company.get("city"), company.get("state"))
        if not org_data:
            company["apollo_status"] = "no_principal_found"
            return company
        company.update(org_data)
        contact = find_contact(org_data.get("apollo_org_id"), company_name)
        if not contact:
            company["apollo_status"] = "contact_not_found"
            return company
        company.update(contact)
        candidates = [{"first_name": contact["contact_first_name"],
                       "last_name":  contact.get("contact_last_name", ""),
                       "title":      contact.get("contact_title", "")}]

    # Try each candidate via people/match
    for candidate in candidates:
        first = candidate["first_name"]
        last  = candidate["last_name"]

        result = apollo_request("people/match", {
            "first_name":        first,
            "last_name":         last,
            "organization_name": company_name,
            "reveal_personal_emails": False,
        })

        if result and result.get("person"):
            person = result["person"]
            email  = person.get("email")
            domain = (person.get("organization") or {}).get("primary_domain", "")

            company["contact_first_name"] = first
            company["contact_last_name"]  = last
            company["contact_title"]      = candidate.get("title") or person.get("title") or ""
            company["contact_email"]      = email
            company["contact_linkedin"]   = person.get("linkedin_url")
            company["domain"]             = domain
            company["employee_count"]     = (person.get("organization") or {}).get("estimated_num_employees")
            company["apollo_person_id"]   = person.get("id")
            company["apollo_status"]      = "enriched" if email else "profile_found_no_email"
            return company

    company["apollo_status"] = "person_not_in_apollo"
    # Still store the principal name even without Apollo match
    if candidates:
        company["contact_first_name"] = candidates[0]["first_name"]
        company["contact_last_name"]  = candidates[0]["last_name"]
        company["contact_title"]      = candidates[0].get("title", "")
    return company


def main():
    parser = argparse.ArgumentParser(description="Enrich 506(c) EDGAR companies via Apollo")
    parser.add_argument("--input",         required=True, help="Path to EDGAR scraper output JSON")
    parser.add_argument("--output",        default=None,  help="Output JSON path (default: auto-named)")
    parser.add_argument("--limit",         type=int,      default=None, help="Max companies to process")
    parser.add_argument("--high-fit-only", action="store_true",          help="Only process high-ICP-fit companies")
    parser.add_argument("--no-email",      action="store_true",          help="Skip email resolution step")
    args = parser.parse_args()

    companies = json.loads(Path(args.input).read_text())
    print(f"Loaded {len(companies)} companies from {args.input}")

    if args.high_fit_only:
        companies = [c for c in companies if c.get("icp_fit") == "high"]
        print(f"Filtered to {len(companies)} high-fit companies")

    if args.limit:
        companies = companies[:args.limit]
        print(f"Capped at {args.limit} companies")

    enriched = []
    for i, company in enumerate(companies):
        print(f"[{i+1}/{len(companies)}] {company['company_name']} ({company.get('industry_group', '?')})...")
        result = enrich_company(company, resolve_emails=not args.no_email)
        enriched.append(result)

        status = result.get("apollo_status", "unknown")
        email  = result.get("contact_email", "")
        name   = f"{result.get('contact_first_name','')} {result.get('contact_last_name','')}".strip()
        title  = result.get("contact_title", "")
        print(f"  → {status} | {name} | {title} | {email or 'no email'}")

        time.sleep(0.3)  # Apollo rate limiting

    # Stats
    statuses = {}
    for c in enriched:
        s = c.get("apollo_status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1
    print(f"\nEnrichment summary: {statuses}")

    # Save
    output_path = args.output or str(
        Path(args.input).parent / (Path(args.input).stem + "_enriched.json")
    )
    with open(output_path, "w") as f:
        json.dump(enriched, f, indent=2)
    print(f"Saved {len(enriched)} enriched companies → {output_path}")

    # Print ready-to-contact leads
    ready = [c for c in enriched if c.get("contact_email")]
    print(f"\n{len(ready)} leads with verified emails — ready for sequencing:")
    for c in ready[:10]:
        amt = f"${c['offering_amount']:,}" if c.get('offering_amount') else "?"
        print(f"  {c['contact_first_name']} {c['contact_last_name']} | {c['contact_title']} | {c['company_name']} | {amt} | {c['contact_email']}")


if __name__ == "__main__":
    main()
