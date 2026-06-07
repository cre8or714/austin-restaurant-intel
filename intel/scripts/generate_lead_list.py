"""
Generate a curated lead list from the 45-day TABC and Austin permits pulls.

Output: intel/raw/YYYY-MM-DD_lead-list.md

Rules:
- Only data present in source CSVs (no inferred values)
- Every field has a source anchor
- Confidence labels: CONFIRMED (in source record) / NOT_FOUND
- No contact info — that's human enrichment territory
- Deduplicates by address; marks leads already in existing profiles
"""

import csv
import datetime
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR    = os.path.join(SCRIPT_DIR, "..", "raw")
TODAY      = datetime.date.today().strftime("%Y-%m-%d")

TABC_CSV    = os.path.join(RAW_DIR, f"{TODAY}_tabc-travis.csv")
PERMITS_CSV = os.path.join(RAW_DIR, f"{TODAY}_austin-permits.csv")
OUTPUT_PATH = os.path.join(RAW_DIR, f"{TODAY}_lead-list.md")

TABC_SOURCE_URL    = "https://data.texas.gov/resource/7hf9-qc9f.json"
PERMITS_SOURCE_URL = "https://data.austintexas.gov/resource/3syk-w9eu.json"

# Leads already in the portfolio (by normalized address fragment)
# If a new lead matches one of these, it is flagged as EXISTING
EXISTING_PROFILE_ADDRESSES = {
    "11821 ROCK ROSE AVE UNIT 135",   # lead-06
    "11821 ROCK ROSE AVE",            # lead-06 alt
    "6406 N IH 35 SVRD SB UNIT 1250", # lead-07 Lima Criolla
    "6406 N INTERSTATE HWY 35",       # lead-07 TABC form
    "11301 LAKELINE BLVD BLDG 8",     # lead-08
    "600 CONGRESS AVE STE G260",      # lead-10 Moxies
    "600 CONGRESS AVE UNIT G260",     # lead-10 alt
    "71 RAINEY ST",                   # lead-12 Rainey Tavern
    "12901 N IH 35 SVRD NB BLDG 21",  # lead-13 Raising Cane's
    "3908 AVENUE B BLDG A",           # lead-11-adj area (check)
}

# TABC records to exclude: not standalone restaurants
TABC_EXCLUDE_OWNERS = {
    "OVATIONS FOOD SERVICES OF TEXAS LLC",  # Long Center venue concession
    "CNMK TEXAS PROPERTIES LLC",            # Cinemark movie theater
}

TABC_EXCLUDE_NAMES = {
    "THE LONG CENTER",
    "CINEMARK STONE HILL TOWN CENTER",
}

# Out-of-target-market ZIP codes (Leander, Manor, Pflugerville, etc.)
OUT_OF_MARKET_ZIPS = {"78641", "78653", "78660"}

# Permit descriptions that indicate demolition, residential, or non-restaurant commercial
EXCLUDE_KEYWORDS = [
    "demolition", "residential", "single family", "sfr", "duplex",
    "condo", "condominium", "apartment", "school", "elementary",
    "cafeteria", "convenience store", "gas station", "movie",
    "theater", "cinema", "outdoor kitchen", "residential care",
    "event", "festival", "mobile home", "rpz", "grease interceptor replacement",
    "replace rpz", "sewer line", "tunnel under", "tunnel below",
    "cast iron", "pvc pipe", "flood", "water restoration",
    "repair drain", "backflow", "multifamily", "multi-family",
    "no commercial kitchen", "no food prep",
    "pool equipment", "amenity space", "clubhouse",
    "office tenant improvement", "awning work for restaurant",
    "replace kitchen hood", "kitchen hood", "kitchen and bathroom",
    "kitchen and bath", "remodel kitchen and", "replace kitchen",
    "repair kitchen", "kitchen renovation", "kitchen remodel",
    "kitchen light", "kitchen outlet", "kitchen sink drain",
    "kitchen drain", "kitchen counter", "kitchen cabinets",
    "gourmet kitchen", "office building common areas",
]

# Permit work_class values that signal a real new opening vs. maintenance
QUALIFYING_WORK_CLASSES = {
    "New", "Remodel", "Addition and Remodel", "Shell",
}

# Only these permit_class_mapped values
QUALIFYING_PERMIT_CLASS = {"Commercial"}

