#!/usr/bin/env python3
"""
apollo_vendor_contacts.py
=========================
Searches Apollo.io for decision-makers at every company in the Austin
Restaurant Intel target-vendor list. No credits consumed for search —
results show only whether email/phone data EXISTS.

Pass --auto-enrich to immediately enrich every has_email=True match with
actual contact data (email address, full name, LinkedIn, phone if known).
Enrichment DOES consume Apollo credits — one credit per person enriched.
The combined output CSV contains both search metadata and enriched fields.

Usage:
  export APOLLO_API_KEY="your_master_key"

  # Search all 42 vendors, write CSV (no credits)
  python apollo_vendor_contacts.py --output vendor_contacts.csv

  # Search + enrich has_email matches in one pass (consumes credits)
  python apollo_vendor_contacts.py --auto-enrich --output vendor_contacts.csv

  # Tier 1 only
  python apollo_vendor_contacts.py --tier 1 --auto-enrich --output tier1.csv

  # Only gap companies (no known contact) + enrich
  python apollo_vendor_contacts.py --gaps-only --auto-enrich --output gaps.csv

  # Single category
  python apollo_vendor_contacts.py --category pest_control --output pest.csv

  # Verbose: show progress per company
  python apollo_vendor_contacts.py --output all.csv -v
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

try:
    import requests
except ImportError:
    sys.exit("This script requires 'requests'. Install with: pip install requests")

# Import enrichment client from sibling script (same directory).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from apollo_people_enrichment import ApolloEnrichClient, EnrichParams
    _ENRICHMENT_AVAILABLE = True
except ImportError:
    _ENRICHMENT_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Apollo constants
# --------------------------------------------------------------------------- #

BASE_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
HOURLY_CALL_LIMIT = 600
MAX_PER_PAGE = 100
MAX_PER_COMPANY = 10   # cap results per vendor — we need decision-makers, not a roster

# Seniority levels that indicate a decision-maker.
DECISION_SENIORITIES = [
    "owner", "founder", "c_suite", "partner", "vp", "head", "director", "manager",
]

logger = logging.getLogger("apollo_vendors")


# --------------------------------------------------------------------------- #
# Vendor target list  (derived from sales/target-vendors.md 2026-06-05)
# --------------------------------------------------------------------------- #
# Fields:
#   tier          — 1 (score ≥16) or 2 (score 11–15)
#   category      — slug matching the category scorecard
#   company       — exact company name to query Apollo with
#   known_contact — name already in the vendor list, or None if gap
#   city          — used to narrow Apollo results for small local companies
# --------------------------------------------------------------------------- #

VENDOR_TARGETS: list[dict[str, Any]] = [
    # ---- Food & Beverage Distributors (Tier 1, score 19) ----
    {"tier": 1, "category": "food_distributor",   "company": "Hardie's Fresh Foods",      "known_contact": "Greg Rowe",           "city": "Austin, Texas"},
    {"tier": 1, "category": "food_distributor",   "company": "Labatt Food Service",        "known_contact": "Kara Bills",          "city": "Austin, Texas"},
    {"tier": 1, "category": "food_distributor",   "company": "Ben E. Keith Foods",         "known_contact": None,                  "city": "Austin, Texas"},
    {"tier": 1, "category": "food_distributor",   "company": "Colinas Foods",              "known_contact": "Emilio H. Salazar",   "city": "Round Rock, Texas"},
    {"tier": 2, "category": "food_distributor",   "company": "River City Produce",         "known_contact": "John Gonzalez",       "city": "San Antonio, Texas"},
    {"tier": 2, "category": "food_distributor",   "company": "Scarmardo Foodservice",      "known_contact": None,                  "city": "Bryan, Texas"},

    # ---- Commercial Insurance (Tier 1, score 18) ----
    {"tier": 1, "category": "insurance",          "company": "GrayStone Insurance Group",  "known_contact": "Chad Kramer",         "city": "Austin, Texas"},
    {"tier": 1, "category": "insurance",          "company": "Britton & Britton Insurance","known_contact": "Riley Britton",       "city": "Austin, Texas"},
    {"tier": 1, "category": "insurance",          "company": "Watkins Insurance Group",    "known_contact": "Chris Scott",         "city": "Austin, Texas"},
    {"tier": 1, "category": "insurance",          "company": "Heaton Bennett Insurance",   "known_contact": "Mike Bando",          "city": "Austin, Texas"},
    {"tier": 2, "category": "insurance",          "company": "Food & Bev Insurance Agency","known_contact": "Joe Thomas",          "city": "Sugar Land, Texas"},
    {"tier": 2, "category": "insurance",          "company": "Fortis Insurance Partners",  "known_contact": "Lillian Braunstein",  "city": "Austin, Texas"},

    # ---- Grease Trap & Waste Oil (Tier 1, score 18) ----
    {"tier": 1, "category": "grease_trap",        "company": "ReGrease LLC",               "known_contact": "Clay Kennedy",        "city": "Texas"},
    {"tier": 1, "category": "grease_trap",        "company": "Dolly's Pump & Dump",        "known_contact": "Travis Martin",       "city": "Cedar Creek, Texas"},
    {"tier": 1, "category": "grease_trap",        "company": "All Cen Tex Septic & Vacuum","known_contact": "Rob Negrete",         "city": "Austin, Texas"},
    {"tier": 1, "category": "grease_trap",        "company": "Austin Grease Trap Services","known_contact": None,                  "city": "Austin, Texas"},
    {"tier": 2, "category": "grease_trap",        "company": "CenTex Grease Recovery",     "known_contact": "Thomas Davis",        "city": "Jarrell, Texas"},
    {"tier": 1, "category": "grease_trap",        "company": "SouthWaste Disposal",        "known_contact": "Richard Hernandez",   "city": "Austin, Texas"},

    # ---- Liquor & Beverage Distributors (Tier 1, score 17) ----
    {"tier": 1, "category": "liquor_distributor", "company": "Henderson Selections",       "known_contact": "Vincent Henderson",   "city": "Austin, Texas"},
    {"tier": 2, "category": "liquor_distributor", "company": "Favorite Brands LLC",        "known_contact": None,                  "city": "Buda, Texas"},
    {"tier": 1, "category": "liquor_distributor", "company": "Ben E. Keith Beverages",     "known_contact": None,                  "city": "Austin, Texas"},

    # ---- POS System Resellers (Tier 1, score 17) ----
    {"tier": 1, "category": "pos_reseller",       "company": "Price Professional Solutions","known_contact": "David Price",        "city": "Round Rock, Texas"},
    {"tier": 2, "category": "pos_reseller",       "company": "Austin POS",                 "known_contact": None,                  "city": "Austin, Texas"},
    {"tier": 1, "category": "pos_reseller",       "company": "Fourlane",                   "known_contact": "Marjorie Adams",      "city": "Austin, Texas"},

    # ---- Pest Control (Tier 1, score 17) ----
    {"tier": 1, "category": "pest_control",       "company": "Absolute Pest Management",   "known_contact": "Tony Ragan",          "city": "Austin, Texas"},
    {"tier": 1, "category": "pest_control",       "company": "The Bug Master",             "known_contact": "Dauphin Ewart",       "city": "Austin, Texas"},
    {"tier": 1, "category": "pest_control",       "company": "A-Tex Pest Management",      "known_contact": "Jason Napolski",      "city": "Austin, Texas"},
    {"tier": 2, "category": "pest_control",       "company": "Accurate Termite & Pest",    "known_contact": "Brandon Smith",       "city": "Leander, Texas"},
    {"tier": 2, "category": "pest_control",       "company": "ABC Home & Commercial",      "known_contact": "Holt Myers",          "city": "Austin, Texas"},

    # ---- Commercial Linen & Uniform (Tier 1, score 16) ----
    {"tier": 2, "category": "linen",              "company": "Capital City Linens",         "known_contact": "Andrew Underwood",   "city": "Liberty Hill, Texas"},
    {"tier": 2, "category": "linen",              "company": "TenFold Linen Supply",        "known_contact": "Anthony Cournia",    "city": "West Lake Hills, Texas"},
    {"tier": 2, "category": "linen",              "company": "Metro Linen Service",         "known_contact": None,                 "city": "Austin, Texas"},
    {"tier": 2, "category": "linen",              "company": "EcoClean Austin",             "known_contact": "Kerstin Shoberg",    "city": "Austin, Texas"},
    {"tier": 2, "category": "linen",              "company": "SpinZone Laundry",            "known_contact": "Dan Melendy",        "city": "Austin, Texas"},

    # ---- Commercial Cleaning (Tier 1, score 16) ----
    {"tier": 1, "category": "cleaning",           "company": "OrakPro",                    "known_contact": "Viviana Akel",        "city": "Austin, Texas"},
    {"tier": 1, "category": "cleaning",           "company": "Bowmar Industrial",          "known_contact": "Kevin Bowen",         "city": "Round Rock, Texas"},
    {"tier": 2, "category": "cleaning",           "company": "Pro Hood Cleaning",          "known_contact": None,                  "city": "Austin, Texas"},
    {"tier": 2, "category": "cleaning",           "company": "Juany Cleaning Service",     "known_contact": "Crystal Wu",          "city": "Austin, Texas"},
    {"tier": 2, "category": "cleaning",           "company": "ATX Janitorial Services",    "known_contact": None,                  "city": "Austin, Texas"},
]

ALL_CATEGORIES = sorted({v["category"] for v in VENDOR_TARGETS})


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class ApolloError(Exception):
    """Base class for Apollo client errors."""


class AuthError(ApolloError):
    """401/403 — bad or insufficient credentials (master key required)."""


class RateLimitError(ApolloError):
    """429 — rate limit exceeded and retries exhausted."""


# --------------------------------------------------------------------------- #
# Rate limiter
# --------------------------------------------------------------------------- #

class RateLimiter:
    def __init__(self, max_calls: int = HOURLY_CALL_LIMIT, period: float = 3600.0):
        self.max_calls = max_calls
        self.period = period
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        now = time.monotonic()
        while self._calls and now - self._calls[0] >= self.period:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            sleep_for = self.period - (now - self._calls[0]) + 0.01
            logger.warning("Rate limit window full; sleeping %.1fs", sleep_for)
            time.sleep(max(sleep_for, 0))
            return self.acquire()
        self._calls.append(time.monotonic())


# --------------------------------------------------------------------------- #
# Apollo client
# --------------------------------------------------------------------------- #

class ApolloClient:
    def __init__(self, api_key: str, max_retries: int = 5, timeout: float = 30.0):
        if not api_key:
            raise AuthError("APOLLO_API_KEY not set. Pass --api-key or export the env var.")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "Accept": "application/json",
            "x-api-key": api_key,
        })
        self.limiter = RateLimiter()
        self.max_retries = max_retries
        self.timeout = timeout

    def _post(self, params: dict[str, Any]) -> dict[str, Any]:
        attempt = 0
        while True:
            attempt += 1
            self.limiter.acquire()
            try:
                resp = self.session.post(BASE_URL, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt > self.max_retries:
                    raise ApolloError(f"Network error after {self.max_retries} retries: {exc}") from exc
                time.sleep(min(2 ** attempt, 60))
                continue

            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                raise AuthError(
                    f"{resp.status_code} auth error. Ensure you are using a MASTER API key "
                    "(Settings → API Keys → Master Key in Apollo)."
                )
            if resp.status_code == 422:
                detail = _safe_error(resp)
                # If org name param is rejected, suggest the fallback.
                raise ApolloError(
                    f"422 Invalid parameters: {detail}\n"
                    "Tip: if 'q_organization_name' is rejected, try replacing it with "
                    "'q_keywords' in _build_params() — Apollo endpoint support varies."
                )
            if resp.status_code == 429:
                if attempt > self.max_retries:
                    raise RateLimitError("429 rate limit; retries exhausted.")
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 120)
                logger.warning("429 backing off %ss", wait)
                time.sleep(wait)
                continue
            if attempt > self.max_retries:
                raise ApolloError(f"HTTP {resp.status_code}: {_safe_error(resp)}")
            time.sleep(min(2 ** attempt, 60))

    def search_company(
        self,
        company_name: str,
        city: Optional[str] = None,
        max_results: int = MAX_PER_COMPANY,
    ) -> list[dict[str, Any]]:
        """Return up to max_results decision-makers at company_name."""
        params = _build_params(company_name, city, min(max_results, MAX_PER_PAGE))
        data = self._post(params)
        return data.get("people", [])


def _build_params(company_name: str, city: Optional[str], per_page: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "q_organization_name": company_name,
        "person_seniorities[]": DECISION_SENIORITIES,
        "page": 1,
        "per_page": per_page,
    }
    # City filter helps disambiguate small local companies from national chains
    # with similar names. Skip for very broad city strings like "Texas".
    if city and city != "Texas":
        params["person_locations[]"] = [city]
    return params


def _safe_error(resp: requests.Response) -> str:
    try:
        return json.dumps(resp.json())
    except ValueError:
        return resp.text[:300]


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

OUTPUT_FIELDS = [
    # Vendor metadata
    "tier", "category", "company", "known_contact",
    # Apollo search data (always present)
    "first_name", "last_name_obfuscated", "apollo_title",
    "has_email", "has_direct_phone",
    "apollo_org_name", "apollo_id",
    # Enriched fields (populated when --auto-enrich is set)
    "enriched_name", "enriched_email", "enriched_email_status",
    "enriched_phone", "enriched_linkedin",
    "enriched_city", "enriched_state",
]

_EMPTY_ENRICHED = {
    "enriched_name": "", "enriched_email": "", "enriched_email_status": "",
    "enriched_phone": "", "enriched_linkedin": "",
    "enriched_city": "", "enriched_state": "",
}


def _merge_enriched(row: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Merge Apollo enrichment result into a search row."""
    person = result.get("person") or {}
    contact = person.get("contact") or {}
    phones = contact.get("phone_numbers") or []
    phone = ""
    if phones:
        phone = phones[0].get("sanitized_number") or phones[0].get("raw_number") or ""
    return {
        **row,
        "enriched_name": person.get("name", ""),
        "enriched_email": person.get("email", ""),
        "enriched_email_status": person.get("email_status", ""),
        "enriched_phone": phone,
        "enriched_linkedin": person.get("linkedin_url", ""),
        "enriched_city": person.get("city", ""),
        "enriched_state": person.get("state", ""),
    }


