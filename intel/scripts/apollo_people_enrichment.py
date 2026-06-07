#!/usr/bin/env python3
"""
apollo_people_enrichment.py
===========================

A complete command-line tool for enriching people via the Apollo.io
People Enrichment endpoint (POST /api/v1/people/match).

What this does (and how it differs from People Search)
------------------------------------------------------
- SEARCH finds net-new people and reports only whether data EXISTS
  (has_email=true). It is free and returns NO actual emails/phones.
- ENRICHMENT (this tool) takes ONE already-identified person and returns
  the ACTUAL data: real email, full employment history, firmographics,
  and — if you opt in — personal emails and phone numbers.

Important behavior
------------------
- This endpoint CONSUMES CREDITS based on your plan.
- reveal_personal_emails / reveal_phone_number cost extra credits and may
  be withheld for people in GDPR regions.
- reveal_phone_number is ASYNCHRONOUS: the immediate response will NOT
  contain phone numbers. Apollo POSTs them later to your --webhook-url.
  If you pass --reveal-phone you MUST pass --webhook-url.
- Waterfall enrichment (--waterfall-email / --waterfall-phone) checks
  third-party sources for broader coverage; results also arrive at the
  webhook asynchronously, and the sync response includes a "waterfall"
  status block plus a request_id you can poll.

Matching tips
-------------
Apollo matches on the identifiers you supply. The MORE you provide, the
more likely a correct match. An Apollo `id` (from People Search) or an
`email` is the strongest signal. A bare name often returns a 200 with no
enriched record.

Usage examples
--------------
  export APOLLO_API_KEY="your_key"

  # Enrich one person by Apollo ID (best when chaining from Search)
  python apollo_people_enrichment.py --id 64a7ff0cc4dfae00013df1a5

  # Enrich by name + domain, revealing personal emails
  python apollo_people_enrichment.py \
      --name "tim zheng" --domain apollo.io --reveal-personal-emails

  # Bulk-enrich every ID from a Search export (CSV with an 'id' column)
  python apollo_people_enrichment.py \
      --ids-from-csv prospects.csv --output enriched.csv

  # Reveal phone numbers (async -> requires a webhook)
  python apollo_people_enrichment.py --id 64a7ff... \
      --reveal-phone --webhook-url https://webhook.site/your-uuid
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
from typing import Any, Iterable, Optional

try:
    import requests
except ImportError:
    sys.exit("This script requires the 'requests' package. Install it with: pip install requests")


# --------------------------------------------------------------------------- #
# Configuration & constants
# --------------------------------------------------------------------------- #

BASE_URL = "https://api.apollo.io/api/v1/people/match"
HOURLY_CALL_LIMIT = 600  # documented max calls/hour for /people/match

logger = logging.getLogger("apollo.enrich")


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class ApolloError(Exception):
    """Base class for Apollo client errors."""


class AuthError(ApolloError):
    """401 — bad credentials."""


class RateLimitError(ApolloError):
    """429 — exceeded the hourly call limit and retries were exhausted."""


# --------------------------------------------------------------------------- #
# Rate limiter (sliding window)
# --------------------------------------------------------------------------- #

class RateLimiter:
    def __init__(self, max_calls: int, period: float = 3600.0):
        self.max_calls = max_calls
        self.period = period
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        now = time.monotonic()
        while self._calls and now - self._calls[0] >= self.period:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            sleep_for = self.period - (now - self._calls[0]) + 0.01
            logger.warning("Hourly limit reached; sleeping %.1fs", sleep_for)
            time.sleep(max(sleep_for, 0))
            return self.acquire()
        self._calls.append(time.monotonic())


# --------------------------------------------------------------------------- #
# Enrichment request parameters
# --------------------------------------------------------------------------- #

@dataclass
class EnrichParams:
    """Identifiers + reveal options for a single enrichment call."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    hashed_email: Optional[str] = None
    organization_name: Optional[str] = None
    domain: Optional[str] = None
    id: Optional[str] = None
    linkedin_url: Optional[str] = None
    reveal_personal_emails: bool = False
    reveal_phone_number: bool = False
    run_waterfall_email: bool = False
    run_waterfall_phone: bool = False
    webhook_url: Optional[str] = None

    def has_identifier(self) -> bool:
        return any([
            self.first_name, self.last_name, self.name, self.email,
            self.hashed_email, self.id, self.linkedin_url, self.domain,
            self.organization_name,
        ])

    def validate(self) -> None:
        if not self.has_identifier():
            raise ApolloError(
                "Provide at least one identifier (id, email, name, linkedin_url, domain, ...)."
            )
        needs_webhook = self.reveal_phone_number or self.run_waterfall_phone
        if needs_webhook and not self.webhook_url:
            raise ApolloError(
                "Revealing/waterfalling phone numbers is asynchronous and requires --webhook-url."
            )

    def to_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        simple = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "name": self.name,
            "email": self.email,
            "hashed_email": self.hashed_email,
            "organization_name": self.organization_name,
            "domain": self.domain,
            "id": self.id,
            "linkedin_url": self.linkedin_url,
            "webhook_url": self.webhook_url,
        }
        for key, val in simple.items():
            if val:
                params[key] = val
        # Booleans only sent when true (defaults are false server-side).
        for flag in ("reveal_personal_emails", "reveal_phone_number",
                     "run_waterfall_email", "run_waterfall_phone"):
            if getattr(self, flag):
                params[flag] = "true"
        return params


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

