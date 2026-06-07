"""
Generate a professional lead profile from a profile data dict.

Usage:
    python build_profile.py profiles/lead_05_phoebes_diner.py
"""

import importlib.util
import os
import sys
import datetime

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "enriched")


def v(field, default="—"):
    """Return value from (value, confidence) tuple or plain string."""
    if isinstance(field, tuple):
        return field[0] if field[0] else default
    return str(field) if field else default


def contact_block(name, title, phone, email, email_alt, linkedin, instagram, facebook, twitter, notes=""):
    lines = []
    lines.append(f"**{name}**  ·  {title}")
    lines.append("")
    if phone and phone != "—":
        lines.append(f"- Phone: {phone}")
    if email and email != "—":
        lines.append(f"- Email: {email}")
    if email_alt and email_alt != "—":
        lines.append(f"- Email (alt): {email_alt}")
    if linkedin and linkedin != "—":
        lines.append(f"- LinkedIn: {linkedin}")
    if instagram and instagram != "—":
        lines.append(f"- Instagram: {instagram}")
    if facebook and facebook != "—":
        lines.append(f"- Facebook: {facebook}")
    if twitter and twitter != "—":
        lines.append(f"- Twitter/X: {twitter}")
    if notes:
        lines.append(f"- *{notes}*")
    return lines


def build(profile, write=True):
    biz       = v(profile.get("business_name"), "Unknown Business")
    concept   = v(profile.get("concept_type"))
    loc_count = v(profile.get("location_count"))
    loc_list  = v(profile.get("location_list"))
    founded   = v(profile.get("founded"))
    employees = v(profile.get("employee_estimate"))
    revenue   = v(profile.get("revenue_estimate"))
    rev_note  = profile.get("revenue_methodology", "")
    sqft      = v(profile.get("sq_footage"))
    est_open  = v(profile.get("estimated_open"))
    website   = v(profile.get("website"))
    ig_biz    = v(profile.get("instagram_business"))
    signal    = profile.get("signal_type", "")
    permit_addr = profile.get("permit_address", "")
    permit_date = profile.get("permit_date", "")
    permit_desc = profile.get("permit_description", "")
    why       = profile.get("why_this_matters", "")
    vendors   = profile.get("vendor_categories", "")
    notes     = profile.get("notes", "")
    sources   = profile.get("sources", "")

    dm_name    = v(profile.get("dm_name"))
    dm_title   = v(profile.get("dm_title"))
    dm_phone   = v(profile.get("dm_phone"))
    dm_email   = v(profile.get("dm_email"))
    dm_email2  = v(profile.get("dm_email_alt"))
    dm_li      = v(profile.get("dm_linkedin"))
    dm_ig      = v(profile.get("dm_instagram"))
    dm_fb      = v(profile.get("dm_facebook"))
    dm_tw      = v(profile.get("dm_twitter"))
    dm_bio     = v(profile.get("dm_bio"))

    c2_name    = v(profile.get("contact_2_name"))
    c2_title   = v(profile.get("contact_2_role"))
    c2_phone   = v(profile.get("contact_2_phone"))
    c2_email   = v(profile.get("contact_2_email"))
    c2_li      = v(profile.get("contact_2_linkedin"))

    lead_id    = profile.get("lead_id", "")
    today      = profile.get("profile_date", str(datetime.date.today()))

    lines = []

    # ── Header ───────────────────────────────────────────────────────────────
    lines += [
        f"# {biz}",
        f"",
        f"**{concept}**",
        f"",
        f"---",
        f"",
    ]

    # ── At a Glance ──────────────────────────────────────────────────────────
    lines += [
        f"## At a Glance",
        f"",
        f"| | |",
        f"|:---|:---|",
        f"| Signal | {signal} |",
        f"| In business since | {founded} |",
        f"| Locations | {loc_count} |",
        f"| Estimated employees | {employees} |",
        f"| Estimated annual revenue | {revenue} |",
        f"| Square footage (new space) | {sqft} |",
        f"| Estimated open | {est_open} |",
        f"| Website | {website} |",
        f"| Instagram | {ig_biz} |",
        f"",
    ]
    if rev_note:
        lines += [f"> *Revenue estimate: {rev_note}*", f""]

    # ── Locations ────────────────────────────────────────────────────────────
    if loc_list and loc_list != "—":
        lines += ["---", "", "## Locations", ""]
        for i, loc in enumerate(loc_list.split("|"), 1):
            loc = loc.strip()
            if loc:
                lines += [f"{i}. {loc}"]
        lines += [""]

    # ── Decision Makers ──────────────────────────────────────────────────────
    lines += ["---", "", "## Decision Makers", ""]

    if dm_name and dm_name != "—":
        lines += contact_block(dm_name, dm_title, dm_phone, dm_email, dm_email2, dm_li, dm_ig, dm_fb, dm_tw)
        lines += [""]
        if dm_bio and dm_bio != "—":
            lines += [f"**Background:** {dm_bio}", ""]

    if c2_name and c2_name != "—":
        lines += ["### Additional Contact", ""]
        lines += contact_block(c2_name, c2_title, c2_phone, c2_email, "—", c2_li, "—", "—", "—")
        lines += [""]

    # Render any extra contacts from the `contacts` list
    for extra in profile.get("contacts", []):
        lines += ["### Additional Contact", ""]
        lines += contact_block(
            extra.get("name", "—"),
            extra.get("title", "—"),
            extra.get("phone", "—"),
            extra.get("email", "—"),
            extra.get("email_alt", "—"),
            extra.get("linkedin", "—"),
            extra.get("instagram", "—"),
            extra.get("facebook", "—"),
            extra.get("twitter", "—"),
            extra.get("notes", ""),
        )
        lines += [""]

    if dm_name == "—":
        lines += [
            "**Decision maker not yet identified** — this is a pre-announcement lead.",
            "",
            f"**To identify:** {notes}",
            "",
        ]

    # ── The Opportunity ──────────────────────────────────────────────────────
    lines += ["---", "", "## The Opportunity", ""]
    if why:
        lines += [why, ""]
    if vendors:
        lines += [f"**Relevant vendor categories:** {vendors}", ""]
    if notes and dm_name != "—":
        lines += [f"**Notes:** {notes}", ""]

    # ── Permit Record ────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## Permit Record",
        "",
        f"| | |",
        f"|:---|:---|",
        f"| Address | {permit_addr} |",
        f"| Filed | {permit_date} |",
        f"| Description | {permit_desc} |",
        f"",
    ]

    # ── Sources ──────────────────────────────────────────────────────────────
    if sources:
        lines += ["---", "", "## Sources", ""]
        for src in sources.split("|"):
            src = src.strip()
            if src:
                lines += [f"- {src}"]
        lines += [""]

    lines += [
        "---",
        f"*Lead ID: {lead_id}  ·  Profile date: {today}  ·  Austin Restaurant Intel*",
    ]

    content = "\n".join(lines)

    if write:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        slug = (lead_id or biz.lower().replace(" ", "-"))
        slug = "".join(c for c in slug if c.isalnum() or c in "-_")[:40]
        date_prefix = today[:7]
        filename = f"{date_prefix}_{slug}_profile.md"
        path = os.path.join(OUTPUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  Written: {filename}")

    return content


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python build_profile.py profiles/lead_XX.py")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("profile_module", sys.argv[1])
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    build(mod.PROFILE)