def _flatten_match(vendor: dict[str, Any], person: dict[str, Any]) -> dict[str, Any]:
    org = person.get("organization") or {}
    return {
        "tier": vendor["tier"],
        "category": vendor["category"],
        "company": vendor["company"],
        "known_contact": vendor.get("known_contact") or "",
        "first_name": person.get("first_name", ""),
        "last_name_obfuscated": person.get("last_name_obfuscated", ""),
        "apollo_title": person.get("title", ""),
        "has_email": person.get("has_email", ""),
        "has_direct_phone": person.get("has_direct_phone", ""),
        "apollo_org_name": org.get("name", ""),
        "apollo_id": person.get("id", ""),
        **_EMPTY_ENRICHED,
    }


def _no_match_row(vendor: dict[str, Any]) -> dict[str, Any]:
    return {
        "tier": vendor["tier"],
        "category": vendor["category"],
        "company": vendor["company"],
        "known_contact": vendor.get("known_contact") or "",
        "first_name": "NO_MATCH",
        "last_name_obfuscated": "",
        "apollo_title": "",
        "has_email": "",
        "has_direct_phone": "",
        "apollo_org_name": "",
        "apollo_id": "",
        **_EMPTY_ENRICHED,
    }


def write_results(rows: list[dict[str, Any]], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, Any]]) -> None:
    total_vendors = len({r["company"] for r in rows})
    matched = len({r["company"] for r in rows if r["first_name"] != "NO_MATCH"})
    has_email = sum(1 for r in rows if r.get("has_email") is True)
    print(f"\nVendors searched : {total_vendors}")
    print(f"Vendors matched  : {matched}")
    print(f"People found     : {sum(1 for r in rows if r['first_name'] != 'NO_MATCH')}")
    print(f"  — with email   : {has_email}")
    print(f"  — no match     : {total_vendors - matched}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Pull Apollo.io decision-maker matches for the Austin Restaurant Intel vendor list.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--api-key", default=os.getenv("APOLLO_API_KEY"),
                   help="Apollo MASTER API key. Defaults to $APOLLO_API_KEY.")
    p.add_argument("--output", default=None,
                   help="Output CSV path. Omit to print a summary only.")
    p.add_argument("--tier", type=int, choices=[1, 2], default=None,
                   help="Restrict to Tier 1 or Tier 2 vendors only.")
    p.add_argument("--category", choices=ALL_CATEGORIES, default=None,
                   help=f"Restrict to one category. Options: {', '.join(ALL_CATEGORIES)}")
    p.add_argument("--gaps-only", action="store_true",
                   help="Only search companies with no known contact (known_contact is blank).")
    p.add_argument("--max-per-company", type=int, default=MAX_PER_COMPANY,
                   help="Max Apollo matches to fetch per company.")
    p.add_argument("--auto-enrich", action="store_true",
                   help=(
                       "After searching, enrich every has_email=True match with actual contact "
                       "data (email, phone if known, LinkedIn). CONSUMES APOLLO CREDITS — "
                       "one credit per person enriched."
                   ))
    p.add_argument("--enrich-pause", type=float, default=0.3,
                   help="Seconds to pause between enrichment calls (default 0.3).")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Log progress per company.")
    return p