# Phrases that strongly confirm a permit is a genuinely NEW restaurant opening.
# At least one of these must appear (case-insensitive) for the permit to qualify.
STRONG_RESTAURANT_PHRASES = [
    "change of use",           # catches "change of use to restaurant", "COU from X to restaurant"
    "change in use",
    "finish out",              # "first generation finish out for restaurant", "finish out for a new restaurant"
    "finish-out",
    "first generation",        # "1st gen shell finish out for restaurant"
    "1st gen",
    "new restaurant",
    "for restaurant",          # "shell for future restaurant", "improvements for a restaurant"
    "future restaurant",
    "new shell space for",
    "restaurant serving",      # "new restaurant serving Mongolian BBQ"
    "convert to restaurant",
    "conversion to restaurant",
    "food establishment",
    "new food service",
    "rebuild of full service commercial restaurant",
    "remodel two bungalows",   # specific 78 Rainey permit
    "interior tenant improvement for a",
    "cocktail bar",            # coffee shop → cocktail bar at 617 Congress
    "first time finish out",   # tenant finish outs
    "tenant infill",
    "billiard",                # billiard halls often have bar/food service
    "connivence store with kitchen",  # 525 W Howard — 5000 SF with kitchen
]


def normalize_address(addr):
    return re.sub(r"\s+", " ", addr.upper().strip())


def is_excluded_description(desc):
    d = desc.lower()
    return any(kw in d for kw in EXCLUDE_KEYWORDS)


def is_restaurant_permit(row):
    desc   = row.get("description", "")
    klass  = row.get("permit_class_mapped", "")
    wc     = row.get("work_class", "")
    status = row.get("status_current", "")

    if status.lower() in ("cancelled - contractor required", "withdrawn", "inactive pending revision"):
        return False
    if klass not in QUALIFYING_PERMIT_CLASS:
        return False
    if wc not in QUALIFYING_WORK_CLASSES:
        return False
    if is_excluded_description(desc):
        return False

    d_lower = desc.lower()

    # Exclude records where a restaurant is converting AWAY (closures, not openings)
    CLOSURE_PATTERNS = [
        "restaurant to retail",
        "restaurant to convenience",
        "change of use restaurant to",
        "change of use from restaurant",
        "from restaurant to",
    ]
    if any(pat in d_lower for pat in CLOSURE_PATTERNS):
        return False

    # Require at least one strong-signal phrase (not just generic keyword match)
    return any(phrase in d_lower for phrase in STRONG_RESTAURANT_PHRASES)


def is_existing_profile(address):
    norm = normalize_address(address)
    for existing in EXISTING_PROFILE_ADDRESSES:
        if normalize_address(existing) in norm or norm in normalize_address(existing):
            return True
    return False