class ApolloEnrichClient:
    def __init__(
        self,
        api_key: str,
        rate_limiter: Optional[RateLimiter] = None,
        max_retries: int = 5,
        timeout: float = 30.0,
    ):
        if not api_key:
            raise AuthError("An API key is required (set APOLLO_API_KEY or pass --api-key).")
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
            if resp.status_code == 429:
                if attempt > self.max_retries:
                    raise RateLimitError("429 Rate limit exceeded; retries exhausted.")
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 120)
                logger.warning("429 rate limited; backing off %ss (attempt %d)", wait, attempt)
                time.sleep(wait)
                continue
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

    def enrich(self, params: EnrichParams) -> dict[str, Any]:
        params.validate()
        data = self._request(params.to_params())
        if not data.get("person"):
            logger.info("200 OK but no record enriched for: %s", params.to_params())
        return data

    def enrich_many(
        self,
        items: Iterable[EnrichParams],
        pause: float = 0.2,
    ) -> Iterable[dict[str, Any]]:
        """Enrich a sequence of people one at a time (this endpoint is single-person)."""
        for params in items:
            try:
                yield self.enrich(params)
            except ApolloError as exc:
                logger.error("Skipping one record due to error: %s", exc)
                yield {"person": None, "error": str(exc)}
            time.sleep(pause)


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #

CSV_FIELDS = [
    "id", "name", "title", "seniority", "email", "email_status",
    "phone", "city", "state", "country", "linkedin_url",
    "organization_name", "organization_domain",
    "organization_industry", "organization_employees", "organization_revenue",
    "waterfall_status", "request_id",
]


def flatten(result: dict[str, Any]) -> dict[str, Any]:
    person = result.get("person") or {}
    org = person.get("organization") or {}
    contact = person.get("contact") or {}

    # The immediate response only carries phone numbers when they were already
    # known (revealed ones arrive later via webhook). Grab the first if present.
    phone = None
    phones = contact.get("phone_numbers") or []
    if phones:
        phone = phones[0].get("sanitized_number") or phones[0].get("raw_number")

    waterfall = result.get("waterfall") or {}

    return {
        "id": person.get("id"),
        "name": person.get("name"),
        "title": person.get("title"),
        "seniority": person.get("seniority"),
        "email": person.get("email"),
        "email_status": person.get("email_status"),
        "phone": phone,
        "city": person.get("city"),
        "state": person.get("state"),
        "country": person.get("country"),
        "linkedin_url": person.get("linkedin_url"),
        "organization_name": org.get("name"),
        "organization_domain": org.get("primary_domain"),
        "organization_industry": org.get("industry"),
        "organization_employees": org.get("estimated_num_employees"),
        "organization_revenue": org.get("annual_revenue_printed"),
        "waterfall_status": waterfall.get("status"),
        "request_id": result.get("request_id"),
    }


