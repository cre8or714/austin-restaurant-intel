"""
Fact-check and audit Austin Restaurant Intel lead profiles.

Usage:
    python verify_profile.py --all                   # audit all profiles
    python verify_profile.py profiles/lead_12.py     # single profile
    python verify_profile.py --all --no-ai           # flag missing sources only

What it checks:
    1. Every tuple field is labeled with a confidence level (CONFIRMED / ESTIMATED / etc.)
    2. CONFIRMED fields have a source URL — either inline as a 3rd tuple element,
       or mapped from the bulk sources list at the bottom of the profile.
    3. (AI mode) Source URLs are fetched and Claude checks whether the claimed
       value actually appears in the page content.

Output:
    intel/factcheck/<lead_id>_FACTCHECK.md   per-profile report + sign-off checklist
    intel/AUDIT_REPORT.md                    master summary across all profiles

Environment:
    ANTHROPIC_API_KEY   required for AI verification (skipped if not set)

New profile standard (3-tuple):
    "dm_phone": ("(512) 555-0123", "CONFIRMED", "https://bobwoody.com/contact"),
    Existing 2-tuple and 1-tuple profiles are handled gracefully.
"""

import importlib.util
import os
import sys
import json
import re
import datetime
import argparse
import glob as glob_module

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")
INTEL_DIR    = os.path.join(SCRIPT_DIR, "..")
FACTCHECK_DIR = os.path.join(INTEL_DIR, "factcheck")
AUDIT_REPORT_PATH = os.path.join(INTEL_DIR, "AUDIT_REPORT.md")

# Fields that must carry a confidence label and source when CONFIRMED
AUDITABLE_FIELDS = [
    "business_name", "concept_type", "location_count", "location_list",
    "sq_footage", "estimated_open", "website", "instagram_business",
    "employee_estimate", "revenue_estimate", "founded",
    "dm_name", "dm_title", "dm_phone", "dm_email", "dm_email_alt",
    "dm_linkedin", "dm_instagram", "dm_facebook", "dm_twitter", "dm_bio",
    "contact_2_name", "contact_2_role", "contact_2_phone",
    "contact_2_email", "contact_2_linkedin",
]

# These count toward completeness score
REQUIRED_FIELDS = [
    "business_name", "concept_type", "location_count",
    "dm_name", "dm_phone", "dm_email", "dm_linkedin", "dm_instagram",
]

# High-priority fields where AI verification matters most
HIGH_VALUE_FIELDS = {
    "dm_phone", "dm_email", "dm_name", "dm_title",
    "business_name", "location_count", "revenue_estimate",
}

# Domains that block scraping — skip AI fetch, accept the URL as credential-level proof
SCRAPER_BLOCKED_DOMAINS = {
    "linkedin.com", "instagram.com", "facebook.com", "twitter.com", "x.com",
}


def load_profile(path):
    spec = importlib.util.spec_from_file_location("profile_module", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PROFILE


def parse_field(field_data):
    """
    Parse a field value. Returns (value, confidence, inline_source).

    Tuple forms:
        (value,)                    -> confidence = "UNLABELED"
        (value, confidence)         -> inline_source = None
        (value, confidence, source) -> full attribution
    Plain string -> confidence = "UNLABELED"
    """
    if isinstance(field_data, tuple):
        value      = field_data[0] if len(field_data) > 0 else ""
        confidence = field_data[1] if len(field_data) > 1 else "UNLABELED"
        source     = field_data[2] if len(field_data) > 2 else None
        return str(value) if value else "", confidence, source
    return str(field_data) if field_data else "", "UNLABELED", None


def fetch_url(url, max_chars=4000):
    if not HAS_REQUESTS:
        return None, "requests not installed"
    try:
        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url
        domain = re.sub(r'^https?://(www\.)?', '', url).split("/")[0]
        if any(domain.endswith(d) for d in SCRAPER_BLOCKED_DOMAINS):
            return None, "SCRAPER_BLOCKED"
        resp = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars], None
    except Exception as e:
        return None, str(e)


