#!/usr/bin/env python3
"""
apollo_people_search.py
=======================

A complete command-line tool for prospecting people via the Apollo.io
People API Search endpoint (POST /api/v1/mixed_people/api_search).

Features
--------
- Master-API-key auth (required by this endpoint)
- Token-bucket rate limiting under Apollo's 600 calls/hour cap
- Automatic pagination, respecting the 50,000-record display limit
- Exponential backoff with Retry-After support on HTTP 429
- Clear, typed error handling for 401/403/422/429
- Export to CSV or JSON (or stream to stdout)
- Filters exposed as CLI flags; key read from env or flag

Notes
-----
- This endpoint does NOT consume credits and does NOT return emails or
  phone numbers. It only reports whether such data EXISTS (has_email,
  has_direct_phone, etc.). Use the People Enrichment endpoints afterward
  to retrieve actual contact data (those DO consume credits).
- Despite being a POST, all parameters travel as QUERY parameters.
  Array parameters use the trailing "[]" key form (e.g. person_titles[]).

Usage examples
--------------
  export APOLLO_API_KEY="your_master_key"

  # Basic search, print a summary table to the console
  python apollo_people_search.py \
      --title "sales manager" --title "marketing manager" \
      --seniority director --seniority vp \
      --location california \
      --employees 250,500

  # Pull up to 5,000 matches and write them to CSV
  python apollo_people_search.py \
      --title "research analyst" --location ireland \
      --max-records 5000 --output prospects.csv

  # Same, as JSON
  python apollo_people_search.py \
      --title "research analyst" --output prospects.json --format json
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
    sys.exit("This script requires the 'requests' package. Install it with: pip install requests")


# --------------------------------------------------------------------------- #
# Configuration & constants
# --------------------------------------------------------------------------- #

BASE_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"

# Apollo limits for this endpoint.
HOURLY_CALL_LIMIT = 600          # documented max calls/hour
MAX_PER_PAGE = 100               # documented max page size
MAX_PAGES = 500                  # 100 * 500 = 50,000 record display cap
MAX_RECORDS_CAP = MAX_PER_PAGE * MAX_PAGES

# Valid seniority values accepted by the API.
VALID_SENIORITIES = {
    "owner", "founder", "c_suite", "partner", "vp",
    "head", "director", "manager", "senior", "entry", "intern",
}

# Valid email statuses.
VALID_EMAIL_STATUSES = {"verified", "unverified", "likely to engage", "unavailable"}

logger = logging.getLogger("apollo")


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class ApolloError(Exception):
    """Base class for Apollo client errors."""


class AuthError(ApolloError):
    """401/403 — bad or insufficient credentials (master key required)."""


class ValidationError(ApolloError):
    """422 — invalid search parameters."""


class RateLimitError(ApolloError):
    """429 — exceeded the hourly call limit and retries were exhausted."""


# --------------------------------------------------------------------------- #
# Rate limiter
# --------------------------------------------------------------------------- #

class RateLimiter:
    """
    Simple sliding-window limiter. Ensures no more than `max_calls` happen
    within `period` seconds. Blocks (sleeps) when the window is full.
    """

    def __init__(self, max_calls: int, period: float = 3600.0):
        self.max_calls = max_calls
        self.period = period
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        now = time.monotonic()
        # Drop timestamps older than the window.
        while self._calls and now - self._calls[0] >= self.period:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            sleep_for = self.period - (now - self._calls[0]) + 0.01
            logger.warning("Hourly limit reached; sleeping %.1fs", sleep_for)
            time.sleep(max(sleep_for, 0))
            return self.acquire()
        self._calls.append(time.monotonic())


# --------------------------------------------------------------------------- #
# Search filters
# --------------------------------------------------------------------------- #

@dataclass
class SearchFilters:
    """Holds the subset of Apollo filters this CLI exposes."""
    person_titles: list[str] = field(default_factory=list)
    person_locations: list[str] = field(default_factory=list)
    person_seniorities: list[str] = field(default_factory=list)
    organization_locations: list[str] = field(default_factory=list)
    organization_num_employees_ranges: list[str] = field(default_factory=list)
    q_keywords: Optional[str] = None
    include_similar_titles: Optional[bool] = None
    contact_email_status: list[str] = field(default_factory=list)
    revenue_min: Optional[int] = None
    revenue_max: Optional[int] = None

    def validate(self) -> None:
        bad_sen = set(self.person_seniorities) - VALID_SENIORITIES
        if bad_sen:
            raise ValidationError(
                f"Invalid seniority value(s): {sorted(bad_sen)}. "
                f"Allowed: {sorted(VALID_SENIORITIES)}"
            )
        bad_email = set(self.contact_email_status) - VALID_EMAIL_STATUSES
        if bad_email:
            raise ValidationError(
                f"Invalid email status(es): {sorted(bad_email)}. "
                f"Allowed: {sorted(VALID_EMAIL_STATUSES)}"
            )
        for rng in self.organization_num_employees_ranges:
            parts = rng.split(",")
            if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
                raise ValidationError(
                    f"Employee range '{rng}' must be 'min,max' with digits, e.g. '250,500'."
                )

    def to_params(self) -> dict[str, Any]:
        """Build the query-parameter dict using Apollo's [] array convention."""
        params: dict[str, Any] = {}
        if self.person_titles:
            params["person_titles[]"] = self.person_titles
        if self.person_locations:
            params["person_locations[]"] = self.person_locations
        if self.person_seniorities:
            params["person_seniorities[]"] = self.person_seniorities
        if self.organization_locations:
            params["organization_locations[]"] = self.organization_locations
        if self.organization_num_employees_ranges:
            params["organization_num_employees_ranges[]"] = self.organization_num_employees_ranges
        if self.contact_email_status:
            params["contact_email_status[]"] = self.contact_email_status
        if self.q_keywords:
            params["q_keywords"] = self.q_keywords
        if self.include_similar_titles is not None:
            params["include_similar_titles"] = str(self.include_similar_titles).lower()
        if self.revenue_min is not None:
            params["revenue_range[min]"] = self.revenue_min
        if self.revenue_max is not None:
            params["revenue_range[max]"] = self.revenue_max
        return params


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

