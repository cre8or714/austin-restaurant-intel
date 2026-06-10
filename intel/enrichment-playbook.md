# Enrichment Playbook

## What this produces
One standardized lead profile per new restaurant opening. Each profile is:
- Consistently structured (same fields every time)
- Confidence-scored per field (CONFIRMED / ESTIMATED / INFERRED / UNVERIFIED / NOT_FOUND)
- Completeness-rated (% of required fields confirmed)
- Pitch-ready at >= 60% completeness with DM name confirmed

---

## The Pipeline

### Step 1 — Pull new permit leads
```
python intel/scripts/pull_austin_permits.py
```
Output: `intel/raw/YYYY-MM-DD_austin-permits.csv` (all permits, last 90 days)
Output: `intel/raw/YYYY-MM-DD_austin-new-openings.csv` (filtered: new openings only)

Filters applied: commercial permits only, change-of-use or new construction, restaurant keywords in description, manual noise removal (event listings, closures, residential matches).

---

### Step 2 — Pull TABC new licenses
```
python intel/scripts/pull_tabc_austin.py
```
Output: `intel/raw/YYYY-MM-DD_tabc-travis.csv`

Pulls MB/BQ/BE/BF license types issued in Travis County, last 180 days. Cross-reference against permit addresses to find trade names and owner entities.

---

### Step 3 — Run automated enrichment per lead
```
python intel/scripts/enrich_lead.py --address "ADDRESS" --zip "ZIPCODE" --name "slug"
```

Queries three free government APIs in sequence:
1. **TABC** (data.texas.gov/7hf9-qc9f) — trade name, owner entity, license type, status, issue date
2. **TX Comptroller Sales Tax** (data.texas.gov/jrea-zgmq) — outlet name, taxpayer entity, NAICS code, permit date. Filters to NAICS 722xxx (food services) in Python.
3. **TX Comptroller Franchise Tax** (data.texas.gov/9cir-efmm) — entity type (LLC/LP/Corp), registered city, formation date

Output: basic profile in `intel/enriched/`

Interpretation:
- **0 hits across all three** = pre-announcement (most valuable lead type — no one else has it)
- **TABC hit** = operator has applied for or holds a liquor license → trade name + owner entity confirmed
- **Sales Tax hit** = business is operating or registered → entity name confirmed, concept type via NAICS

---

### Step 4 — Web research (decision maker + business intel)
Run a research agent (or manual research) for each lead. Find:
- Decision maker full name, title, bio
- Phone, email, LinkedIn, Instagram (personal + business), Facebook, Twitter/X
- Number of locations (all cities)
- Employee count (LinkedIn company page, ZoomInfo)
- Estimated revenue (ZoomInfo, D&B, Prospeo, or industry benchmark model)

**Revenue benchmarks by concept type:**
| Concept | Revenue per location/yr |
|---------|------------------------|
| Specialty coffee (single daypart) | $300K – $500K |
| Fast casual / QSR | $500K – $1.5M |
| Full-service casual dining | $1.5M – $3.5M |
| Full-service upscale | $2M – $6M |
| Bar / drinking place | $700K – $2.8M |
| Large-format (10K+ SF) | $5M – $20M+ |

**Employee benchmarks by concept type:**
| Concept | Employees per location |
|---------|-----------------------|
| Coffee shop | 2 – 8 |
| Fast casual / QSR | 10 – 25 |
| Full-service casual | 20 – 40 |
| Bar / nightclub | 10 – 30 |
| Large-format | 50 – 150+ |

---

### Step 5 — Build standardized profile
Create a profile data file in `intel/scripts/profiles/lead_XX_name.py` using the schema from `profile_schema.py`, then run:
```
python intel/scripts/build_profile.py profiles/lead_XX_name.py
```
Output: `intel/enriched/YYYY-MM_lead-XX_profile.md`

The builder validates completeness, labels every field with a confidence badge, and flags gaps explicitly.

**Completeness thresholds:**
- **< 60%** = NEEDS ENRICHMENT — do not pitch
- **>= 60% + DM name confirmed** = PITCH-READY
- **>= 87%** = full profile — only gap is typically personal phone or personal email

---

## Checks and Balances

Every data point in a profile carries one of five confidence labels:

