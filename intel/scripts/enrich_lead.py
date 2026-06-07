"""
Enrich a restaurant lead from Austin permit data.

Usage:
    python enrich_lead.py --address "11821 ROCK ROSE AVE" --zip "78758" --name "Unit 135"

Sources:
    1. TABC (data.texas.gov) — trade name, owner, license status
    2. OpenCorporates (api.opencorporates.com) — entity registration details
    3. Existing TABC raw pull if available (skips API call if fresh)

Output: intel/enriched/YYYY-MM_<slug>_profile.md
"""

import argparse
import csv
import json
import os
import re
import urllib.request
import urllib.parse
import datetime

TABC_URL = "https://data.texas.gov/resource/7hf9-qc9f.json"
FRANCHISE_URL = "https://data.texas.gov/resource/9cir-efmm.json"
SALES_TAX_URL = "https://data.texas.gov/resource/jrea-zgmq.json"

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "enriched")
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "raw")


# ---------------------------------------------------------------------------
# TABC lookup
# ---------------------------------------------------------------------------

def tabc_lookup(address, zip_code, app_token=None):
    """Search TABC for licenses near the given address/zip."""
    # Normalize: strip unit numbers for matching, use first word of street
    street_parts = address.upper().split()
    # Build a partial match — use street number + first street name word
    partial = " ".join(street_parts[:2]) if len(street_parts) >= 2 else street_parts[0]

    # Clean zip (TABC stores as 9-digit with no hyphen)
    zip_prefix = zip_code.replace("-", "")[:5]

    where = (
        f"zip LIKE '{zip_prefix}%' "
        f"AND upper(address) LIKE '%{partial}%'"
    )
    params = {
        "$where": where,
        "$limit": "20",
        "$select": (
            "trade_name,owner,license_type,primary_status,"
            "address,city,zip,original_issue_date,expiration_date,tier"
        ),
    }

    url = TABC_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    if app_token:
        req.add_header("X-App-Token", app_token)

    try:
        with urllib.request.urlopen(req) as r:
            results = json.loads(r.read().decode())
        return results
    except Exception as e:
        print(f"  TABC lookup error: {e}")
        return []


# ---------------------------------------------------------------------------
# Texas Comptroller lookups
# ---------------------------------------------------------------------------

def _comptroller_fetch(base_url, where, select, limit=5):
    params = {"$where": where, "$select": select, "$limit": str(limit)}
    url = base_url + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  Comptroller lookup error: {e}")
        return []


def franchise_lookup(owner_name):
    """Search Texas Comptroller franchise taxpayers by name (exact phrase match)."""
    # Use the full name for matching to avoid false positives
    name_upper = owner_name.upper()
    where = f"upper(taxpayer_name) LIKE '%{name_upper}%'"
    select = "taxpayer_name,taxpayer_address,taxpayer_city,taxpayer_state,taxpayer_zip,taxpayer_organizational_type,responsibility_beginning_date"
    return _comptroller_fetch(FRANCHISE_URL, where, select)


def sales_tax_lookup(address, zip_code):
    """Search Texas Comptroller sales tax permits by outlet address, filter food-service in Python."""
    street_parts = address.upper().split()
    partial = " ".join(street_parts[:2]) if len(street_parts) >= 2 else street_parts[0]
    zip_prefix = zip_code[:5]
    where = (
        f"upper(outlet_address) LIKE '%{partial}%' "
        f"AND outlet_zip_code LIKE '{zip_prefix}%'"
    )
    select = "outlet_name,taxpayer_name,outlet_address,outlet_city,outlet_zip_code,outlet_naics_code,outlet_permit_issue_date"
    all_records = _comptroller_fetch(SALES_TAX_URL, where, select, limit=50)
    # Filter to food/beverage NAICS codes in Python (722xxx = food services)
    return [r for r in all_records if str(r.get("outlet_naics_code", "")).startswith("722")]


# ---------------------------------------------------------------------------
# Profile writer
# ---------------------------------------------------------------------------

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:40]