def load_tabc():
    leads = []
    seen_addresses = set()
    with open(TABC_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            zip_code  = row.get("zip", "").strip()[:5]
            address   = normalize_address(row.get("address", ""))
            owner     = row.get("owner", "").upper()
            trade_name = (row.get("trade_name") or "").upper()

            # Skip out-of-market ZIPs
            if zip_code in OUT_OF_MARKET_ZIPS:
                continue
            # Skip known non-restaurant entities
            if owner in TABC_EXCLUDE_OWNERS or trade_name in TABC_EXCLUDE_NAMES:
                continue
            # Deduplicate by address
            if address in seen_addresses:
                continue
            seen_addresses.add(address)

            leads.append({
                "source":       "TABC",
                "trade_name":   row.get("trade_name") or "— not on file",
                "owner_entity": row.get("owner") or "— not on file",
                "license_type": row.get("license_type", ""),
                "status":       row.get("primary_status", ""),
                "address":      row.get("address", ""),
                "city":         row.get("city", ""),
                "zip":          zip_code,
                "issue_date":   row.get("original_issue_date", "")[:10],
                "description":  "",
                "permit_number": "",
                "work_class":   "",
                "existing_profile": is_existing_profile(row.get("address", "")),
            })
    return leads


def load_permits():
    leads = []
    seen_projects = {}  # permit_number_prefix -> row (deduplicate same project with multiple permit types)

    with open(PERMITS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not is_restaurant_permit(row):
                continue

            address = normalize_address(row.get("original_address1", ""))
            # Deduplicate: multiple permit types (BP/MP/EP/PP) for same address+project
            # Use address as the key — keep the first (usually BP or earliest)
            if address in seen_projects:
                continue
            seen_projects[address] = True

            zip_code = row.get("original_zip", "").strip()[:5]
            leads.append({
                "source":       "PERMITS",
                "trade_name":   "— not yet named",
                "owner_entity": "— not on file",
                "license_type": row.get("permit_type_desc", ""),
                "status":       row.get("status_current", ""),
                "address":      row.get("original_address1", ""),
                "city":         "Austin",
                "zip":          zip_code,
                "issue_date":   row.get("issue_date", "")[:10],
                "description":  row.get("description", "").replace("\n", " ").strip(),
                "permit_number": row.get("permit_number", ""),
                "work_class":   row.get("work_class", ""),
                "existing_profile": is_existing_profile(row.get("original_address1", "")),
            })
    return leads


def cross_reference(tabc_leads, permit_leads):
    """Tag TABC leads that also have a permit (same address fragment)."""
    permit_addrs = {normalize_address(p["address"])[:20]: p for p in permit_leads}

    for lead in tabc_leads:
        addr_fragment = normalize_address(lead["address"])[:20]
        if addr_fragment in permit_addrs:
            lead["cross_ref"] = "Also has Austin permit"
        else:
            lead["cross_ref"] = ""

    # Tag permit leads that also have TABC
    tabc_addrs = {normalize_address(t["address"])[:20]: t for t in tabc_leads}
    for lead in permit_leads:
        addr_fragment = normalize_address(lead["address"])[:20]
        if addr_fragment in tabc_addrs:
            t = tabc_addrs[addr_fragment]
            lead["cross_ref"] = f"TABC: {t['trade_name']} ({t['license_type']} {t['issue_date']})"
            lead["trade_name"] = t["trade_name"]
            lead["owner_entity"] = t["owner_entity"]
        else:
            lead["cross_ref"] = ""

    return tabc_leads, permit_leads


def write_md(tabc_leads, permit_leads):
    today_str = datetime.date.today().isoformat()
    cutoff = (datetime.date.today() - datetime.timedelta(days=45)).isoformat()

    new_tabc    = [l for l in tabc_leads    if not l["existing_profile"]]
    new_permits = [l for l in permit_leads  if not l["existing_profile"]]
    existing    = [l for l in tabc_leads + permit_leads if l["existing_profile"]]

    lines = [
        f"# Austin Restaurant Intel — 45-Day Lead List",
        f"",
        f"**Generated:** {today_str}  ·  **Lookback:** {cutoff} → {today_str}  ·  **Sources:** TABC + Austin Open Data Permits",
        f"",
        f"---",
        f"",
        f"## Summary",
        f"",
        f"| Source | Total records | New leads | Already profiled |",
        f"|:---|:---|:---|:---|",
        f"| TABC (data.texas.gov/7hf9-qc9f) | {len(tabc_leads)} | {len(new_tabc)} | {sum(1 for l in tabc_leads if l['existing_profile'])} |",
        f"| Austin Permits (data.austintexas.gov/3syk-w9eu) | {len(permit_leads)} | {len(new_permits)} | {sum(1 for l in permit_leads if l['existing_profile'])} |",
        f"| **Total unique new leads** | | **{len(new_tabc) + len(new_permits)}** | |",
        f"",
        f"> **Anti-hallucination note:** All values below are sourced verbatim from public records. Fields without a record value are marked `— not on file`. No contact information, revenue estimates, or concept descriptions have been inferred.",
        f"",
        f"---",
        f"",
        f"## Part 1 — TABC New Licenses (New, Not Yet Profiled)",
        f"",
        f"Source: `{TABC_SOURCE_URL}` · Raw file: `raw/{TODAY}_tabc-travis.csv`",
        f"",
    ]

    for i, lead in enumerate(new_tabc, 1):
        cross = f" *(also has Austin permit)*" if lead.get("cross_ref") else ""
        lines += [
            f"### T{i}. {lead['trade_name']}{cross}",
            f"",
            f"| Field | Value | Confidence | Source |",
            f"|:---|:---|:---|:---|",
            f"| Trade name | {lead['trade_name']} | CONFIRMED | TABC record |",
            f"| Owner entity | {lead['owner_entity']} | CONFIRMED | TABC record |",
            f"| License type | {lead['license_type']} | CONFIRMED | TABC record |",
            f"| Status | {lead['status']} | CONFIRMED | TABC record |",
            f"| Address | {lead['address']} | CONFIRMED | TABC record |",
            f"| City / ZIP | {lead['city']} {lead['zip']} | CONFIRMED | TABC record |",
            f"| License issued | {lead['issue_date']} | CONFIRMED | TABC record |",
            f"| Concept type | — not on file | NOT_FOUND | Human research needed |",
            f"| Decision maker | — not on file | NOT_FOUND | Human research needed |",
            f"",
        ]

    lines += [
        f"---",
        f"",
        f"## Part 2 — Austin Permit New Openings (New, Not Yet Profiled)",
        f"",
        f"Source: `{PERMITS_SOURCE_URL}` · Raw file: `raw/{TODAY}_austin-permits.csv`",
        f"Filter: Commercial class · work_class in (New, Remodel, Addition and Remodel, Shell) · restaurant keywords in description",
        f"",
    ]

    for i, lead in enumerate(new_permits, 1):
        tabc_note = f" *(TABC cross-ref: {lead['cross_ref']})*" if lead.get("cross_ref") else ""
        concept = lead['description'][:120] + "…" if len(lead['description']) > 120 else lead['description']
        lines += [
            f"### P{i}. {lead['address']}{tabc_note}",
            f"",
            f"| Field | Value | Confidence | Source |",
            f"|:---|:---|:---|:---|",
            f"| Address | {lead['address']} | CONFIRMED | Permit record |",
            f"| ZIP | {lead['zip']} | CONFIRMED | Permit record |",
            f"| Permit # | {lead['permit_number']} | CONFIRMED | Permit record |",
            f"| Permit type | {lead['license_type']} | CONFIRMED | Permit record |",
            f"| Work class | {lead['work_class']} | CONFIRMED | Permit record |",
            f"| Status | {lead['status']} | CONFIRMED | Permit record |",
            f"| Issued | {lead['issue_date']} | CONFIRMED | Permit record |",
            f"| Description | {concept} | CONFIRMED | Permit record |",
            f"| Trade name | {lead['trade_name']} | NOT_FOUND | Human research needed |",
            f"| Owner / operator | {lead['owner_entity']} | NOT_FOUND | Human research needed |",
            f"| Decision maker | — not on file | NOT_FOUND | Human research needed |",
            f"",
        ]

    if existing:
        lines += [
            f"---",
            f"",
            f"## Existing Profiles — Appeared in This Pull",
            f"",
            f"These addresses were found in the 45-day window but are already in the lead portfolio:",
            f"",
        ]
        for lead in existing:
            lines.append(f"- **{lead['address']}** ({lead['source']}) — already profiled")
        lines.append("")

    lines += [
        f"---",
        f"",
        f"## Enrichment Queue",
        f"",
        f"Next steps per the enrichment-playbook.md:",
        f"",
        f"1. **TABC leads (T1–T{len(new_tabc)}):** Run `enrich_lead.py` per address → gets TX Comptroller sales tax + franchise records",
        f"2. **Permit-only leads (P1–P{len(new_permits)}):** Run `enrich_lead.py` → checks if TABC license exists at address",
        f"3. **Human research (Steps 4–5):** Decision maker, contact info, concept type, social media",
        f"4. **Build profile (Step 5):** Only after DM is confirmed",
        f"5. **Verify (Step 6):** `verify_profile.py --all` before pitching",
        f"",
        f"Priority order (highest value):",
        f"- Leads with both TABC + permit cross-reference (operator identity confirmed + build in progress)",
        f"- New construction permits (ground-up builds = largest investment = most motivated buyer)",
        f"- TABC leads with no existing Austin permit (pre-permit stage — earliest possible signal)",
        f"",
        f"---",
        f"",
        f"*Austin Restaurant Intel · generate_lead_list.py · {today_str}*",
    ]

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return OUTPUT_PATH


def main():
    print(f"Reading {TABC_CSV}")
    tabc_leads = load_tabc()
    print(f"  {len(tabc_leads)} TABC leads after filtering")

    print(f"Reading {PERMITS_CSV}")
    permit_leads = load_permits()
    print(f"  {len(permit_leads)} permit leads after filtering")

    tabc_leads, permit_leads = cross_reference(tabc_leads, permit_leads)

    path = write_md(tabc_leads, permit_leads)
    print(f"\nLead list written to: {path}")

    new_t = sum(1 for l in tabc_leads if not l["existing_profile"])
    new_p = sum(1 for l in permit_leads if not l["existing_profile"])
    print(f"  {new_t} new TABC leads  |  {new_p} new permit leads  |  {new_t + new_p} total new leads")


if __name__ == "__main__":
    main()
