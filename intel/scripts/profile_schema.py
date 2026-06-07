"""
Standard profile schema for Austin Restaurant Intel leads.

Every field carries a confidence level:
  CONFIRMED  — sourced and verified
  ESTIMATED  — model-based or inferred from industry benchmarks
  INFERRED   — logical deduction from confirmed data (e.g. email pattern)
  UNVERIFIED — found in a public record but not independently confirmed
  NOT_FOUND  — exhausted available sources; gap acknowledged

Completeness score = CONFIRMED fields / total required fields.
A profile is pitch-ready at >= 60% completeness with DM name confirmed.

─── Source anchoring (required for CONFIRMED fields) ────────────────────────
Use a 3-tuple: (value, confidence, source_url)

    "dm_phone": ("(512) 555-0123", "CONFIRMED", "https://bobwoody.com/contact"),
    "dm_email": ("bob@example.com", "INFERRED",  "https://bobwoody.com"),

The source_url must be the specific page where the value was found.
If a value appears across multiple pages, use the most authoritative one.
Bulk sources in the `sources` field are supplemental — not a substitute.

verify_profile.py enforces this: any CONFIRMED field without a source_url
is flagged SOURCE_NOT_ANCHORED. Run it before marking a profile pitch-ready.
────────────────────────────────────────────────────────────────────────────
"""

CONFIDENCE = {
    "CONFIRMED":   "✓",
    "ESTIMATED":   "~",
    "INFERRED":    "~",
    "UNVERIFIED":  "?",
    "NOT_FOUND":   "✗",
}

# Required fields counted toward completeness score
REQUIRED_FIELDS = [
    "business_name",
    "concept_type",
    "location_count",
    "dm_name",
    "dm_phone",
    "dm_email",
    "dm_linkedin",
    "dm_instagram",
]

def empty_profile():
    """Return a blank profile dict with all fields."""
    return {
        # ── Lead metadata ──────────────────────────────────────────────────
        "lead_id":              "",   # e.g. "lead-05"
        "permit_address":       "",
        "permit_date":          "",
        "permit_description":   "",
        "signal_type":          "",   # Pre-announcement | TABC Filed | Open
        "profile_date":         "",

        # ── Business ───────────────────────────────────────────────────────
        "business_name":        ("", "NOT_FOUND"),
        "concept_type":         ("", "NOT_FOUND"),   # Full-service / Bar / QSR / Coffee / etc.
        "location_count":       ("", "NOT_FOUND"),   # int or string like "~30"
        "location_list":        ("", "NOT_FOUND"),   # pipe-separated addresses
        "sq_footage":           ("", "NOT_FOUND"),
        "estimated_open":       ("", "NOT_FOUND"),
        "website":              ("", "NOT_FOUND"),
        "instagram_business":   ("", "NOT_FOUND"),
        "employee_estimate":    ("", "NOT_FOUND"),
        "revenue_estimate":     ("", "NOT_FOUND"),
        "revenue_methodology":  "",   # plain text, no confidence tag

        # ── Decision Maker ─────────────────────────────────────────────────
        "dm_name":              ("", "NOT_FOUND"),
        "dm_title":             ("", "NOT_FOUND"),
        "dm_phone":             ("", "NOT_FOUND"),
        "dm_email":             ("", "NOT_FOUND"),
        "dm_email_alt":         ("", "NOT_FOUND"),
        "dm_linkedin":          ("", "NOT_FOUND"),
        "dm_instagram":         ("", "NOT_FOUND"),   # personal handle
        "dm_facebook":          ("", "NOT_FOUND"),
        "dm_twitter":           ("", "NOT_FOUND"),
        "dm_bio":               ("", "NOT_FOUND"),

        # ── Additional contacts ────────────────────────────────────────────
        "contact_2_name":       ("", "NOT_FOUND"),
        "contact_2_role":       ("", "NOT_FOUND"),
        "contact_2_phone":      ("", "NOT_FOUND"),
        "contact_2_email":      ("", "NOT_FOUND"),
        "contact_2_linkedin":   ("", "NOT_FOUND"),

        # ── Opportunity ────────────────────────────────────────────────────
        "why_this_matters":     "",
        "vendor_categories":    "",   # comma-separated: food dist, insurance, POS, etc.
        "notes":                "",
        "sources":              "",   # pipe-separated URLs
    }
