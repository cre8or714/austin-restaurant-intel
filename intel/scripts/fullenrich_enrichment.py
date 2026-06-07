"""
fullenrich_enrichment.py
Waterfall contact enrichment via FullEnrich API — 20+ provider cascade
(Lusha, Apollo, ZoomInfo, Hunter, Datagma, etc.)

Auth: set FULLENRICH_API_KEY env var before running.
Docs: https://app.fullenrich.com/api/v2

Usage — single contact:
  python fullenrich_enrichment.py \
    --first Camden --last Stuerzenberger \
    --domain austinwinebelly.com \
    --output camden_enriched.csv

Usage — batch from CSV:
  python fullenrich_enrichment.py \
    --csv contacts.csv \
    --output enriched.csv \
    --phone

CSV must have columns: first_name, last_name, and domain OR company_name.
Optional columns: linkedin_url, email, ref_id, notes.

Credit costs (FullEnrich):
  Work email  = 1 credit/found
  Mobile      = 10 credits/found
  Personal    = 3 credits/found
  Not found   = 0 credits
"""

import argparse
import csv
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Optional
import urllib.request
import urllib.error

FULLENRICH_BASE = "https://app.fullenrich.com/api/v2"
API_KEY_ENV = "FULLENRICH_API_KEY"
BATCH_SIZE = 100   # FullEnrich max per request
RATE_LIMIT_PAUSE = 1.0  # seconds between batches (60 calls/min limit)


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class ContactInput:
    first_name: str
    last_name: str
    company_domain: str = ""
    company_name: str = ""
    linkedin_url: str = ""
    email: str = ""
    ref_id: str = ""
    notes: str = ""

    def to_api_dict(self, enrich_fields: list = None) -> dict:
        d: dict = {}
        if self.first_name:
            d["first_name"] = self.first_name
        if self.last_name:
            d["last_name"] = self.last_name
        if self.company_domain:
            d["domain"] = self.company_domain
        elif self.company_name:
            d["company_name"] = self.company_name
        if self.linkedin_url:
            d["linkedin_url"] = self.linkedin_url
        if self.email:
            d["email"] = self.email
        if self.ref_id:
            d["reference"] = self.ref_id
        # enrich_fields is required per record by FullEnrich API
        d["enrich_fields"] = enrich_fields or ["contact.work_emails"]
        return d


@dataclass
class EnrichedContact:
    ref_id: str = ""
    first_name: str = ""
    last_name: str = ""
    company_domain: str = ""
    company_name: str = ""
    work_email: str = ""
    work_email_confidence: str = ""
    personal_email: str = ""
    mobile_phone: str = ""
    landline_phone: str = ""
    job_title: str = ""
    linkedin_url: str = ""
    location_city: str = ""
    location_state: str = ""
    location_country: str = ""
    credits_used: int = 0
    enrichment_status: str = ""
    notes: str = ""


# ── API client ────────────────────────────────────────────────────────────────

POLL_SCHEDULE = [2, 3, 5, 8, 13, 21, 34, 60, 60, 60]  # seconds between polls


class FullEnrichClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = f"{FULLENRICH_BASE}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} - {body_text}") from e

    def _poll(self, enrichment_id: str, verbose: bool = False) -> dict:
        """Poll GET /contact/enrich/bulk/{id} until status is FINISHED or FAILED."""
        for i, wait in enumerate(POLL_SCHEDULE):
            time.sleep(wait)
            result = self._request("GET", f"/contact/enrich/bulk/{enrichment_id}")
            status = result.get("status", "").upper()
            if verbose:
                cost = result.get("cost", {}).get("credits", "?")
                print(f"    poll {i+1}: status={status} credits_so_far={cost}")
            if status in ("FINISHED", "FAILED", "ERROR"):
                return result
        raise RuntimeError(f"FullEnrich enrichment {enrichment_id} did not finish after {sum(POLL_SCHEDULE)}s")

    def enrich_bulk(
        self,
        contacts: list,
        batch_name: str = "",
        enrich_work_email: bool = True,
        enrich_phone: bool = False,
        enrich_personal_email: bool = False,
        verbose: bool = False,
    ) -> list:
        if not contacts:
            return []
        if len(contacts) > BATCH_SIZE:
            raise ValueError(f"FullEnrich max {BATCH_SIZE} contacts per call.")

        # Build per-contact enrich_fields list (required by FullEnrich API)
        fields = []
        if enrich_work_email:
            fields.append("contact.work_emails")
        if enrich_phone:
            fields.append("contact.phones")
        if enrich_personal_email:
            fields.append("contact.personal_emails")
        if not fields:
            fields = ["contact.work_emails"]

        payload: dict = {
            "name": batch_name or f"austin-intel-{uuid.uuid4().hex[:8]}",
            "data": [c.to_api_dict(enrich_fields=fields) for c in contacts],
        }

        # POST returns enrichment_id; results arrive asynchronously
        submit_response = self._request("POST", "/contact/enrich/bulk", payload)
        if os.environ.get("FULLENRICH_DEBUG"):
            print(f"[DEBUG] submit response: {json.dumps(submit_response, indent=2)}", file=sys.stderr)

        enrichment_id = submit_response.get("enrichment_id") or submit_response.get("id")
        if not enrichment_id:
            raise RuntimeError(f"No enrichment_id in response: {submit_response}")

        if verbose:
            print(f"    enrichment_id: {enrichment_id} — polling for results...")

        finished = self._poll(enrichment_id, verbose=verbose)
        if os.environ.get("FULLENRICH_DEBUG"):
            print(f"[DEBUG] finished response: {json.dumps(finished, indent=2)}", file=sys.stderr)

        return _parse_bulk_response(finished, contacts)


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_bulk_response(response: dict, originals: list) -> list:
    """
    Parse async FullEnrich FINISHED response.
    Results are matched by position (index) since the API does not echo the
    'reference' field back in the 'input' block.

    Response shape per item:
      { "input": {...}, "contact_info": {work_emails, phones, personal_emails},
        "profile": {first_name, last_name, location, employment, social_profiles} }
    """
    items = response.get("data", [])
    if not isinstance(items, list):
        items = []

    results = []
    for idx, item in enumerate(items):
        original = originals[idx] if idx < len(originals) else None

        profile = item.get("profile", {})
        contact_info = item.get("contact_info", {})
        inp = item.get("input", {})

        # Job title from current employment
        job_title = ""
        current_job = profile.get("employment", {}).get("current", {})
        if current_job:
            job_title = current_job.get("title", "")

        # LinkedIn from social_profiles
        linkedin_url = (
            profile.get("social_profiles", {})
            .get("professional_network", {})
            .get("url", "")
        )

        loc = profile.get("location", {})

        ec = EnrichedContact(
            ref_id=getattr(original, "ref_id", str(idx)),
            first_name=profile.get("first_name", getattr(original, "first_name", "")),
            last_name=profile.get("last_name", getattr(original, "last_name", "")),
            company_domain=inp.get("domain", getattr(original, "company_domain", "")),
            company_name=inp.get("company_name", getattr(original, "company_name", "")),
            job_title=job_title,
            linkedin_url=linkedin_url,
            location_city=loc.get("city", ""),
            location_state=loc.get("region", loc.get("state", "")),
            location_country=loc.get("country", ""),
            notes=getattr(original, "notes", ""),
        )

        # Work email
        work_emails = contact_info.get("work_emails", [])
        if work_emails:
            best = work_emails[0]
            ec.work_email = best.get("email", "")
            ec.work_email_confidence = best.get("status", best.get("confidence", ""))

        # Personal email
        personal_emails = contact_info.get("personal_emails", [])
        if personal_emails:
            ec.personal_email = personal_emails[0].get("email", "")

        # Phones
        phones = contact_info.get("phones", [])
        if isinstance(phones, list):
            for ph in phones:
                ptype = ph.get("type", "")
                number = ph.get("number", ph.get("phone", ""))
                if ptype == "mobile" and not ec.mobile_phone:
                    ec.mobile_phone = number
                elif ptype in ("landline", "direct", "work") and not ec.landline_phone:
                    ec.landline_phone = number
        elif isinstance(phones, dict):
            ec.mobile_phone = phones.get("mobile", "")
            ec.landline_phone = phones.get("landline", "")

        ec.credits_used = item.get("credits_used", item.get("credits", 0))
        ec.enrichment_status = "found" if (ec.work_email or ec.mobile_phone) else "not_found"

        results.append(ec)

    # Pad stubs if API returned fewer items than submitted
    for i in range(len(items), len(originals)):
        c = originals[i]
        results.append(EnrichedContact(
            ref_id=c.ref_id,
            first_name=c.first_name,
            last_name=c.last_name,
            company_domain=c.company_domain,
            company_name=c.company_name,
            notes=c.notes,
            enrichment_status="not_found",
            credits_used=0,
        ))

    return results