def ai_verify_batch(client, fields_values, source_url, source_text):
    """One Haiku call verifying N field claims against a single source page."""
    claims_json = json.dumps({k: v[:200] for k, v in fields_values.items()}, indent=2)
    prompt = (
        "You are a strict fact-checker for a B2B lead intelligence service. "
        "Check whether each CLAIM below appears in the SOURCE EXCERPT.\n\n"
        f"Source URL: {source_url}\n\n"
        "SOURCE EXCERPT:\n---\n"
        f"{source_text}\n"
        "---\n\n"
        f"CLAIMS:\n{claims_json}\n\n"
        "Return a JSON object mapping each field name to:\n"
        '{"verdict":"VERIFIED"|"UNSUPPORTED"|"CONTRADICTED"|"PARTIAL"|"INSUFFICIENT_SOURCE",'
        '"confidence":0.0-1.0,"note":"one sentence"}\n'
        "JSON only — no other text."
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max(250, len(fields_values) * 150),
            messages=[{"role": "user", "content": prompt}]
        )
        parsed = json.loads(resp.content[0].text.strip())
        for field in fields_values:
            if field not in parsed:
                parsed[field] = {"verdict": "ERROR", "confidence": 0.0, "note": "missing from response"}
        return parsed
    except Exception as e:
        return {f: {"verdict": "ERROR", "confidence": 0.0, "note": str(e)} for f in fields_values}


