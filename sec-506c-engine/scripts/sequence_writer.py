#!/usr/bin/env python3
"""
Smartlead Sequence Writer for 506(c) Pipeline
Creates a 4-step email sequence on an existing Smartlead campaign.

Usage:
    # Write sequence to an existing campaign (from campaign_meta JSON)
    python3 sequence_writer.py --meta data/enriched/campaign_meta_YYYYMMDD.json

    # Write sequence to a specific campaign ID
    python3 sequence_writer.py --campaign-id 12345678

    # Preview emails without hitting API
    python3 sequence_writer.py --campaign-id 12345678 --dry-run
"""

import json, os, sys, argparse
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

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

# ---------------------------------------------------------------------------
# Sequence copy — MoneyShow 506(c) sponsor outreach
# Personalization variables (Smartlead syntax: {{variable_name}}):
#   {{first_name}}        — contact first name
#   {{company_name}}      — company name
#   {{offering_amount}}   — e.g. "$10,000,000"
#   {{industry_group}}    — e.g. "Pooled Investment Fund"
#   {{title}}             — contact title
# ---------------------------------------------------------------------------

SEQUENCE = [
    {
        "seq_delay_details": {"delay_in_days": 0},
        "subject": "Your raise + 150,000 accredited investors",
        "email_body": """\
<p>Hi {{first_name}},</p>

<p>Noticed {{company_name}}'s recent 506(c) filing — raising capital from accredited investors is exactly what MoneyShow is built for.</p>

<p>We connect 150,000+ serious retail and institutional investors with the funds and financial firms they're evaluating each year, across our live conferences and year-round digital events. Our audience self-selects as accredited: they attend specifically to find their next allocation.</p>

<p>Sponsors typically see direct conversations with 50–200 qualified prospects per event — people already in capital-deployment mode.</p>

<p>Would a quick call make sense? Happy to share what firms at your stage have done with us.</p>

<p>Michael Berger<br>
Chief Marketing Officer, MoneyShow<br>
<a href="https://www.moneyshow.com">moneyshow.com</a></p>
""",
    },
    {
        "seq_delay_details": {"delay_in_days": 3},
        "subject": "What 506(c) sponsors get from MoneyShow",
        "email_body": """\
<p>Hi {{first_name}},</p>

<p>A few specifics on what exhibiting at MoneyShow looks like for a firm in {{company_name}}'s position:</p>

<ul>
<li><strong>Audience:</strong> 150,000+ registered investors — 80%+ accredited, $500K+ investable assets median</li>
<li><strong>Format:</strong> Booth + speaking session packages available; your team presents directly to attendees already vetted by their event registration</li>
<li><strong>Timeline:</strong> Our next flagship event is Las Vegas 2026 — several exhibitor slots remain</li>
<li><strong>Proven fit:</strong> Asset managers, alternative funds, and fintech platforms are our top sponsor categories year over year</li>
</ul>

<p>If you'd like to see the full sponsor deck — specific traffic numbers, session formats, and pricing — I can send it over.</p>

<p>Michael Berger<br>
CMO, MoneyShow</p>
""",
    },
    {
        "seq_delay_details": {"delay_in_days": 7},
        "subject": "Las Vegas 2026 — limited slots left",
        "email_body": """\
<p>Hi {{first_name}},</p>

<p>We're finalizing the exhibitor roster for MoneyShow Las Vegas 2026. A few packages are still available, but the floor plan fills fast once we open registration broadly.</p>

<p>Given {{company_name}}'s raise timing, this event lands at exactly the right moment — attendees are actively evaluating fund managers and alternative allocations through Q4.</p>

<p>Worth 20 minutes to see if it's a fit? I can pull together a proposal specific to your raise size and investor profile.</p>

<p>Michael Berger<br>
CMO, MoneyShow<br>
<a href="mailto:mberger@moneyshow.com">mberger@moneyshow.com</a></p>
""",
    },
    {
        "seq_delay_details": {"delay_in_days": 14},
        "subject": "Last note from me",
        "email_body": """\
<p>Hi {{first_name}},</p>

<p>Last note on this — I don't want to keep hitting your inbox if the timing isn't right.</p>

<p>If MoneyShow is ever relevant as you continue raising — we're the largest independent investor conference network in the country, and accredited-investor access is what we do — feel free to reach out directly at <a href="mailto:mberger@moneyshow.com">mberger@moneyshow.com</a>.</p>

<p>Either way, good luck with the {{company_name}} raise.</p>

<p>Michael Berger<br>
CMO, MoneyShow</p>
""",
    },
]


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
        body = e.read().decode("utf-8", errors="replace")[:400]
        print(f"  HTTP {e.code} {method} {endpoint}: {body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error {method} {endpoint}: {e}", file=sys.stderr)
        return None