def write_csv(results: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for result in results:
            writer.writerow(flatten(result))


def write_json(results: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)


def print_summary(results: list[dict[str, Any]]) -> None:
    enriched = [r for r in results if r.get("person")]
    print(f"Enriched {len(enriched)} of {len(results)} record(s).")
    for result in enriched:
        row = flatten(result)
        line = f"  {row['name'] or '(unknown)'} — {row['title'] or 'n/a'} @ {row['organization_name'] or 'n/a'}"
        if row["email"]:
            line += f"  <{row['email']}>"
        if row["waterfall_status"]:
            line += f"  [waterfall: {row['waterfall_status']}]"
        print(line)
    pending_phone = [r for r in results if (r.get("waterfall") or {}).get("status")]
    if pending_phone:
        print("\nNote: phone/waterfall data is delivered asynchronously to your webhook.")
        print("Match results to requests using the request_id field.")


# --------------------------------------------------------------------------- #
# Input building
# --------------------------------------------------------------------------- #

def ids_from_csv(path: str, column: str = "id") -> list[str]:
    """Read an 'id' column from a CSV (e.g. a People Search export)."""
    ids: list[str] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or column not in reader.fieldnames:
            raise ApolloError(f"CSV '{path}' has no '{column}' column. Found: {reader.fieldnames}")
        for row in reader:
            val = (row.get(column) or "").strip()
            if val:
                ids.append(val)
    return ids


def build_items(args: argparse.Namespace) -> list[EnrichParams]:
    reveal_opts = dict(
        reveal_personal_emails=args.reveal_personal_emails,
        reveal_phone_number=args.reveal_phone,
        run_waterfall_email=args.waterfall_email,
        run_waterfall_phone=args.waterfall_phone,
        webhook_url=args.webhook_url,
    )

    if args.ids_from_csv:
        ids = ids_from_csv(args.ids_from_csv, args.csv_column)
        logger.info("Loaded %d IDs from %s", len(ids), args.ids_from_csv)
        return [EnrichParams(id=i, **reveal_opts) for i in ids]

    # Single-person mode from explicit flags.
    return [EnrichParams(
        first_name=args.first_name,
        last_name=args.last_name,
        name=args.name,
        email=args.email,
        hashed_email=args.hashed_email,
        organization_name=args.organization_name,
        domain=args.domain,
        id=args.id,
        linkedin_url=args.linkedin_url,
        **reveal_opts,
    )]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Enrich people via the Apollo.io People Enrichment endpoint (consumes credits).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--api-key", default=os.getenv("APOLLO_API_KEY"),
                   help="Apollo API key. Defaults to $APOLLO_API_KEY.")

    ident = p.add_argument_group("identifiers (supply as many as you can)")
    ident.add_argument("--id", help="Apollo person ID (best; from People Search).")
    ident.add_argument("--email", help="Person's email address.")
    ident.add_argument("--hashed-email", help="MD5 or SHA-256 hashed email.")
    ident.add_argument("--name", help="Full name, e.g. 'tim zheng'.")
    ident.add_argument("--first-name", help="First name.")
    ident.add_argument("--last-name", help="Last name.")
    ident.add_argument("--domain", help="Employer domain, e.g. apollo.io (no www/@).")
    ident.add_argument("--organization-name", help="Employer name.")
    ident.add_argument("--linkedin-url", help="LinkedIn profile URL.")

    bulk = p.add_argument_group("bulk input")
    bulk.add_argument("--ids-from-csv", help="CSV file with an ID column (e.g. a Search export).")
    bulk.add_argument("--csv-column", default="id", help="Name of the ID column in the CSV.")

    reveal = p.add_argument_group("reveal options (extra credits; phone is async)")
    reveal.add_argument("--reveal-personal-emails", action="store_true",
                        help="Return personal emails (withheld in GDPR regions).")
    reveal.add_argument("--reveal-phone", action="store_true",
                        help="Return phone numbers ASYNC; requires --webhook-url.")
    reveal.add_argument("--waterfall-email", action="store_true",
                        help="Run email waterfall enrichment (third-party sources).")
    reveal.add_argument("--waterfall-phone", action="store_true",
                        help="Run phone waterfall enrichment; requires --webhook-url.")
    reveal.add_argument("--webhook-url",
                        help="HTTPS webhook for async phone/waterfall results.")

    out = p.add_argument_group("output")
    out.add_argument("--output", help="Output file path. Omit to print a summary.")
    out.add_argument("--format", choices=["csv", "json"], default=None,
                     help="Output format. Inferred from --output extension if omitted.")
    out.add_argument("--pause", type=float, default=0.2,
                     help="Seconds to pause between bulk calls.")
    out.add_argument("-v", "--verbose", action="count", default=0,
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

    try:
        items = build_items(args)
        if not items:
            print("Nothing to enrich. Provide identifiers or --ids-from-csv.", file=sys.stderr)
            return 3

        client = ApolloEnrichClient(api_key=args.api_key)

        if len(items) == 1:
            results = [client.enrich(items[0])]
        else:
            logger.info("Bulk-enriching %d people (this consumes credits).", len(items))
            results = list(client.enrich_many(items, pause=args.pause))

    except AuthError as exc:
        print(f"Auth error: {exc}", file=sys.stderr)
        return 2
    except RateLimitError as exc:
        print(f"Rate limit error: {exc}", file=sys.stderr)
        return 4
    except ApolloError as exc:
        print(f"Apollo error: {exc}", file=sys.stderr)
        return 1

    fmt = resolve_format(args.output, args.format)
    if args.output and fmt == "csv":
        write_csv(results, args.output)
        print(f"Wrote {len(results)} record(s) to {args.output} (CSV).")
    elif args.output and fmt == "json":
        write_json(results, args.output)
        print(f"Wrote {len(results)} record(s) to {args.output} (JSON).")
    else:
        print_summary(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