def filter_targets(
    tier: Optional[int],
    category: Optional[str],
    gaps_only: bool,
) -> list[dict[str, Any]]:
    targets = VENDOR_TARGETS
    if tier is not None:
        targets = [v for v in targets if v["tier"] == tier]
    if category is not None:
        targets = [v for v in targets if v["category"] == category]
    if gaps_only:
        targets = [v for v in targets if not v["known_contact"]]
    return targets


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    targets = filter_targets(args.tier, args.category, args.gaps_only)
    if not targets:
        print("No vendors match the given filters.", file=sys.stderr)
        return 1

    try:
        client = ApolloClient(api_key=args.api_key)
    except AuthError as exc:
        print(f"Auth error: {exc}", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    total = len(targets)

    for i, vendor in enumerate(targets, 1):
        logger.info("[%d/%d] %s (%s)", i, total, vendor["company"], vendor["category"])
        try:
            people = client.search_company(
                vendor["company"],
                city=vendor.get("city"),
                max_results=args.max_per_company,
            )
        except AuthError as exc:
            print(f"Auth error: {exc}", file=sys.stderr)
            return 2
        except ApolloError as exc:
            logger.warning("  Skipping %s — %s", vendor["company"], exc)
            rows.append(_no_match_row(vendor))
            continue

        if people:
            logger.info("  %d match(es) found", len(people))
            for person in people:
                rows.append(_flatten_match(vendor, person))
        else:
            logger.info("  No matches found")
            rows.append(_no_match_row(vendor))

    # ------------------------------------------------------------------ #
    # Optional enrichment pass — one credit per person with has_email=True
    # ------------------------------------------------------------------ #
    if args.auto_enrich:
        if not _ENRICHMENT_AVAILABLE:
            print(
                "Error: --auto-enrich requires apollo_people_enrichment.py in the same directory.",
                file=sys.stderr,
            )
            return 1

        enrichable = [r for r in rows if r.get("has_email") is True and r.get("apollo_id")]
        credit_cost = len(enrichable)
        if credit_cost == 0:
            print("No has_email=True matches to enrich.")
        else:
            print(f"Enriching {credit_cost} match(es) — this will consume {credit_cost} Apollo credit(s).")
            enrich_client = ApolloEnrichClient(api_key=args.api_key)
            enriched_index: dict[str, dict[str, Any]] = {}

            for j, row in enumerate(enrichable, 1):
                apollo_id = row["apollo_id"]
                logger.info("  Enriching [%d/%d] id=%s (%s)", j, credit_cost, apollo_id, row["company"])
                try:
                    result = enrich_client.enrich(EnrichParams(id=apollo_id))
                    enriched_index[apollo_id] = result
                except ApolloError as exc:
                    logger.warning("  Enrichment failed for %s: %s", apollo_id, exc)
                if j < credit_cost:
                    time.sleep(args.enrich_pause)

            # Merge enriched data back into rows in-place.
            for row in rows:
                aid = row.get("apollo_id", "")
                if aid in enriched_index:
                    rows[rows.index(row)] = _merge_enriched(row, enriched_index[aid])

            enriched_count = sum(
                1 for r in rows
                if r.get("enriched_email") or r.get("enriched_name")
            )
            print(f"  Enriched {enriched_count} of {credit_cost} match(es) with contact data.")

    if args.output:
        write_results(rows, args.output)
        print(f"Wrote {len(rows)} rows to {args.output}")

    print_summary(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
