"""
Batch government API enrichment for the 45-day lead list.

Runs enrich_lead.py functions against TABC + TX Comptroller for every
new lead in the current lead list. Saves output to intel/enriched/.

Sources (government APIs only — no LLM, no commercial data):
  TABC          data.texas.gov/7hf9-qc9f
  Sales Tax     data.texas.gov/jrea-zgmq
  Franchise Tax data.texas.gov/9cir-efmm

Usage:
    python batch_enrich.py
"""

import csv
import datetime
import os
import sys
import time

# Pull in enrich_lead functions directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enrich_lead as el

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR     = os.path.join(SCRIPT_DIR, "..", "raw")
TODAY       = datetime.date.today().strftime("%Y-%m-%d")

TABC_CSV    = os.path.join(RAW_DIR, f"{TODAY}_tabc-travis.csv")
PERMITS_CSV = os.path.join(RAW_DIR, f"{TODAY}_austin-permits.csv")

APP_TOKEN = os.environ.get("TEXAS_APP_TOKEN")

# Addresses already in the portfolio — skip enrichment
EXISTING_ADDRESSES = {
    "11821 ROCK ROSE AVE UNIT 135",
    "11821 ROCK ROSE AVE",
    "6406 N IH 35 SVRD SB UNIT 1250",
    "6406 N INTERSTATE HWY 35",
    "11301 LAKELINE BLVD BLDG 8",
    "600 CONGRESS AVE STE G260",
    "600 CONGRESS AVE UNIT G260",
    "71 RAINEY ST",
    "12901 N IH 35 SVRD NB BLDG 21",
    "3908 AVENUE B BLDG A",
}

OUT_OF_MARKET_ZIPS = {"78641", "78653", "78660"}

TABC_EXCLUDE_OWNERS = {"OVATIONS FOOD SERVICES OF TEXAS LLC", "CNMK TEXAS PROPERTIES LLC"}
TABC_EXCLUDE_NAMES  = {"THE LONG CENTER", "CINEMARK STONE HILL TOWN CENTER"}

# Permit strong-signal phrases (must match at least one)
STRONG_PHRASES = [
    "change of use", "change in use", "finish out", "finish-out",
    "first generation", "1st gen", "new restaurant", "for restaurant",
    "future restaurant", "new shell space for", "restaurant serving",
    "convert to restaurant", "conversion to restaurant", "food establishment",
    "new food service", "rebuild of full service commercial restaurant",
    "remodel two bungalows", "interior tenant improvement for a",
    "cocktail bar", "first time finish out", "tenant infill",
    "billiard", "connivence store with kitchen",
]

EXCLUDE_KW = [
    "demolition", "residential", "single family", "sfr", "duplex",
    "condo", "condominium", "apartment", "school", "elementary",
    "outdoor kitchen", "event", "festival", "mobile home",
    "multifamily", "multi-family", "no commercial kitchen", "no food prep",
    "pool equipment", "amenity space", "clubhouse",
    "office tenant improvement", "awning work for restaurant",
    "replace kitchen", "repair kitchen", "kitchen hood",
    "kitchen and bathroom", "kitchen and bath",
]

CLOSURE_PATTERNS = [
    "restaurant to retail", "restaurant to convenience",
    "change of use restaurant to", "change of use from restaurant", "from restaurant to",
]


def is_existing(address):
    norm = address.upper().strip()
    return any(e in norm or norm in e for e in EXISTING_ADDRESSES)


def is_qualifying_permit(row):
    desc   = (row.get("description") or "").lower()
    klass  = row.get("permit_class_mapped", "")
    wc     = row.get("work_class", "")
    status = (row.get("status_current") or "").lower()
    if status in ("cancelled - contractor required", "withdrawn", "inactive pending revision"):
        return False
    if klass != "Commercial":
        return False
    if wc not in ("New", "Remodel", "Addition and Remodel", "Shell"):
        return False
    if any(k in desc for k in EXCLUDE_KW):
        return False
    if any(p in desc for p in CLOSURE_PATTERNS):
        return False
    return any(p in desc for p in STRONG_PHRASES)


def load_leads():
    """Return list of (address, zip, label) dicts for all new leads."""
    leads = []
    seen  = set()

    # TABC leads
    with open(TABC_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr  = (row.get("address") or "").strip()
            zip_c = (row.get("zip") or "")[:5]
            owner = (row.get("owner") or "").upper()
            name  = (row.get("trade_name") or "").upper()

            if zip_c in OUT_OF_MARKET_ZIPS:
                continue
            if owner in TABC_EXCLUDE_OWNERS or name in TABC_EXCLUDE_NAMES:
                continue
            if is_existing(addr):
                continue

            key = addr.upper()
            if key in seen:
                continue
            seen.add(key)

            leads.append({
                "address": addr,
                "zip":     zip_c,
                "label":   row.get("trade_name") or addr,
                "source":  "TABC",
            })

    # Permit leads
    permit_seen = set()
    with open(PERMITS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not is_qualifying_permit(row):
                continue
            addr  = (row.get("original_address1") or "").strip()
            zip_c = (row.get("original_zip") or "")[:5]
            if is_existing(addr):
                continue
            key = addr.upper()
            if key in permit_seen or key in seen:
                continue
            permit_seen.add(key)
            leads.append({
                "address": addr,
                "zip":     zip_c,
                "label":   addr,
                "source":  "PERMIT",
                "desc":    (row.get("description") or "").replace("\n", " ")[:80],
            })

    return leads


def enrich_one(lead, idx, total):
    addr  = lead["address"]
    zip_c = lead["zip"]
    label = lead["label"]
    print(f"\n[{idx}/{total}] {label} | {addr} {zip_c}")

    tabc = el.tabc_lookup(addr, zip_c, APP_TOKEN)
    print(f"  TABC: {len(tabc)} record(s)")
    for r in tabc[:2]:
        print(f"    {r.get('trade_name') or '[no name]'} | {r.get('owner')} | {r.get('primary_status')}")

    sales = el.sales_tax_lookup(addr, zip_c)
    print(f"  Sales Tax: {len(sales)} food-service record(s)")

    franchise = []
    owners = list({r.get("owner") or r.get("trade_name")
                   for r in tabc if r.get("owner") or r.get("trade_name")})
    for o in owners[:2]:
        res = el.franchise_lookup(o)
        franchise.extend(res)
        if res:
            print(f"  Franchise: '{o}' → {len(res)} match(es)")

    path = el.write_profile(addr, zip_c, label, tabc, franchise, sales, el.OUTPUT_DIR)
    print(f"  Saved: {os.path.basename(path)}")
    return path


def main():
    leads = load_leads()
    print(f"Loaded {len(leads)} new leads for enrichment")
    print(f"Output dir: {el.OUTPUT_DIR}\n")

    paths = []
    for i, lead in enumerate(leads, 1):
        try:
            path = enrich_one(lead, i, len(leads))
            paths.append(path)
            time.sleep(0.3)  # gentle rate limiting
        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\n=== Done: {len(paths)}/{len(leads)} enriched ===")
    print(f"Output: {el.OUTPUT_DIR}")


if __name__ == "__main__":
    main()