# ── CSV helpers ───────────────────────────────────────────────────────────────

def read_csv_contacts(path: str) -> list:
    contacts = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            first = (row.get("first_name") or row.get("First Name") or "").strip()
            last = (row.get("last_name") or row.get("Last Name") or "").strip()
            if not first or not last:
                continue
            c = ContactInput(
                first_name=first,
                last_name=last,
                company_domain=(row.get("company_domain") or row.get("domain") or "").strip(),
                company_name=(row.get("company_name") or row.get("Company") or "").strip(),
                linkedin_url=(row.get("linkedin_url") or row.get("linkedin") or "").strip(),
                email=(row.get("email") or row.get("Email") or "").strip(),
                ref_id=(row.get("ref_id") or str(i)),
                notes=(row.get("notes") or "").strip(),
            )
            contacts.append(c)
    return contacts


def write_csv(results: list, path: str) -> None:
    if not results:
        print("  No results to write.")
        return
    fields = list(EnrichedContact.__dataclass_fields__.keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
    print(f"  Wrote {len(results)} row(s) -> {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="FullEnrich waterfall contact enrichment (email, phone, LinkedIn).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single contact by domain
  python fullenrich_enrichment.py \\
    --first Camden --last Stuerzenberger \\
    --domain austinwinebelly.com \\
    --output camden.csv

  # Single contact by company name (fallback when no domain known)
  python fullenrich_enrichment.py \\
    --first Brian --last Knowles \\
    --company "Terrible Love" \\
    --linkedin https://www.linkedin.com/in/brian-knowles-7969779 \\
    --phone --output brian.csv

  # Batch from CSV
  python fullenrich_enrichment.py \\
    --csv contacts.csv \\
    --output enriched.csv \\
    --phone

  # Batch with personal email too (3 credits/found)
  python fullenrich_enrichment.py --csv contacts.csv --output out.csv --phone --personal-email
""",
    )

    parser.add_argument(
        "--api-key",
        default=os.environ.get(API_KEY_ENV, ""),
        help=f"FullEnrich API key (default: ${API_KEY_ENV})",
    )

    # Single contact args
    single = parser.add_argument_group("single contact")
    single.add_argument("--first", help="First name")
    single.add_argument("--last", help="Last name")
    single.add_argument("--domain", help="Company domain (e.g. austinwinebelly.com)")
    single.add_argument("--company", help="Company name (used if --domain not provided)")
    single.add_argument("--linkedin", help="LinkedIn URL (increases match accuracy)")
    single.add_argument("--email", help="Known email address (for cross-enrichment)")

    # Batch args
    batch = parser.add_argument_group("batch mode")
    batch.add_argument("--csv", help="CSV path (columns: first_name, last_name, domain or company_name)")

    # Output
    parser.add_argument("--output", "-o", default="fullenrich_results.csv", help="Output CSV path")

    # Enrichment fields
    enrich = parser.add_argument_group("enrichment options")
    enrich.add_argument("--phone", action="store_true",
                        help="Request mobile + landline (10 credits per found number)")
    enrich.add_argument("--personal-email", action="store_true",
                        help="Request personal email (3 credits per found email)")
    enrich.add_argument("--no-work-email", action="store_true",
                        help="Skip work email enrichment (1 credit per found email)")

    parser.add_argument("--batch-pause", type=float, default=RATE_LIMIT_PAUSE,
                        help="Seconds between batches, rate limit is 60 req/min (default 1.0)")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    # ── Validate API key ──────────────────────────────────────────────────────
    api_key = args.api_key.strip()
    if not api_key:
        print(f"ERROR: FullEnrich API key not found. Set {API_KEY_ENV} env var or pass --api-key.",
              file=sys.stderr)
        return 1

    client = FullEnrichClient(api_key=api_key)

    # ── Build contact list ────────────────────────────────────────────────────
    contacts = []
    if args.csv:
        contacts = read_csv_contacts(args.csv)
        if not contacts:
            print(f"ERROR: No valid contacts in {args.csv} (need first_name + last_name).",
                  file=sys.stderr)
            return 1
        print(f"Loaded {len(contacts)} contact(s) from {args.csv}")
    elif args.first and args.last:
        contacts = [ContactInput(
            first_name=args.first,
            last_name=args.last,
            company_domain=args.domain or "",
            company_name=args.company or "",
            linkedin_url=args.linkedin or "",
            email=args.email or "",
            ref_id="single-0",
        )]
    else:
        print("ERROR: Provide --first + --last for single contact, or --csv for batch.",
              file=sys.stderr)
        parser.print_help()
        return 1

    enrich_work = not args.no_work_email
    enrich_phone = args.phone
    enrich_personal = args.personal_email

    # ── Credit preview ────────────────────────────────────────────────────────
    n = len(contacts)
    max_credits = (n * 1 if enrich_work else 0) + (n * 10 if enrich_phone else 0) + (n * 3 if enrich_personal else 0)
    print(f"Contacts: {n}  |  Max credit cost: ~{max_credits}")
    print(f"Enriching: {'work_email ' if enrich_work else ''}{'phone ' if enrich_phone else ''}{'personal_email' if enrich_personal else ''}".strip())
    if not (enrich_work or enrich_phone or enrich_personal):
        print("WARNING: No enrichment fields selected. Use --phone or --personal-email to request more data.")

    # ── Batch processing ──────────────────────────────────────────────────────
    all_results = []
    batches = [contacts[i:i + BATCH_SIZE] for i in range(0, len(contacts), BATCH_SIZE)]

    for bi, batch in enumerate(batches, 1):
        batch_label = f"austin-intel-batch-{bi}"
        if args.verbose or len(batches) > 1:
            print(f"\nBatch {bi}/{len(batches)} — {len(batch)} contact(s)...")
        try:
            results = client.enrich_bulk(
                batch,
                batch_name=batch_label,
                enrich_work_email=enrich_work,
                enrich_phone=enrich_phone,
                enrich_personal_email=enrich_personal,
                verbose=args.verbose,
            )
        except RuntimeError as e:
            print(f"  ERROR on batch {bi}: {e}", file=sys.stderr)
            # Pad with error stubs so output aligns
            for c in batch:
                all_results.append(EnrichedContact(
                    ref_id=c.ref_id,
                    first_name=c.first_name,
                    last_name=c.last_name,
                    company_domain=c.company_domain,
                    company_name=c.company_name,
                    notes=c.notes,
                    enrichment_status="error",
                ))
            if bi < len(batches):
                time.sleep(args.batch_pause)
            continue

        all_results.extend(results)
        found_email = sum(1 for r in results if r.work_email)
        found_phone = sum(1 for r in results if r.mobile_phone or r.landline_phone)
        batch_credits = sum(r.credits_used for r in results)
        print(f"  email: {found_email}/{len(batch)}  phone: {found_phone}/{len(batch)}  credits: {batch_credits}")

        if bi < len(batches):
            time.sleep(args.batch_pause)

    # ── Write output ──────────────────────────────────────────────────────────
    write_csv(all_results, args.output)

    # ── Final summary ─────────────────────────────────────────────────────────
    total_email = sum(1 for r in all_results if r.work_email)
    total_phone = sum(1 for r in all_results if r.mobile_phone or r.landline_phone)
    total_personal = sum(1 for r in all_results if r.personal_email)
    total_credits = sum(r.credits_used for r in all_results)

    print("\n" + "-"*50)
    print(f"Results: {total_email}/{n} work email | {total_phone}/{n} phone | {total_personal}/{n} personal email")
    print(f"Credits used: {total_credits}")
    if total_email == 0 and n > 0:
        print("TIP: No emails found. Try adding --linkedin or --domain for better match accuracy.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
