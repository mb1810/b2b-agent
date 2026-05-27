# CLAUDE.md — MoneyShow B2B GTM Agent

This repo is a fork of Single Grain's `ai-marketing-skills`. It has been **personalized
for Michael Berger's MoneyShow B2B work**. The skills are kept native — this file adds
the operating context so every skill runs against the right company, stack, and brand.

> Only **verified** facts are recorded here. Anything not yet confirmed is marked
> `[CONFIRM]` — do not invent values for those.

---

## Who this is for

- **User:** Michael Berger — CMO, MoneyShow (`mberger@moneyshow.com`).
- **Company:** MoneyShow — 45+ years connecting serious retail and institutional
  investors and traders with top market strategists, economists, and money managers. Annual
  flagship conference plus year-round digital/virtual events.
- **The B2B motion this agent serves:** selling **sponsorships and exhibitor packages
  to financial firms** (asset managers, brokers, fintech, newsletters/publishers) for
  MoneyShow's live and virtual investor conferences. This is the sponsor/exhibitor side
  — not attendee registration (that is a separate, B2C-leaning motion).

## Working style (apply by default)

- Decisive. Michael says "yes" or a number to proceed. **Do not ask permission for
  obvious next steps** — state assumptions and continue.
- Don't over-explain options. Recommend, then act.
- Flag genuine forks (data loss, irreversible, or an unverified business fact) — those
  are worth a pause.

---

## Verified tool stack (and the one thing that matters most)

| Job | Tool Michael actually uses | Notes |
|---|---|---|
| CRM | **Pipedrive (Ultimate)** | Fully migrated from legacy SQL "CaerusProject" (~465K records: 19K orgs / 50K people / 55K deals). Pipelines: **Live Events** (id `2`), **Virtual Events** (id `3`). 71 products in catalog. Custom fields for Apollo, UTM, Fireflies already exist. |
| Enrichment / lead source | **Apollo.io** | Apollo **MCP is connected** in this environment — use it directly. A standalone Apollo **API key** for the Python scripts is `[CONFIRM]`. Either way, Apollo is the people/company search engine for every "find/enrich leads" step. |
| Call intelligence | **Fireflies** | Meeting summaries land on the Pipedrive **Person** record. Transcripts are the input for call-analysis skills. |
| Email — B2B outbound / sending | **Smartlead** | Primary cold-outbound platform for B2B sponsor sequences (campaigns, warmup, sending accounts, API). This is where outbound sequences send from — **not** Gmail, not Instantly. |
| Email — B2C lifecycle | **Customer.io** | B2C only: attendee drip, subscriber sequences, lifecycle automation. Do not use for B2B sponsor outreach. |
| Work email client | **Outlook** | `mberger@moneyshow.com`. All business email — sponsor correspondence, internal reports — lives in Outlook. Gmail is personal only. |
| Misc | Slack, Notion, Gamma, Canva | Connected via MCP. |

> ⚠️ **Read before using any sales/outbound skill:** the upstream skills are written for
> **HubSpot (CRM)** and **Instantly (cold email)**. Michael uses **Pipedrive + Apollo +
> Smartlead (B2B) / Customer.io (B2C)**. So:
> - Treat every `HUBSPOT_API_KEY` path as "**point at Pipedrive instead**."
> - Treat every `INSTANTLY_API_KEY` path as "**send via Smartlead (B2B outbound) or
>   Customer.io (B2C drip) instead**." Smartlead is the same class of tool as Instantly
>   (cold-email campaigns + warmup + API), so this is a near 1:1 swap, not a rewrite.
> - `APOLLO_API_KEY` / `LEAD_SOURCE_API_URL=https://api.apollo.io/...` paths target the
>   right vendor (Apollo is in the stack) — but confirm a standalone API key exists, or
>   drive Apollo through its connected MCP instead.

## Secrets — do not commit

- This repo has a **public GitHub remote** (`github.com/mb1810/b2b-agent`).
- **Never** write the Pipedrive API token, Apollo key, or any credential into a tracked
  file. The Pipedrive token lives in the separate PipeDrive migration project's env;
  reference it as `$PIPEDRIVE_API_TOKEN`, never as a literal.
- Each skill reads keys from its own `.env` (gitignored). Use those.
- Before any commit: `python3 security/sanitizer.py --scan --dir . --recursive`.

---

## Brand & copy rules (hard constraints — apply during generation, not as a post-edit)

These are verified from Michael's existing `/event-gtm` command and apply to **all**
copy, email, landing, and deck output.

**Voice:** authoritative, precise, data-backed. MoneyShow is long-tenured and trusted by
serious investors — quiet confidence, not retail hype.

**Copy:**
- No hype adjectives ("amazing", "game-changing"). Replace with a specific claim
  (e.g. "strategists managing $X in assets", "ranked #1 by [outlet]").
- **No exclamation points in subject lines.** Subject lines: 7 words, specific, benefit-first.
- Preview text: 40–50 chars, extends the subject (no repetition).
- All CTAs are action-verb led ("Register Now", "Reserve Your Booth") — never "Click Here"
  or "Learn More".
