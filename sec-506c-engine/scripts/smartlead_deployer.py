#!/usr/bin/env python3
"""
Smartlead Campaign Deployer for 506(c) Pipeline
Creates a campaign, assigns sending accounts, and uploads enriched leads.

Usage:
    python3 smartlead_deployer.py --input data/enriched/edgar_506c_YYYYMMDD_enriched.json
    python3 smartlead_deployer.py --input ... --campaign-name "MoneyShow 506c Q2 2026"
    python3 smartlead_deployer.py --input ... --domain MoneyShowExhibitor.com
    python3 smartlead_deployer.py --input ... --dry-run

After running:
    - Campaign is created in Smartlead (paused, ready for sequence)
    - Leads are uploaded with personalization fields
    - Go to Smartlead UI → add sequence → activate campaign
"""

import json, os, sys, time, argparse, subprocess
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent

# Load .env
for candidate in [SCRIPT_DIR.parent / ".env", SCRIPT_DIR.parent.parent / ".env"]:
    if candidate.exists():
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))
        break

API_KEY  = os.environ.get("SMARTLEAD_API_KEY", "")
BASE_URL = "https://server.smartlead.ai/api/v1"

# Default campaign schedule — weekdays, 8am-5pm ET
DEFAULT_SCHEDULE = {
    "timezone": "America/New_York",
    "days_of_the_week": [1, 2, 3, 4, 5],  # Mon-Fri
    "start_hour": "08:00",
    "end_hour":   "17:00",
    "min_time_btw_emails": 10,
    "max_new_leads_per_day": 20,
}


def sl_request(method, endpoint, payload=None):
    sep = "&" if "?" in endpoint else "?"
    url = f"{BASE_URL}/{endpoint}{sep}api_key={API_KEY}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "MoneyShow-B2B/1.0",
        "Accept": "application/json",
    }
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        print(f"  HTTP {e.code} {method} {endpoint}: {body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error {method} {endpoint}: {e}", file=sys.stderr)
        return None


def get_email_accounts(domain_filter=None):
    """Get all active sending accounts, optionally filtered by domain."""
    accounts = sl_request("GET", "email-accounts?limit=100&offset=0")
    if not accounts:
        return []
    active = [a for a in accounts if a.get("is_smtp_success")]
    if domain_filter:
        active = [a for a in active if domain_filter.lower() in a.get("from_email", "").lower()]
    return active


def find_campaign_by_name(name):
    """Look up an existing campaign by exact name. Returns campaign dict or None."""
    result = sl_request("GET", "campaigns?limit=100&offset=0")
    if not result:
        return None
    campaigns = result if isinstance(result, list) else result.get("data", [])
    for c in campaigns:
        if c.get("name") == name:
            return c
    return None


def create_campaign(name):
    """Create a new Smartlead campaign (starts paused)."""
    result = sl_request("POST", "campaigns/create", {"name": name})
    return result


def update_campaign_schedule(campaign_id, schedule):
    """Set sending schedule on an existing campaign."""
    return sl_request("POST", f"campaigns/{campaign_id}/schedule", schedule)


def assign_email_accounts(campaign_id, account_ids):
    """Assign sending accounts to a campaign."""
    payload = {"email_account_ids": account_ids}
    return sl_request("POST", f"campaigns/{campaign_id}/email-accounts", payload)


def upload_leads(campaign_id, leads, dry_run=False):
    """Upload leads to campaign in batches of 100."""
    if dry_run:
        print(f"  [dry-run] Would upload {len(leads)} leads")
        return {"uploaded": len(leads)}

    BATCH = 100
    total_uploaded = 0

    for i in range(0, len(leads), BATCH):
        batch = leads[i:i + BATCH]
        payload = {
            "lead_list": batch,
            "settings": {
                "ignore_global_block_list":   True,
                "ignore_unsubscribe_list":    True,
                "ignore_community_bounce_list": False,
                "ignore_duplicate_leads_in_other_campaign": False,
            }
        }
        result = sl_request("POST", f"campaigns/{campaign_id}/leads", payload)
        if result:
            uploaded = result.get("upload_count", 0)
            dupes    = result.get("duplicate_count", 0) + result.get("already_added_to_campaign", 0)
            total_uploaded += uploaded
            print(f"  Batch {i//BATCH + 1}: {uploaded} uploaded, {dupes} dupes")
        time.sleep(0.5)

    return {"uploaded": total_uploaded}