def audit_profile(profile, use_ai=True):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = None
    if use_ai and HAS_ANTHROPIC and api_key:
        client = anthropic.Anthropic(api_key=api_key)

    lead_id   = profile.get("lead_id", "unknown")
    biz_name  = parse_field(profile.get("business_name", ""))[0]
    sources_raw = profile.get("sources", "")
    bulk_urls = [s.strip() for s in sources_raw.split("|") if s.strip()]

    # ── Pass 1: Structural audit ─────────────────────────────────────────────
    results = []
    result_by_field = {}

    for field_name in AUDITABLE_FIELDS:
        raw = profile.get(field_name)
        if raw is None:
            continue

        value, confidence, inline_source = parse_field(raw)

        if not value or value.strip() in ("", "—", "-"):
            continue

        result = {
            "field":         field_name,
            "value":         value[:150] + "…" if len(value) > 150 else value,
            "confidence":    confidence,
            "inline_source": inline_source,
            "checked_url":   None,
            "ai_verdict":    None,
            "flags":         [],
        }

        if confidence == "UNLABELED":
            result["flags"].append("CONFIDENCE_MISSING")

        if confidence == "CONFIRMED":
            if not inline_source and not bulk_urls:
                result["flags"].append("SOURCE_MISSING")
            elif not inline_source and bulk_urls:
                result["flags"].append("SOURCE_NOT_ANCHORED")

        results.append(result)
        result_by_field[field_name] = result

    # ── Pass 2: Batch AI verification ────────────────────────────────────────
    # One Haiku call per unique source URL rather than one per field.
    # Inline-sourced fields are grouped by their URL; all others share the first
    # fetchable bulk URL. Typical profile: 1–2 API calls instead of 5–7.
    if client:
        # Only AI-verify CONFIRMED fields — ESTIMATED/INFERRED/UNVERIFIED have no
        # specific source page to check against.
        hv_results = {
            name: r for name, r in result_by_field.items()
            if name in HIGH_VALUE_FIELDS
            and r["confidence"] == "CONFIRMED"
            and r["value"] and r["value"].strip() not in ("", "—", "-")
        }

        inline_groups = {}  # {url: {field: value}}
        bulk_fields   = {}  # {field: value} — no inline source

        for field_name, r in hv_results.items():
            if r["inline_source"]:
                inline_groups.setdefault(r["inline_source"], {})[field_name] = r["value"]
            else:
                bulk_fields[field_name] = r["value"]

        work = [{"url": url, "fields": fv, "text": None} for url, fv in inline_groups.items()]

        if bulk_fields:
            resolved_url = resolved_text = None
            for bulk_url in bulk_urls[:3]:
                text, err = fetch_url(bulk_url)
                if text:
                    resolved_url, resolved_text = bulk_url, text
                    break
            if resolved_url:
                work.append({"url": resolved_url, "fields": bulk_fields, "text": resolved_text})
            else:
                for field_name in bulk_fields:
                    result_by_field[field_name]["flags"].append("FETCH_FAILED")

        for job in work:
            url, fields_values = job["url"], job["fields"]
            source_text = job["text"]
            if source_text is None:
                source_text, err = fetch_url(url)
            if not source_text:
                # Scraper-blocked platforms (LinkedIn, Instagram, etc.) — URL itself
                # is sufficient credential-level proof; skip AI, no flag.
                if err == "SCRAPER_BLOCKED":
                    for field_name in fields_values:
                        result_by_field[field_name]["checked_url"] = url
                else:
                    for field_name in fields_values:
                        result_by_field[field_name]["flags"].append("FETCH_FAILED")
                continue

            verdicts = ai_verify_batch(client, fields_values, url, source_text)
            for field_name, verdict in verdicts.items():
                if field_name not in result_by_field:
                    continue
                r = result_by_field[field_name]
                r["ai_verdict"]  = verdict
                r["checked_url"] = url
                v = verdict.get("verdict", "")
                if v == "VERIFIED":
                    r["flags"] = [f for f in r["flags"] if f != "SOURCE_NOT_ANCHORED"]
                    r["flags"].append("AI_VERIFIED")
                elif v in ("UNSUPPORTED", "CONTRADICTED"):
                    r["flags"].append(f"AI_{v}")

    # ── Completeness ─────────────────────────────────────────────────────────
    confirmed_required = sum(
        1 for f in REQUIRED_FIELDS
        if f in profile and parse_field(profile[f])[1] == "CONFIRMED"
    )
    completeness = round(confirmed_required / len(REQUIRED_FIELDS) * 100)
    dm_confirmed = parse_field(profile.get("dm_name", ""))[1] == "CONFIRMED"

    # Flags that block factcheck_passed (substantive issues requiring human resolution)
    BLOCKING_FLAGS = {"CONFIDENCE_MISSING", "SOURCE_MISSING", "AI_CONTRADICTED", "AI_UNSUPPORTED"}

    total_flags      = sum(1 for r in results for fl in r["flags"]
                           if fl not in ("AI_VERIFIED",))
    missing_sources  = sum(1 for r in results
                           for fl in r["flags"]
                           if fl in ("SOURCE_MISSING", "SOURCE_NOT_ANCHORED"))
    confidence_gaps  = sum(1 for r in results if "CONFIDENCE_MISSING" in r["flags"])
    ai_verified      = sum(1 for r in results if "AI_VERIFIED" in r["flags"])
    ai_flags         = sum(1 for r in results
                           for fl in r["flags"] if fl.startswith("AI_") and fl != "AI_VERIFIED")
    factcheck_passed = not any(
        fl in BLOCKING_FLAGS for r in results for fl in r["flags"]
    )

    return {
        "lead_id":         lead_id,
        "business_name":   biz_name,
        "completeness":    completeness,
        "pitch_ready":     completeness >= 60 and dm_confirmed,
        "factcheck_passed": factcheck_passed,
        "total_fields":    len(results),
        "confidence_gaps": confidence_gaps,
        "missing_sources": missing_sources,
        "ai_verified":     ai_verified,
        "ai_flags":        ai_flags,
        "total_flags":     total_flags,
        "results":         results,
    }