class ApolloClient:
    def __init__(
        self,
        api_key: str,
        rate_limiter: Optional[RateLimiter] = None,
        max_retries: int = 5,
        timeout: float = 30.0,
    ):
        if not api_key:
            raise AuthError("A master API key is required (set APOLLO_API_KEY or pass --api-key).")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "Accept": "application/json",
            "x-api-key": api_key,
        })
        self.rate_limiter = rate_limiter or RateLimiter(HOURLY_CALL_LIMIT)
        self.max_retries = max_retries
        self.timeout = timeout

    def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        attempt = 0
        while True:
            attempt += 1
            self.rate_limiter.acquire()
            try:
                resp = self.session.post(BASE_URL, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt > self.max_retries:
                    raise ApolloError(f"Network error after {self.max_retries} retries: {exc}") from exc
                backoff = min(2 ** attempt, 60)
                logger.warning("Network error (%s); retrying in %ss", exc, backoff)
                time.sleep(backoff)
                continue

            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401:
                raise AuthError("401 Invalid access credentials. Check your API key.")
            if resp.status_code == 403:
                raise AuthError(
                    "403 This endpoint requires a MASTER API key. "
                    "Create one at https://docs.apollo.io/docs/create-api-key"
                )
            if resp.status_code == 422:
                detail = self._safe_error(resp)
                raise ValidationError(f"422 Invalid parameters: {detail}")
            if resp.status_code == 429:
                if attempt > self.max_retries:
                    raise RateLimitError("429 Rate limit exceeded; retries exhausted.")
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 120)
                logger.warning("429 rate limited; backing off %ss (attempt %d)", wait, attempt)
                time.sleep(wait)
                continue
            # Anything else: retry a few times, then give up.
            if attempt > self.max_retries:
                raise ApolloError(f"HTTP {resp.status_code}: {self._safe_error(resp)}")
            backoff = min(2 ** attempt, 60)
            logger.warning("HTTP %s; retrying in %ss", resp.status_code, backoff)
            time.sleep(backoff)

    @staticmethod
    def _safe_error(resp: requests.Response) -> str:
        try:
            return json.dumps(resp.json())
        except ValueError:
            return resp.text[:300]

    def search_page(self, filters: SearchFilters, page: int, per_page: int) -> dict[str, Any]:
        params = filters.to_params()
        params["page"] = page
        params["per_page"] = per_page
        logger.debug("Requesting page %d (per_page=%d)", page, per_page)
        return self._request(params)

    def search_all(
        self,
        filters: SearchFilters,
        max_records: int = MAX_RECORDS_CAP,
        per_page: int = MAX_PER_PAGE,
    ) -> Iterator[dict[str, Any]]:
        """Yield people one at a time, paginating automatically."""
        filters.validate()
        per_page = min(per_page, MAX_PER_PAGE)
        max_records = min(max_records, MAX_RECORDS_CAP)
        fetched = 0
        page = 1

        first = self.search_page(filters, page=1, per_page=per_page)
        total = first.get("total_entries", 0)
        logger.info("Apollo reports %s total matching people.", f"{total:,}")
        if total > MAX_RECORDS_CAP:
            logger.warning(
                "Match count (%s) exceeds the %s display cap; add filters to reach the rest.",
                f"{total:,}", f"{MAX_RECORDS_CAP:,}",
            )

        while True:
            data = first if page == 1 else self.search_page(filters, page, per_page)
            first = None  # consumed
            people = data.get("people", [])
            if not people:
                break
            for person in people:
                yield person
                fetched += 1
                if fetched >= max_records:
                    logger.info("Reached max_records=%d; stopping.", max_records)
                    return
            page += 1
            if page > MAX_PAGES:
                logger.info("Reached the %d-page hard limit; stopping.", MAX_PAGES)
                return


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #

CSV_FIELDS = [
    "id", "first_name", "last_name_obfuscated", "title",
    "last_refreshed_at", "has_email", "has_direct_phone",
    "has_city", "has_state", "has_country",
    "organization_name", "org_has_revenue", "org_has_employee_count",
]


def flatten(person: dict[str, Any]) -> dict[str, Any]:
    org = person.get("organization") or {}
    return {
        "id": person.get("id"),
        "first_name": person.get("first_name"),
        "last_name_obfuscated": person.get("last_name_obfuscated"),
        "title": person.get("title"),
        "last_refreshed_at": person.get("last_refreshed_at"),
        "has_email": person.get("has_email"),
        "has_direct_phone": person.get("has_direct_phone"),
        "has_city": person.get("has_city"),
        "has_state": person.get("has_state"),
        "has_country": person.get("has_country"),
        "organization_name": org.get("name"),
        "org_has_revenue": org.get("has_revenue"),
        "org_has_employee_count": org.get("has_employee_count"),
    }


def write_csv(people: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for person in people:
            writer.writerow(flatten(person))


def write_json(people: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(people, fh, indent=2, ensure_ascii=False)


def print_table(people: list[dict[str, Any]], limit: int = 25) -> None:
    if not people:
        print("No matching people found.")
        return
    rows = [flatten(p) for p in people[:limit]]
    name_w = max(len("Name"), *(len(f"{r['first_name']} {r['last_name_obfuscated']}") for r in rows))
    title_w = max(len("Title"), *(len(str(r["title"] or "")) for r in rows))
    org_w = max(len("Organization"), *(len(str(r["organization_name"] or "")) for r in rows))
    header = f"{'Name':<{name_w}}  {'Title':<{title_w}}  {'Organization':<{org_w}}  Email?"
    print(header)
    print("-" * len(header))
    for r in rows:
        name = f"{r['first_name']} {r['last_name_obfuscated']}"
        print(
            f"{name:<{name_w}}  {str(r['title'] or ''):<{title_w}}  "
            f"{str(r['organization_name'] or ''):<{org_w}}  "
            f"{'yes' if r['has_email'] else 'no'}"
        )
    if len(people) > limit:
        print(f"... and {len(people) - limit:,} more (use --output to save all).")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Search the Apollo.io People database (prospecting; no credits consumed).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--api-key", default=os.getenv("APOLLO_API_KEY"),
                   help="Apollo MASTER API key. Defaults to $APOLLO_API_KEY.")

    # Filters (repeatable flags build lists).
    p.add_argument("--title", action="append", default=[], dest="titles",
                   help="Job title to match (repeatable).")
    p.add_argument("--location", action="append", default=[], dest="locations",
                   help="Person location: city/state/country (repeatable).")
    p.add_argument("--seniority", action="append", default=[], dest="seniorities",
                   help=f"Seniority (repeatable). One of: {sorted(VALID_SENIORITIES)}")
    p.add_argument("--org-location", action="append", default=[], dest="org_locations",
                   help="Employer HQ location (repeatable).")
    p.add_argument("--employees", action="append", default=[], dest="employee_ranges",
                   help="Employer headcount range as 'min,max', e.g. 250,500 (repeatable).")
    p.add_argument("--email-status", action="append", default=[], dest="email_statuses",
                   help=f"Email status (repeatable). One of: {sorted(VALID_EMAIL_STATUSES)}")
    p.add_argument("--keywords", default=None, help="Free-text keyword filter.")
    p.add_argument("--strict-titles", action="store_true",
                   help="Disable similar-title matching (include_similar_titles=false).")
    p.add_argument("--revenue-min", type=int, default=None, help="Min employer revenue.")
    p.add_argument("--revenue-max", type=int, default=None, help="Max employer revenue.")

    # Pagination / output.
    p.add_argument("--max-records", type=int, default=100,
                   help=f"Max people to fetch (hard cap {MAX_RECORDS_CAP:,}).")
    p.add_argument("--per-page", type=int, default=MAX_PER_PAGE,
                   help=f"Page size (max {MAX_PER_PAGE}).")
    p.add_argument("--output", default=None, help="Output file path. Omit to print a table.")
    p.add_argument("--format", choices=["csv", "json"], default=None,
                   help="Output format. Inferred from --output extension if omitted.")
    p.add_argument("-v", "--verbose", action="count", default=0,
                   help="-v for INFO, -vv for DEBUG.")
    return p


def resolve_format(output: Optional[str], fmt: Optional[str]) -> Optional[str]:
    if fmt:
        return fmt
    if output:
        return "json" if output.lower().endswith(".json") else "csv"
    return None


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    level = logging.WARNING - (10 * min(args.verbose, 2))
    logging.basicConfig(level=level, format="%(levelname)s  %(message)s")

    filters = SearchFilters(
        person_titles=args.titles,
        person_locations=args.locations,
        person_seniorities=args.seniorities,
        organization_locations=args.org_locations,
        organization_num_employees_ranges=args.employee_ranges,
        contact_email_status=args.email_statuses,
        q_keywords=args.keywords,
        include_similar_titles=(False if args.strict_titles else None),
        revenue_min=args.revenue_min,
        revenue_max=args.revenue_max,
    )

    if not any([
        filters.person_titles, filters.person_locations, filters.person_seniorities,
        filters.organization_locations, filters.organization_num_employees_ranges,
        filters.q_keywords, filters.contact_email_status,
        filters.revenue_min, filters.revenue_max,
    ]):
        print("Warning: no filters set — this will match the entire database. "
              "Add at least one filter to get useful, capped results.", file=sys.stderr)

    try:
        client = ApolloClient(api_key=args.api_key)
        people = list(client.search_all(
            filters,
            max_records=args.max_records,
            per_page=args.per_page,
        ))
    except AuthError as exc:
        print(f"Auth error: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 3
    except RateLimitError as exc:
        print(f"Rate limit error: {exc}", file=sys.stderr)
        return 4
    except ApolloError as exc:
        print(f"Apollo error: {exc}", file=sys.stderr)
        return 1

    fmt = resolve_format(args.output, args.format)
    if args.output and fmt == "csv":
        write_csv(people, args.output)
        print(f"Wrote {len(people):,} records to {args.output} (CSV).")
    elif args.output and fmt == "json":
        write_json(people, args.output)
        print(f"Wrote {len(people):,} records to {args.output} (JSON).")
    else:
        print_table(people)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