def get_existing_sequences(campaign_id):
    result = sl_request("GET", f"campaigns/{campaign_id}/sequences")
    if not result:
        return []
    if isinstance(result, list):
        return result
    return result.get("data", {}).get("sequences", []) or result.get("sequences", [])


def create_all_sequences(campaign_id, steps):
    """Upload all sequence steps in one API call."""
    payload = {"sequences": [{"seq_number": i + 1, **step} for i, step in enumerate(steps)]}
    return sl_request("POST", f"campaigns/{campaign_id}/sequences", payload)


def main():
    parser = argparse.ArgumentParser(description="Write 506(c) email sequence to Smartlead campaign")
    parser.add_argument("--campaign-id", type=int, default=None, help="Smartlead campaign ID")
    parser.add_argument("--meta",        default=None,           help="campaign_meta JSON from deployer (auto-extracts campaign ID)")
    parser.add_argument("--dry-run",     action="store_true",    help="Print emails without calling API")
    args = parser.parse_args()

    if not API_KEY and not args.dry_run:
        print("ERROR: SMARTLEAD_API_KEY not set in .env")
        sys.exit(1)

    campaign_id = args.campaign_id
    if not campaign_id and args.meta:
        meta = json.loads(Path(args.meta).read_text())
        campaign_id = meta.get("campaign_id")
        print(f"Using campaign '{meta.get('campaign_name')}' (ID: {campaign_id})")

    if not campaign_id and not args.dry_run:
        print("ERROR: provide --campaign-id or --meta")
        sys.exit(1)

    if args.dry_run:
        print(f"[dry-run] Would write {len(SEQUENCE)} sequence steps to campaign {campaign_id or '(none)'}\n")
        for i, step in enumerate(SEQUENCE, 1):
            day = step["seq_delay_details"]["delay_in_days"]
            print(f"--- Step {i} | Day {day} | Subject: {step['subject']} ---")
            # Strip HTML tags for preview
            import re
            body = re.sub(r"<[^>]+>", "", step["email_body"]).strip()
            print(body[:400])
            print()
        return

    # Check for existing steps
    existing = get_existing_sequences(campaign_id)
    if existing:
        print(f"Campaign already has {len(existing)} sequence step(s) — skipping (delete them in Smartlead UI to reset)")
        sys.exit(0)

    print(f"Writing {len(SEQUENCE)} sequence steps to campaign {campaign_id}...")
    result = create_all_sequences(campaign_id, SEQUENCE)
    if result and result.get("ok"):
        for i, step in enumerate(SEQUENCE, 1):
            day = step["seq_delay_details"]["delay_in_days"]
            print(f"  Step {i} created (Day {day}): {step['subject']}")
    else:
        print(f"  Sequence creation FAILED: {result}")

    print(f"""
{'='*60}
SEQUENCE ATTACHED
{'='*60}
Campaign ID: {campaign_id}
Steps:       {len(SEQUENCE)}
  Day  0 — {SEQUENCE[0]['subject']}
  Day  3 — {SEQUENCE[1]['subject']}
  Day  7 — {SEQUENCE[2]['subject']}
  Day 14 — {SEQUENCE[3]['subject']}

Activate campaign in Smartlead UI to start sending.
{'='*60}
""")


if __name__ == "__main__":
    main()