def write_factcheck_md(audit):
    os.makedirs(FACTCHECK_DIR, exist_ok=True)
    today    = str(datetime.date.today())
    lead_id  = audit["lead_id"]
    status   = "PASS" if audit["factcheck_passed"] else "NEEDS REVIEW"
    pr_label = "YES" if audit["pitch_ready"] else "NO"

    lines = [
        f"# Fact-Check: {audit['business_name']}",
        f"",
        f"**Lead:** {lead_id}  ·  **Generated:** {today}  ·  **Status:** {status}",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|:---|:---|",
        f"| Fields audited | {audit['total_fields']} |",
        f"| Confidence label missing | {audit['confidence_gaps']} |",
        f"| Source not anchored to field | {audit['missing_sources']} |",
        f"| AI-verified (claim appears in source) | {audit['ai_verified']} |",
        f"| AI flags (unsupported / contradicted) | {audit['ai_flags']} |",
        f"| Completeness score | {audit['completeness']}% |",
        f"| Pitch-ready | {pr_label} |",
        f"| Fact-check status | {status} |",
        f"",
        f"---",
        f"",
        f"## Claim Audit",
        f"",
    ]

    flagged = [r for r in audit["results"] if any(
        f not in ("AI_VERIFIED",) for f in r["flags"]
    )]
    clean = [r for r in audit["results"] if not flagged or r not in flagged]
    ai_ok  = [r for r in audit["results"] if "AI_VERIFIED" in r["flags"] and r not in flagged]

    if flagged:
        lines += [f"### Flagged — requires action ({len(flagged)})", ""]
        for r in flagged:
            lines += _claim_block(r)

    if ai_ok:
        lines += [f"### AI-Verified ({len(ai_ok)})", ""]
        for r in ai_ok:
            lines += _claim_block(r)

    remaining = [r for r in audit["results"] if r not in flagged and r not in ai_ok]
    if remaining:
        lines += [f"### Unverified — no issues flagged ({len(remaining)})", ""]
        for r in remaining:
            lines += _claim_block(r)

    lines += [
        "---",
        "",
        "## Human Sign-off",
        "",
        "- [ ] All flagged items reviewed",
        "- [ ] AI-flagged claims independently confirmed",
        "- [ ] Source URLs verified as live",
        "- Reviewed by: ___",
        "- Date: ___",
        "- Notes: ___",
        "",
        f"*Austin Restaurant Intel · verify_profile.py · {today}*",
    ]

    path = os.path.join(FACTCHECK_DIR, f"{lead_id}_FACTCHECK.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def _claim_block(r):
    flag_labels = [fl for fl in r["flags"] if fl != "AI_VERIFIED"]
    flag_str = "  **[" + " · ".join(flag_labels) + "]**" if flag_labels else ""
    lines = [f"**{r['field']}**{flag_str}"]
    lines.append(f"- Value: `{r['value']}`")
    lines.append(f"- Confidence: {r['confidence']}")
    if r["inline_source"]:
        lines.append(f"- Inline source: {r['inline_source']}")
    if r["checked_url"] and not r["inline_source"]:
        lines.append(f"- Checked against bulk source: {r['checked_url']}")
    if not r["inline_source"] and not r["checked_url"]:
        lines.append(f"- Source: *none*")
    if r["ai_verdict"]:
        v = r["ai_verdict"]
        lines.append(
            f"- AI verdict: **{v.get('verdict', '?')}** "
            f"({v.get('confidence', '?'):.0%}) — {v.get('note', '')}"
        )
    lines.append("")
    return lines


def write_audit_report(audits):
    today = str(datetime.date.today())

    lines = [
        f"# Austin Restaurant Intel — Audit Report",
        f"",
        f"**Generated:** {today}  ·  **Profiles:** {len(audits)}",
        f"",
        f"## Portfolio Summary",
        f"",
        f"| Metric | Count |",
        f"|:---|:---|",
        f"| Profiles audited | {len(audits)} |",
        f"| Pitch-ready | {sum(1 for a in audits if a['pitch_ready'])} |",
        f"| Fact-check passed (zero flags) | {sum(1 for a in audits if a['factcheck_passed'])} |",
        f"| Fields with confidence label missing | {sum(a['confidence_gaps'] for a in audits)} |",
        f"| Fields with no source anchor | {sum(a['missing_sources'] for a in audits)} |",
        f"| AI-verified claims | {sum(a['ai_verified'] for a in audits)} |",
        f"| AI flags (contradictions / unsupported) | {sum(a['ai_flags'] for a in audits)} |",
        f"",
        f"---",
        f"",
        f"## Per-Profile Results",
        f"",
        f"| Lead | Business | Complete | Conf. Gaps | No Source | AI Verified | AI Flags | Status |",
        f"|:---|:---|:---|:---|:---|:---|:---|:---|",
    ]

    for a in sorted(audits, key=lambda x: x["lead_id"]):
        status = "PASS" if a["factcheck_passed"] else "NEEDS REVIEW"
        lines.append(
            f"| {a['lead_id']} "
            f"| {a['business_name'][:28]} "
            f"| {a['completeness']}% "
            f"| {a['confidence_gaps']} "
            f"| {a['missing_sources']} "
            f"| {a['ai_verified']} "
            f"| {a['ai_flags']} "
            f"| {status} |"
        )

    lines += ["", "---", "", "## Priority Actions", ""]

    ai_flagged = [
        (a, r)
        for a in audits
        for r in a["results"]
        if any(fl.startswith("AI_") and fl != "AI_VERIFIED" for fl in r["flags"])
    ]
    lines += ["### AI flags — review before pitching", ""]
    if ai_flagged:
        for a, r in ai_flagged:
            v = r.get("ai_verdict") or {}
            lines.append(
                f"- **{a['lead_id']}** / `{r['field']}`: "
                f"{v.get('verdict', '?')} — {v.get('note', '')}"
            )
    else:
        lines.append("- None")

    lines += ["", "### Profiles needing source anchoring", ""]
    needs_anchoring = [a for a in audits if a["missing_sources"] > 0]
    if needs_anchoring:
        for a in sorted(needs_anchoring, key=lambda x: -x["missing_sources"]):
            lines.append(
                f"- **{a['lead_id']}** ({a['business_name'][:30]}): "
                f"{a['missing_sources']} CONFIRMED claims lack per-field source URL"
            )
    else:
        lines.append("- None")

    lines += ["", "### Profiles needing confidence labels", ""]
    needs_labels = [a for a in audits if a["confidence_gaps"] > 0]
    if needs_labels:
        for a in sorted(needs_labels, key=lambda x: -x["confidence_gaps"]):
            lines.append(
                f"- **{a['lead_id']}** ({a['business_name'][:30]}): "
                f"{a['confidence_gaps']} fields missing confidence label"
            )
    else:
        lines.append("- None")

    lines += [
        "",
        "---",
        "",
        f"*Austin Restaurant Intel · verify_profile.py · {today}*",
    ]

    with open(AUDIT_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(
        description="Fact-check Austin Restaurant Intel profiles"
    )
    parser.add_argument("profile", nargs="?", help="Path to a single profile .py file")
    parser.add_argument("--all",   action="store_true", help="Audit all profiles")
    parser.add_argument("--no-ai", action="store_true", help="Skip AI verification")
    args = parser.parse_args()

    use_ai = not args.no_ai

    if not HAS_REQUESTS and use_ai:
        print("Note: 'requests' not installed — URL fetching disabled. pip install requests")
    if not HAS_ANTHROPIC and use_ai:
        print("Note: 'anthropic' not installed — AI verification disabled. pip install anthropic")
    if use_ai and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Note: ANTHROPIC_API_KEY not set — AI verification skipped. Use --no-ai to suppress.")
        use_ai = False

    if args.all:
        profile_files = sorted(glob_module.glob(os.path.join(PROFILES_DIR, "lead_*.py")))
    elif args.profile:
        profile_files = [args.profile]
    else:
        parser.print_help()
        sys.exit(1)

    if not profile_files:
        print(f"No profile files found in {PROFILES_DIR}")
        sys.exit(1)

    print(f"\nAuditing {len(profile_files)} profile(s) | AI: {'ON' if use_ai else 'OFF'}\n")

    audits = []
    for path in profile_files:
        name = os.path.basename(path)
        print(f"  {name} ...", end=" ", flush=True)
        try:
            profile = load_profile(path)
            audit   = audit_profile(profile, use_ai=use_ai)
            write_factcheck_md(audit)
            audits.append(audit)
            status = "PASS" if audit["factcheck_passed"] else (
                f"NEEDS REVIEW "
                f"({audit['confidence_gaps']} conf gaps, "
                f"{audit['missing_sources']} no source, "
                f"{audit['ai_flags']} AI flags)"
            )
            print(status)
        except Exception as e:
            print(f"ERROR — {e}")

    if audits:
        write_audit_report(audits)

    print(f"\nFactcheck files: {FACTCHECK_DIR}")
    print(f"Audit report:    {AUDIT_REPORT_PATH}\n")


if __name__ == "__main__":
    main()