- Speaker/credential lines lead with a measurable credential (AUM, track record, ranking),
  not personality.
- Dates spelled out in full ("December 4, 2025", not "12/4").
- Reference MoneyShow's 45+ year longevity where it earns trust.
- Skip TikTok / Reels / influencer formats — substitute LinkedIn + email.
- Show codes (LVAC26, SFAC26, etc.) are internal shorthand only. All external copy uses
  full show names (e.g. "MoneyShow Masters Symposium Las Vegas 2026").

**Design specs (for handoff):**
- Primary button: `background: #ff5900; color: #ffffff; border-radius: 6px`.
- Palette: `#000710` (dark), `#ff5900` (accent), `#ffffff` (bg), `#f3f3f7` (sections).
  No additional accent colors.
- Type: **Flecha** for dominant headlines (36px, weight 500); **Inter** for all body,
  nav, secondary headings (14–24px).
- Radii: cards 12px; default elements 6px; inputs 0px.

---

## Skill routing — best skills to start with

Ranked by **value to the sponsor/exhibitor motion × how much already works with
Michael's stack**. Start at the top.

### Tier 1 — Start now (runs on tools already in hand)

1. **`sales-playbook`** — value-based pricing, pre-call briefings, tiered packaging,
   call scoring. Works **without API keys** (built-in stubs); `call_analyzer.py` uses an
   Anthropic key. Best fit for packaging sponsorship tiers and prepping sponsor calls.
   - `python3 sales-playbook/value_pricing_packager.py --target-monthly <$> --services "<sponsor assets>"`
   - `python3 sales-playbook/value_pricing_briefing.py --domain <sponsor-domain.com>`
   - `python3 sales-playbook/call_analyzer.py --transcript <fireflies-export.txt>`

2. **`revenue-intelligence` → `gong_insight_pipeline.py`** — extracts objections, buying
   signals, competitive mentions, and follow-ups from **plain transcript files** (no Gong
   needed). Feed it Fireflies call exports.
   - `python3 revenue-intelligence/gong_insight_pipeline.py --dir ./transcripts/ --follow-ups`

3. **`lead-dossier`** — research + cascade-enrich a target sponsor account before outreach.
   Apollo is the lead source (use the Apollo MCP, or set `LEAD_SOURCE_API_KEY` if a
   standalone key exists). The research/dossier output is usable standalone now. Caveat:
   the CRM-enrich step (`lead-enricher.py`) uses **HubSpot's API shape**
   (`/crm/v3/objects/...`), so repointing `CRM_BASE_URL` alone won't reach Pipedrive —
   that step needs a Pipedrive adapter, or just skip it and use the dossier output directly.
   - `python3 lead-dossier/scripts/account-researcher.py --domain <sponsor-domain.com>`

4. **`content-ops` (expert-panel)** — quality gate for any sponsor email / landing copy
   against the brand rules above. Needs an Anthropic key. Pairs with the `/event-gtm` command.

### Tier 2 — High value, needs one swap

5. **`sales-pipeline` → `deal_resurrector.py`** — revive **closed-lost** sponsors (scores
   them by time-decay + POC expansion + champion tracking). You have a large migrated deal
   base in Pipedrive (~55K deals; 47,940 flagged "auto-created" still awaiting triage) — a
   real dormant pool to mine once closed-lost stages are identified. **Fully HubSpot-bound**
   (`HubSpotClient`, requires `HUBSPOT_API_KEY`, `CLOSED_LOST_STAGES` map) — needs a
   Pipedrive adapter. This is the single highest-ROI integration task in the repo.
   `trigger_prospector.py` (new-hire/funding signals) needs a Brave Search key.

6. **`outbound-engine`** — design brand-correct cold sponsor sequences; Apollo handles
   sourcing (ready). Sending assumes Instantly — swap to **Smartlead** (same class:
   cold-email campaigns, warmup, sending accounts, API), so the send/enroll step is a
   near 1:1 API swap, not a rewrite. Customer.io stays for B2C drip only.

### Tier 3 — Later / standalone

- **`seo-ops`** — MoneyShow.com keyword + competitor-gap work. Needs GSC OAuth + Ahrefs.
  More attendee/content than sponsor sales.
- **`finance-ops`** — CFO briefings from QuickBooks exports, no keys. Internal finance,
  not core to the sponsor motion.
- **`growth-engine`, `content-ops` production, video/podcast/clone pipelines** —
  marketing/content; peripheral to the B2B sponsor motion. Useful when promoting a
  specific event (see the `/event-gtm` command).

---

## Open items to confirm (don't fabricate these)

- `[CONFIRM]` Sponsor/exhibitor **ICP**: target titles, firm types, AUM/size floor, anti-ICP.
- `[CONFIRM]` Sponsorship **package tiers and price points** (for `value_pricing_packager`).
- `[CONFIRM]` Whether a standalone **Apollo API key** exists for the Python scripts (the Apollo MCP is already connected).
- `[CONFIRM]` Which **events** are the current GTM priority.
