# Deliverables Workspace

This workspace owns the buyer-facing artifacts: the lead profile template and the monthly brief format.

The profile template is the sales asset. Design quality matters more here than anywhere else in the project. Samples in /samples are what we show on pitch calls.

---

## Canonical Brief Format

One brief per metro per month. The current canonical brief is always in /deliverables/samples/. Prior versions are in /deliverables/archive/. Two live briefs is a defect.

### Three-tier structure (standardized — do not drift from this)

**Standing Portfolio Targets**
- Multi-venue operators whose most recent signal predates the current 45-day window.
- NOT window-bound. "Before public announcement" claim is dropped for this section.
- Labeled explicitly as Standing Portfolio — never mixed into the Active tier.
- Sorted by portfolio scale (combined venues and estimated revenue, largest first).

**Active**
- Window-qualified (most recent signal within the trailing 45-day window).
- MUST pass the no-dig gate: named DM with at least one confirmed contact, OR a named
  back-channel route to the operator.
- Sorted within tier by Intent + Opportunity (1–5 each), Intent as tiebreaker on ties.
- Intent score: readiness to act (1 = early signal only / 5 = opening imminent).
- Opportunity score: deal value to vendor (1 = single small location / 5 = portfolio scale).

**Watch**
- Window-qualified signal but operator or decision-maker not yet resolved.
- Explicitly labeled not-yet-actionable.
- Each card states the specific next enrichment action needed to move to Active.
- Do NOT include contact info in Watch cards — it implies actionability.

### Within-tier lead format (Active and Standing Portfolio full pages)
- Lead header: tier tag, title, concept/address, signal badges, I/O scores (Active only)
- Two-column layout: left = business overview + locations + opportunity + permit; right = DMs + background
- Confidence labels on all contact info: confirmed / *inferred* / *unverified*
- First move box: one specific, immediately executable action
- Intel note: source attribution for any non-obvious claim

### Watch cards (compact format)
- Title, concept, address
- Signal type + estimated revenue + estimated open
- Permit details
- Next enrichment action (specific, not generic)

### Naming and archiving
- Canonical brief file: austin-intel-brief-[month]-[year].html in /deliverables/samples/
- Archive: prior brief moved to /deliverables/archive/ on regeneration (never deleted)
- PDF export lives alongside the HTML in /deliverables/samples/