| Badge | Label | Meaning |
|-------|-------|---------|
| ✓ | CONFIRMED | Sourced and independently verified |
| ~ | ESTIMATED | Model-based or industry benchmark |
| ~ | INFERRED | Logical deduction from confirmed data (e.g. email pattern from domain) |
| ? | UNVERIFIED | Found in a public record aggregator; not independently confirmed |
| ✗ | NOT_FOUND | Exhausted all available sources; gap acknowledged |

Rules:
- Never present ESTIMATED or INFERRED data to a buyer as confirmed fact
- UNVERIFIED phone numbers: note they come from public records, offer to verify
- An inferred email (e.g. `firstname@domain.com`) must be disclosed as inferred in outreach — "I believe the best email for you is..." not "Your email is..."
- Required fields: `business_name`, `concept_type`, `location_count`, `dm_name`, `dm_phone`, `dm_email`, `dm_linkedin`, `dm_instagram`

### Source anchoring (required for CONFIRMED fields)

Every CONFIRMED value must be traced to the specific URL where it was found.
Use a 3-tuple in the profile dict:

```python
"dm_phone": ("(512) 555-0123", "CONFIRMED", "https://bobwoody.com/contact"),
```

The 3rd element is the direct URL — not a search results page or aggregator.
The bulk `sources` field at the bottom of each profile is a reference list, not
a substitute for per-field anchoring.

---

### Step 5a — Texas SOS SOSDirect lookup (MANDATORY for TABC-confirmed LLC leads)

Any lead with a TABC license tied to a named Texas LLC MUST have a Texas SOS SOSDirect
managing-member lookup completed BEFORE the lead can be placed in the Active tier.

- Go to SOSDirect (apps.sos.state.tx.us/sosda/) — $1 fee per entity search
- Search the exact LLC name from the TABC record
- Record the managing member name(s) and registered agent
- Add the result to the profile under Decision Makers

If the lookup returns no result or the managing member cannot be identified from any
public source, the lead stays in Watch tier until resolved. Do not mark Active and do
not paper over the gap with "Apollo recommended" or "SOS recommended" language —
that offloads the research to the client and violates the no-dig gate.

---

### Step 6 — Verify before marking pitch-ready

Run the fact-checker on every profile before it is used in outreach:

```
python intel/scripts/verify_profile.py --all
```

This checks three things:
1. Every field has a confidence label (no unlabeled 1-tuples)
2. Every CONFIRMED field has a source URL anchored to it
3. (AI mode) Source pages are fetched and Claude checks whether the claimed
   value actually appears in the page content

Output:
- `intel/factcheck/<lead_id>_FACTCHECK.md` — per-profile report and sign-off checklist
- `intel/AUDIT_REPORT.md` — master summary across all profiles

A profile is only pitch-ready when:
- Completeness >= 60% AND dm_name CONFIRMED
- `_FACTCHECK.md` exists AND human sign-off is complete

Without a signed factcheck, treat the profile as NEEDS ENRICHMENT regardless of completeness score.

---

## Profile File Naming

| File type | Convention |
|-----------|------------|
| Raw permit pull | `YYYY-MM-DD_austin-permits.csv` |
| Raw TABC pull | `YYYY-MM-DD_tabc-travis.csv` |
| Filtered new openings | `YYYY-MM-DD_austin-new-openings.csv` |
| Profile data file | `intel/scripts/profiles/lead_XX_name.py` |
| Final profile | `intel/enriched/YYYY-MM_lead-XX_profile.md` |

---

## Completed Profiles (as of 2026-06-05)

| Lead | Business | Completeness | Status |
|------|----------|-------------|--------|
| lead-06 | Rock Rose Unit 135 ("Red Car") | 0% | Pre-announcement — DM unknown |
| lead-05 | Phoebe's Diner (4th location) | 75% | PITCH-READY |
| lead-07 | Lima Criolla / The Linc Unit 1250 | 62% | PITCH-READY |
| lead-09 | Terrible Love (wine bar buildout) | 87% | PITCH-READY |
| lead-11-adj | Roya / Silk Road Hospitality | 87% | PITCH-READY |
| lead-12 | Rainey Tavern | 87% | PITCH-READY |