def build_sl_lead(company):
    """Map enriched company record to Smartlead lead format."""
    offering = company.get("offering_amount")
    offering_str = f"${offering:,}" if offering else "undisclosed"

    return {
        "email":        company.get("contact_email", ""),
        "first_name":   company.get("contact_first_name", ""),
        "last_name":    company.get("contact_last_name", ""),
        "company_name": company.get("company_name", ""),
        "phone_number": company.get("phone", ""),
        "linkedin_profile": company.get("contact_linkedin", ""),
        "custom_fields": {
            "title":            company.get("contact_title", ""),
            "industry_group":   company.get("industry_group", ""),
            "offering_amount":  offering_str,
            "amount_sold":      f"${company['amount_sold']:,}" if company.get("amount_sold") else "",
            "state":            company.get("state", ""),
            "edgar_url":        company.get("edgar_url", ""),
            "icp_fit":          company.get("icp_fit", ""),
            "file_date":        company.get("file_date", ""),
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Deploy 506(c) leads to Smartlead")
    parser.add_argument("--input",         required=True,       help="Enriched leads JSON file")
    parser.add_argument("--campaign-name", default=None,        help="Campaign name (auto-generated if omitted)")
    parser.add_argument("--domain",        default=None,        help="Sending domain filter (e.g. MoneyShowExhibitor.com)")
    parser.add_argument("--max-accounts",  type=int, default=5, help="Max sending accounts to assign (default: 5)")
    parser.add_argument("--dry-run",       action="store_true", help="Preview without creating campaign or uploading")
    parser.add_argument("--no-sequence",   action="store_true", help="Skip auto-attaching email sequence")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: SMARTLEAD_API_KEY not set in .env")
        sys.exit(1)

    # Load enriched leads
    companies = json.loads(Path(args.input).read_text())
    ready = [c for c in companies if c.get("contact_email")]
    print(f"Loaded {len(companies)} companies, {len(ready)} with verified emails")

    if not ready:
        print("No leads with emails — run apollo_enricher.py first")
        sys.exit(1)

    # Deduplicate by email (keep first occurrence — largest offering amount for same person)
    ready.sort(key=lambda c: c.get("offering_amount") or 0, reverse=True)
    seen_emails = set()
    deduped = []
    for c in ready:
        email = c.get("contact_email", "").lower()
        if email and email not in seen_emails:
            seen_emails.add(email)
            deduped.append(c)
    if len(deduped) < len(ready):
        print(f"Deduplicated: {len(ready)} → {len(deduped)} unique contacts")
    ready = deduped

    # Build Smartlead lead objects
    sl_leads = [build_sl_lead(c) for c in ready]

    # Campaign name
    today = datetime.today().strftime("%Y-%m-%d")
    campaign_name = args.campaign_name or f"MoneyShow 506c Sponsors {today}"
    print(f"\nCampaign: {campaign_name}")
    print(f"Leads to upload: {len(sl_leads)}")

    # Get sending accounts
    accounts = get_email_accounts(domain_filter=args.domain)
    if not accounts:
        print(f"No active sending accounts found{' for domain ' + args.domain if args.domain else ''}")
        sys.exit(1)
    accounts = accounts[:args.max_accounts]
    print(f"Sending accounts ({len(accounts)}):")
    for a in accounts:
        print(f"  [{a['id']}] {a['from_email']} — {a['message_per_day']}/day")

    if args.dry_run:
        print("\n[dry-run] Sample lead payload:")
        print(json.dumps(sl_leads[0], indent=2))
        print(f"\n[dry-run] Would create campaign '{campaign_name}' with {len(sl_leads)} leads")
        return

    # Create or reuse campaign
    existing = find_campaign_by_name(campaign_name)
    if existing:
        campaign_id = existing["id"]
        print(f"\nFound existing campaign '{campaign_name}' (ID: {campaign_id}) — adding leads")
    else:
        print(f"\nCreating campaign...")
        campaign = create_campaign(campaign_name)
        if not campaign or not campaign.get("id"):
            print(f"Failed to create campaign: {campaign}")
            sys.exit(1)
        campaign_id = campaign["id"]
        print(f"Created campaign ID: {campaign_id}")
        update_campaign_schedule(campaign_id, DEFAULT_SCHEDULE)
        print(f"Schedule set: Mon-Fri 8am-5pm ET, max 20 new leads/day")
        account_ids = [a["id"] for a in accounts]
        assign_email_accounts(campaign_id, account_ids)
        print(f"Assigned {len(account_ids)} sending accounts")

    # Upload leads
    print(f"\nUploading {len(sl_leads)} leads...")
    upload_result = upload_leads(campaign_id, sl_leads)
    print(f"Uploaded: {upload_result.get('uploaded', 0)}")

    print(f"""
{'='*60}
CAMPAIGN READY
{'='*60}
Campaign ID:    {campaign_id}
Campaign name:  {campaign_name}
Leads uploaded: {upload_result.get('uploaded', 0)}
Status:         PAUSED — sequence attached, activate when ready

Next steps:
  1. Go to smartlead.ai → Campaigns → {campaign_name}
  2. Review sequence (4 steps auto-attached: Day 0 / 3 / 7 / 14)
  3. Activate campaign to start sending
{'='*60}
""")

    # Save campaign ID for reference
    meta_path = Path(args.input).parent / f"campaign_meta_{today}.json"
    meta_path.write_text(json.dumps({
        "campaign_id":   campaign_id,
        "campaign_name": campaign_name,
        "leads_file":    str(args.input),
        "leads_count":   len(sl_leads),
        "created_at":    today,
        "sending_accounts": [a["from_email"] for a in accounts],
    }, indent=2))
    print(f"Campaign metadata saved → {meta_path}")

    # Auto-attach sequence (only for new campaigns — sequence_writer skips if steps already exist)
    if not args.no_sequence and not existing:
        sequence_script = SCRIPT_DIR / "sequence_writer.py"
        if sequence_script.exists():
            print("\nAttaching email sequence...")
            subprocess.run([sys.executable, str(sequence_script), "--campaign-id", str(campaign_id)],
                           check=False)
        else:
            print(f"\nSequence writer not found at {sequence_script} — attach manually")


if __name__ == "__main__":
    main()
