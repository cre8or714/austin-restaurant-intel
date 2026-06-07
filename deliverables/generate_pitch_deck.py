"""
Generate a professional HTML pitch deck from all lead profiles.
Open the output in Chrome/Edge and use Print > Save as PDF.

Usage:
    python deliverables/generate_pitch_deck.py
Output:
    deliverables/austin-restaurant-intel-2026-06.html
"""

import importlib.util
import os
import sys
import datetime

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "..", "intel", "scripts", "profiles")
OUTPUT_DIR   = os.path.dirname(__file__)

LEAD_ORDER = [
    "lead_12_rainey_tavern",
    "lead_11_shoal_creek_roya",
    "lead_05_phoebes_diner",
    "lead_09_terrible_love",
    "lead_07_lima_criolla",
    "lead_06_rock_rose",
    "lead_13_raising_canes",
    "lead_03_applebees",
    "lead_10_moxies",
    "lead_01_e7th",
    "lead_02_tokami",
    "lead_04_farwest",
    "lead_08_lakeline",
]


def load(name):
    path = os.path.join(PROFILES_DIR, name + ".py")
    spec = importlib.util.spec_from_file_location("m", path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PROFILE


def v(field, default="—"):
    if isinstance(field, tuple):
        return field[0] if field[0] else default
    return str(field) if field else default


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def contact_html(name, title, phone, email, email_alt, linkedin, instagram, facebook, twitter, notes=""):
    rows = []
    if phone and phone != "—":
        rows.append(f'<tr><td class="cl">Phone</td><td>{esc(phone)}</td></tr>')
    if email and email != "—":
        rows.append(f'<tr><td class="cl">Email</td><td>{esc(email)}</td></tr>')
    if email_alt and email_alt != "—":
        rows.append(f'<tr><td class="cl">Email (alt)</td><td>{esc(email_alt)}</td></tr>')
    if linkedin and linkedin != "—":
        rows.append(f'<tr><td class="cl">LinkedIn</td><td>{esc(linkedin)}</td></tr>')
    if instagram and instagram != "—":
        rows.append(f'<tr><td class="cl">Instagram</td><td>{esc(instagram)}</td></tr>')
    if facebook and facebook != "—":
        rows.append(f'<tr><td class="cl">Facebook</td><td>{esc(facebook)}</td></tr>')
    if twitter and twitter != "—":
        rows.append(f'<tr><td class="cl">Twitter/X</td><td>{esc(twitter)}</td></tr>')
    if notes:
        rows.append(f'<tr><td class="cl">Note</td><td><em>{esc(notes)}</em></td></tr>')
    table = "<table class='ct'>" + "".join(rows) + "</table>" if rows else ""
    return f"""
<div class="contact-card">
  <div class="contact-name">{esc(name)}</div>
  <div class="contact-title">{esc(title)}</div>
  {table}
</div>"""


def profile_html(p):
    lead_id   = p.get("lead_id", "")
    biz       = esc(v(p.get("business_name")))
    concept   = esc(v(p.get("concept_type")))
    founded   = esc(v(p.get("founded")))
    loc_count = esc(v(p.get("location_count")))
    employees = esc(v(p.get("employee_estimate")))
    revenue   = esc(v(p.get("revenue_estimate")))
    rev_note  = esc(p.get("revenue_methodology", ""))
    sqft      = esc(v(p.get("sq_footage")))
    est_open  = esc(v(p.get("estimated_open")))
    website   = esc(v(p.get("website")))
    ig_biz    = esc(v(p.get("instagram_business")))
    signal    = esc(p.get("signal_type", ""))
    why       = esc(p.get("why_this_matters", ""))
    vendors   = esc(p.get("vendor_categories", ""))
    notes     = esc(p.get("notes", ""))
    permit_addr = esc(p.get("permit_address", ""))
    permit_date = esc(p.get("permit_date", ""))
    permit_desc = esc(p.get("permit_description", ""))

    # Locations
    loc_list = v(p.get("location_list"))
    loc_items = ""
    if loc_list and loc_list != "—":
        for i, loc in enumerate(loc_list.split("|"), 1):
            loc = loc.strip()
            if loc:
                loc_items += f"<li>{esc(loc)}</li>"

    # Bio
    dm_bio = esc(v(p.get("dm_bio")))

    # Contacts
    contacts_html = ""

    dm_name = v(p.get("dm_name"))
    if dm_name and dm_name != "—":
        contacts_html += contact_html(
            dm_name,
            v(p.get("dm_title")),
            v(p.get("dm_phone")),
            v(p.get("dm_email")),
            v(p.get("dm_email_alt")),
            v(p.get("dm_linkedin")),
            v(p.get("dm_instagram")),
            v(p.get("dm_facebook")),
            v(p.get("dm_twitter")),
        )
    else:
        contacts_html += '<div class="no-dm">Decision maker not yet identified — see Notes below.</div>'

    c2 = v(p.get("contact_2_name"))
    if c2 and c2 != "—":
        contacts_html += contact_html(
            c2,
            v(p.get("contact_2_role")),
            v(p.get("contact_2_phone")),
            v(p.get("contact_2_email")),
            "—",
            v(p.get("contact_2_linkedin")),
            "—", "—", "—",
        )

    for extra in p.get("contacts", []):
        contacts_html += contact_html(
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

    signal_class = "signal-open" if "Open" in signal else ("signal-tabc" if "TABC" in signal else "signal-pre")

    return f"""
<div class="lead-page page-break">

  <div class="lead-header">
    <div class="lead-id">{esc(lead_id.upper())}</div>
    <div class="lead-title">{biz}</div>
    <div class="lead-concept">{concept}</div>
    <div class="signal-badge {signal_class}">{signal}</div>
  </div>

  <div class="two-col">

    <div class="col-left">
      <h3>Business Overview</h3>
      <table class="overview-table">
        <tr><td>In business since</td><td>{founded}</td></tr>
        <tr><td>Locations</td><td>{loc_count}</td></tr>
        <tr><td>Employees (est.)</td><td>{employees}</td></tr>
        <tr><td>Revenue (est.)</td><td>{revenue}</td></tr>
        <tr><td>Sq footage</td><td>{sqft}</td></tr>
        <tr><td>Est. open</td><td>{est_open}</td></tr>
        <tr><td>Website</td><td>{website}</td></tr>
        <tr><td>Instagram</td><td>{ig_biz}</td></tr>
      </table>
      {"<p class='rev-note'><em>" + rev_note + "</em></p>" if rev_note else ""}

      {"<h3>Location List</h3><ol class='loc-list'>" + loc_items + "</ol>" if loc_items else ""}

      <h3>The Opportunity</h3>
      {"<p>" + why + "</p>" if why else ""}
      {"<p><strong>Vendor categories:</strong> " + vendors + "</p>" if vendors else ""}
      {"<p class='notes-text'>" + notes + "</p>" if notes else ""}

      <h3>Permit Record</h3>
      <table class="overview-table">
        <tr><td>Address</td><td>{permit_addr}</td></tr>
        <tr><td>Filed</td><td>{permit_date}</td></tr>
        <tr><td>Description</td><td>{permit_desc}</td></tr>
      </table>
    </div>

    <div class="col-right">
      <h3>Decision Makers</h3>
      {contacts_html}
      {"<h3>Background</h3><p class='bio'>" + dm_bio + "</p>" if dm_bio and dm_bio != "—" else ""}
    </div>

  </div>
</div>"""


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Helvetica Neue', Arial, sans-serif;
  font-size: 10.5pt;
  color: #1a1a2e;
  background: #fff;
}

/* ── Cover page ─────────────────────────────────────── */
.cover {
  height: 100vh;
  background: #0f2044;
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 80px;
  page-break-after: always;
}
.cover-eyebrow { font-size: 11pt; letter-spacing: 3px; text-transform: uppercase; color: #5b9bd5; margin-bottom: 24px; }
.cover-title   { font-size: 42pt; font-weight: 700; line-height: 1.1; margin-bottom: 20px; }
.cover-sub     { font-size: 14pt; color: #a0b4cc; margin-bottom: 48px; max-width: 600px; line-height: 1.5; }
.cover-meta    { font-size: 10pt; color: #6080a0; border-top: 1px solid #2a4060; padding-top: 24px; }
.cover-meta span { margin-right: 40px; }

/* ── Summary table page ──────────────────────────────── */
.summary-page {
  padding: 48px;
  page-break-after: always;
}
.summary-page h2 { font-size: 18pt; color: #0f2044; margin-bottom: 8px; }
.summary-page p  { color: #555; margin-bottom: 24px; font-size: 10pt; }

.summary-table { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
.summary-table th {
  background: #0f2044; color: #fff;
  padding: 8px 10px; text-align: left; font-weight: 600;
}
.summary-table td { padding: 7px 10px; border-bottom: 1px solid #e8edf2; vertical-align: top; }
.summary-table tr:nth-child(even) td { background: #f7f9fc; }
.summary-table .badge-open  { background: #d4edda; color: #155724; padding: 2px 7px; border-radius: 10px; font-size: 8.5pt; white-space: nowrap; }
.summary-table .badge-tabc  { background: #fff3cd; color: #856404; padding: 2px 7px; border-radius: 10px; font-size: 8.5pt; white-space: nowrap; }
.summary-table .badge-pre   { background: #f8d7da; color: #721c24; padding: 2px 7px; border-radius: 10px; font-size: 8.5pt; white-space: nowrap; }

/* ── Lead pages ──────────────────────────────────────── */
.lead-page {
  padding: 40px 48px;
  min-height: 100vh;
}
.page-break { page-break-before: always; }

.lead-header { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 3px solid #0f2044; }
.lead-id     { font-size: 8pt; letter-spacing: 2px; text-transform: uppercase; color: #5b9bd5; margin-bottom: 4px; }
.lead-title  { font-size: 22pt; font-weight: 700; color: #0f2044; line-height: 1.1; margin-bottom: 6px; }
.lead-concept{ font-size: 11pt; color: #555; margin-bottom: 10px; }

.signal-badge {
  display: inline-block; padding: 4px 12px; border-radius: 12px;
  font-size: 8.5pt; font-weight: 600; letter-spacing: 0.5px;
}
.signal-open { background: #d4edda; color: #155724; }
.signal-tabc { background: #fff3cd; color: #856404; }
.signal-pre  { background: #f8d7da; color: #721c24; }

/* ── Two column layout ───────────────────────────────── */
.two-col    { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }
.col-left h3, .col-right h3 {
  font-size: 9pt; font-weight: 700; text-transform: uppercase;
  letter-spacing: 1.5px; color: #5b9bd5; margin: 20px 0 8px;
  border-bottom: 1px solid #e8edf2; padding-bottom: 4px;
}
.col-left h3:first-child, .col-right h3:first-child { margin-top: 0; }

/* ── Overview table ──────────────────────────────────── */
.overview-table { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
.overview-table td { padding: 5px 0; border-bottom: 1px solid #f0f3f7; vertical-align: top; }
.overview-table td:first-child { color: #888; width: 42%; padding-right: 8px; }

.rev-note { font-size: 8.5pt; color: #777; margin-top: 8px; line-height: 1.4; }

/* ── Location list ───────────────────────────────────── */
.loc-list { padding-left: 16px; font-size: 9.5pt; }
.loc-list li { padding: 3px 0; border-bottom: 1px solid #f0f3f7; }

/* ── Contact cards ───────────────────────────────────── */
.contact-card {
  background: #f7f9fc;
  border: 1px solid #dde4ef;
  border-left: 3px solid #0f2044;
  border-radius: 4px;
  padding: 12px 14px;
  margin-bottom: 12px;
}
.contact-name  { font-size: 11pt; font-weight: 700; color: #0f2044; }
.contact-title { font-size: 9pt; color: #5b9bd5; margin-bottom: 8px; }
.ct            { width: 100%; border-collapse: collapse; font-size: 9pt; }
.ct td         { padding: 3px 0; vertical-align: top; }
.cl            { color: #888; width: 30%; padding-right: 6px; }
.no-dm         { font-style: italic; color: #888; font-size: 9.5pt; padding: 12px 0; }

/* ── Bio / notes ─────────────────────────────────────── */
.bio        { font-size: 9.5pt; color: #444; line-height: 1.5; }
.notes-text { font-size: 9pt; color: #666; font-style: italic; line-height: 1.5; margin-top: 6px; }

/* ── Print settings ──────────────────────────────────── */
@page { size: letter; margin: 0; }
@media print {
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .lead-page, .cover, .summary-page { page-break-inside: avoid; }
}
"""


def summary_row(p):
    biz    = esc(v(p.get("business_name")))
    lead_id = esc(p.get("lead_id", ""))
    signal = p.get("signal_type", "")
    dm     = esc(v(p.get("dm_name")))
    phone  = esc(v(p.get("dm_phone")))
    email  = esc(v(p.get("dm_email")))
    rev    = esc(v(p.get("revenue_estimate")))
    locs   = esc(v(p.get("location_count")))

    if "Open" in signal:
        badge = f'<span class="badge-open">Open</span>'
    elif "TABC" in signal or "Rebuild" in signal or "Confirmed" in signal:
        badge = f'<span class="badge-tabc">Active</span>'
    else:
        badge = f'<span class="badge-pre">Pre-Announcement</span>'

    return f"""<tr>
      <td><strong>{lead_id}</strong></td>
      <td>{biz}</td>
      <td>{badge}</td>
      <td>{locs}</td>
      <td>{rev}</td>
      <td>{dm}</td>
      <td>{phone}</td>
      <td>{email}</td>
    </tr>"""


def build_html(profiles):
    today = datetime.date.today().strftime("%B %d, %Y")
    month = datetime.date.today().strftime("%Y-%m")

    cover = f"""
<div class="cover">
  <div class="cover-eyebrow">Confidential Intelligence Brief</div>
  <div class="cover-title">Austin Restaurant<br>Intel</div>
  <div class="cover-sub">Early-signal lead profiles for new restaurant openings in Austin, TX — sourced from city permits, TABC filings, and Texas Comptroller data before any public announcement.</div>
  <div class="cover-meta">
    <span>Report date: {today}</span>
    <span>Leads: {len(profiles)}</span>
    <span>Market: Austin, TX (Travis County)</span>
    <span>Confidential — Not for redistribution</span>
  </div>
</div>"""

    rows = "".join(summary_row(p) for p in profiles)
    summary = f"""
<div class="summary-page">
  <h2>All Leads — At a Glance</h2>
  <p>Sorted by intelligence depth. Pre-announcement leads are the highest value — no public coverage, no incumbent vendor relationships.</p>
  <table class="summary-table">
    <thead>
      <tr>
        <th>ID</th><th>Business</th><th>Status</th><th>Locations</th>
        <th>Est. Revenue</th><th>Decision Maker</th><th>Phone</th><th>Email</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""

    leads = "".join(profile_html(p) for p in profiles)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Austin Restaurant Intel — {today}</title>
<style>{CSS}</style>
</head>
<body>
{cover}
{summary}
{leads}
</body>
</html>"""


def main():
    profiles = []
    for name in LEAD_ORDER:
        try:
            profiles.append(load(name))
        except Exception as e:
            print(f"  Skipping {name}: {e}")

    html = build_html(profiles)

    today = datetime.date.today().strftime("%Y-%m")
    filename = f"austin-restaurant-intel-{today}.html"
    out_path = os.path.join(OUTPUT_DIR, filename)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Done. Open in Chrome and print to PDF:")
    print(f"  {out_path}")


if __name__ == "__main__":
    main()
