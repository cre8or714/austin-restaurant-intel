# 0004 — Add FullEnrich to Contact Enrichment Pipeline

**Date:** 2026-06-06
**Status:** Approved — testing phase
**Decider:** Chris

---

## Decision

Add FullEnrich waterfall API as a supplementary contact enrichment layer in the Austin Restaurant Intel pipeline, running after Apollo to fill email, phone, and LinkedIn gaps.

---

## Context

Apollo's free people-search tier returns presence flags but not actual contact data. Apollo enrichment (credits) sometimes finds nothing for restaurant operators who aren't in its database. The pipeline currently has confirmed contacts for only ~50% of leads.

FullEnrich queries 20+ data providers in cascade (Lusha, Apollo, ZoomInfo, Hunter, Datagma, and others) and charges only on successful matches:
- Work email: 1 credit
- Personal email: 3 credits
- Mobile phone: 10 credits
- Not found: 0 credits

This fills the "operator unknown" gap for leads where we have a name but no contact data, without paying credits upfront for likely misses.

---

## Constraints

- **Validation phase**: use only on active qualified leads (18 qualifying per 45-day window) — no bulk-enriching cold lists
- **Phone enrichment** (10 credits/contact) is opt-in only via `--phone` flag; default run enriches work email only
- **No hardcoded API key** — key stored in `FULLENRICH_API_KEY` env var only
- **Credits are real money** — run a preview dry-run before any batch over 20 contacts
- **Re-evaluate at first paying client** — if paying clients want enriched profiles, decide then whether to enrich all 18 leads per cycle or just the top 5 by score

---

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| Apollo enrichment only | Misses operators not in Apollo; already confirmed gaps |
| Manual LinkedIn research | Too slow for 18 leads per 45-day cycle |
| Hunter.io alone | Email-only, no phone; no waterfall |
| FullEnrich + immediate scale | Premature — no paying clients yet; test first |

---

## Integration

Script: `intel/scripts/fullenrich_enrichment.py`

Pipeline position:
1. `apollo_people_search.py` — presence flags (free)
2. `apollo_vendor_contacts.py` — vendor contact search (free tier)
3. `apollo_people_enrichment.py` — Apollo enrichment (credits, selective)
4. **`fullenrich_enrichment.py`** ← new, fills remaining gaps
5. `build_profile.py` — assemble enriched profile .md
6. `verify_profile.py` — confidence label audit

---

## Success Criteria for This Test

Run FullEnrich against the 8 NEEDS REVIEW leads that have a known operator name. Declare success if:
- ≥3/8 return a work email with `valid` or `risky` confidence
- Total credit spend < 20 credits for the test batch

---

## Reference

See `intel/enrichment-playbook.md` for pipeline detail and confidence tier definitions.
Reference `decisions/0003` before any scope expansion beyond the 18-lead qualifying window.