def write_profile(address, zip_code, label, tabc_records, franchise_records, sales_tax_records, output_dir):
    today = datetime.date.today()
    month = today.strftime("%Y-%m")
    slug = slugify(label or address)
    filename = f"{month}_{slug}_profile.md"
    path = os.path.join(output_dir, filename)

    lines = [
        f"# Lead Profile: {label or address}",
        f"",
        f"**Profile date:** {today}",
        f"**Address:** {address}, Austin TX {zip_code}",
        f"",
        f"---",
        f"",
        f"## TABC License Records",
        f"",
    ]

    if tabc_records:
        for r in tabc_records:
            lines += [
                f"### {r.get('trade_name') or '[Name not filed]'}",
                f"",
                f"| Field | Value |",
                f"|-------|-------|",
                f"| Owner | {r.get('owner', '—')} |",
                f"| License type | {r.get('license_type', '—')} |",
                f"| Status | {r.get('primary_status', '—')} |",
                f"| Issued | {str(r.get('original_issue_date', ''))[:10]} |",
                f"| Expires | {str(r.get('expiration_date', ''))[:10]} |",
                f"| Address on file | {r.get('address', '—')}, {r.get('city', '')} {r.get('zip', '')} |",
                f"",
            ]
    else:
        lines += [
            f"No TABC records found at this address/zip. Either:",
            f"- License not yet applied for (pre-announcement lead)",
            f"- Application filed under a different address format",
            f"",
            f"**Action:** Search manually at apps.tabc.texas.gov/publicinquiry",
            f"",
        ]

    lines += ["---", "", "## Texas Comptroller — Sales Tax Permits (Food Service)", ""]

    if sales_tax_records:
        for r in sales_tax_records:
            lines += [
                f"- **{r.get('outlet_name', '—')}** / taxpayer: {r.get('taxpayer_name', '—')}",
                f"  - Address: {r.get('outlet_address', '—')}, {r.get('outlet_city', '')} {r.get('outlet_zip_code', '')}",
                f"  - NAICS: {r.get('outlet_naics_code', '—')} | Permit issued: {str(r.get('outlet_permit_issue_date', ''))[:10]}",
                f"",
            ]
    else:
        lines += ["No food-service sales tax permit found at this address (may not be filed yet).", ""]

    lines += ["---", "", "## Texas Comptroller — Franchise Taxpayers", ""]

    if franchise_records:
        for r in franchise_records[:3]:
            org_type = {"CI": "Corporation", "LP": "Limited Partnership", "LI": "LLC"}.get(
                r.get("taxpayer_organizational_type", ""), r.get("taxpayer_organizational_type", "—")
            )
            lines += [
                f"- **{r.get('taxpayer_name', '—')}** ({org_type})",
                f"  - Address: {r.get('taxpayer_address', '—')}, {r.get('taxpayer_city', '')} {r.get('taxpayer_zip', '')}",
                f"  - Active since: {str(r.get('responsibility_beginning_date', ''))[:10]}",
                f"",
            ]
    else:
        lines += ["No franchise taxpayer match found.", ""]

    lines += [
        "---",
        "",
        "## Enrichment Gaps",
        "",
        "- [ ] Operator/owner contact info (phone, email, LinkedIn)",
        "- [ ] Concept type confirmed",
        "- [ ] Estimated open date",
        "- [ ] Website / social media",
        "- [ ] Press coverage",
        "",
        "---",
        f"",
        f"*Generated {today} by enrich_lead.py*",
    ]

    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Enrich a restaurant lead")
    parser.add_argument("--address", required=True, help="Street address (e.g. '11821 ROCK ROSE AVE')")
    parser.add_argument("--zip", required=True, help="ZIP code (e.g. '78758')")
    parser.add_argument("--name", default="", help="Optional label for the profile filename")
    args = parser.parse_args()

    app_token = os.environ.get("TEXAS_APP_TOKEN")

    print(f"\n=== Enriching: {args.address}, {args.zip} ===\n")

    print("1. TABC lookup...")
    tabc_records = tabc_lookup(args.address, args.zip, app_token)
    print(f"   Found {len(tabc_records)} TABC record(s)")
    for r in tabc_records:
        print(f"   -> {r.get('trade_name') or '[no name]'} | {r.get('owner')} | {r.get('primary_status')}")

    print("\n2. Texas Comptroller — Sales Tax Permits (food service at address)...")
    sales_tax_records = sales_tax_lookup(args.address, args.zip)
    print(f"   Found {len(sales_tax_records)} record(s)")
    for r in sales_tax_records:
        print(f"   -> {r.get('outlet_name')} | {r.get('taxpayer_name')} | NAICS {r.get('outlet_naics_code')}")

    franchise_records = []
    owners = list({r.get("owner") or r.get("trade_name") for r in tabc_records if r.get("owner") or r.get("trade_name")})
    if owners:
        print(f"\n3. Texas Comptroller — Franchise Taxpayers (by owner name)...")
        for name in owners[:2]:
            results = franchise_lookup(name)
            franchise_records.extend(results)
            print(f"   '{name}': {len(results)} match(es)")
            for r in results[:2]:
                print(f"   -> {r.get('taxpayer_name')} | {r.get('taxpayer_organizational_type')} | {r.get('taxpayer_city')}")
    else:
        print("\n3. Skipping franchise lookup — no TABC owner name found")

    print(f"\n4. Writing profile...")
    label = args.name or args.address
    path = write_profile(args.address, args.zip, label, tabc_records, franchise_records, sales_tax_records, OUTPUT_DIR)
    print(f"   Saved: {path}")


if __name__ == "__main__":
    main()
