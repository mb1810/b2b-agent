---
name: sec-506c-engine
description: >
  Custom pipeline: SEC EDGAR Rule 506(c) Form D scrape → Apollo enrich → account research → sequence.
  Finds companies actively raising capital from accredited investors — the exact audience MoneyShow serves.
  Triggers on: "506c leads", "EDGAR scrape", "run the pipeline", "506c prospects", "new sponsor leads".
---

# SEC 506(c) Sponsor Pipeline

Finds financial firms currently raising capital under Rule 506(c) — they need to reach accredited investors, which is MoneyShow's audience. Converts public SEC filings into enriched, sequenced outbound leads.

## Pipeline Stages

```
EDGAR (free) → Filter → Apollo Enrich → Account Research → Sequence → Smartlead
```

## Quick Start

```bash
# Dry run — see counts without making any API calls
python3 scripts/pipeline.py --dry-run

# Full run — 90 days, high-fit only, up to 100 leads
python3 scripts/pipeline.py

# Full run — 180 days, $1M+ offerings, 200 leads
python3 scripts/pipeline.py --days 180 --min-offering 1000000 --limit 200

# Re-run enrichment on existing EDGAR file
python3 scripts/pipeline.py --skip-scrape

# EDGAR scrape only (no Apollo)
python3 scripts/edgar_scraper.py --days 90 --dry-run
python3 scripts/edgar_scraper.py --days 90
```

## Setup

1. Copy `.env.example` to `.env`
2. Add `APOLLO_API_KEY` (from apollo.io → Settings → API Keys)
3. Add `SMARTLEAD_API_KEY` when ready to deploy sequences

## Scripts

| Script | Purpose |
|---|---|
| `edgar_scraper.py` | Fetches Form D 506(c) filings from SEC EDGAR EFTS API. Caches XML for 7 days. |
| `apollo_enricher.py` | Enriches each company: org lookup → contact find → email match via Apollo REST API |
| `pipeline.py` | Orchestrator: runs all steps in sequence, outputs ready-to-sequence lead list |

## Output Fields (per lead)

| Field | Source |
|---|---|
| `company_name` | EDGAR XML |
| `industry_group` | EDGAR XML (`Pooled Investment Fund`, etc.) |
| `offering_amount` | EDGAR XML |
| `amount_sold` | EDGAR XML |
| `icp_fit` | Derived (`high` / `medium`) |
| `domain` | Apollo |
| `employee_count` | Apollo |
| `contact_first_name` | Apollo |
| `contact_last_name` | Apollo |
| `contact_title` | Apollo |
| `contact_email` | Apollo people_match |
| `edgar_url` | EDGAR filing link |

## ICP Filter Logic

**High-fit industries (passed through by default):**
- Pooled Investment Fund
- Other Banking and Financial Services
- Investing, REITS and Finance
- Other Technology (fintech)

**Skipped by default:**
- Real Estate, Residential, Commercial
- Oil and Gas, Agriculture, Mining
- Retail, Manufacturing, Travel

Override with `--industry "keyword"` to force a specific industry.

## Rate Limits

- SEC EDGAR: 0.15s between XML fetches (well under 10 req/sec limit)
- Apollo REST: 0.3s between calls
- Both are configurable in the scripts

## After the Pipeline

Feed the enriched JSON into the `outbound-engine` skill to write and score sequences:
- Each lead has `company_name`, `contact_first_name`, `contact_title`, `industry_group`, `offering_amount`
- Use offering amount and industry as personalization hooks
- MoneyShow value prop: "You're raising from accredited investors — that's our entire audience"
