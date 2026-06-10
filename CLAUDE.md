# Austin Restaurant Intel

## What this project is
A B2B lead intelligence service. Unit of production: one enriched profile of a restaurant opening in Austin, TX. Each profile is sold to multiple non-competing vendor categories (food distributors, POS resellers, commercial insurance, linens, signage, etc.) on category-exclusive monthly retainers.

## Current phase: VALIDATION
Zero paying clients. Goal: produce 5-10 sample profiles, close 2-3 founding vendors in Austin, prove unit economics before any scaling.

## Operator constraints (immutable)
- Solo operator, 15-20 hrs/week
- Liveaboard cruiser, intermittent connectivity
- Strength: sales. Primary risk: temptation to over-build before selling.

## Workspaces
- /strategy — Business model, decisions, pricing, buyer definition
- /intel — Data sources, scripts, raw pulls, enriched profiles
- /deliverables — Profile and brief templates, sample outputs
- /sales — Target vendors, pitch materials, outreach, pipeline

## Routing
| Task | Go to | Read |
|------|-------|------|
| Strategic decision or business question | /strategy | CONTEXT.md + relevant doc |
| Pull or enrich data | /intel | CONTEXT.md, sources.md, enrichment-playbook.md |
| Build a sample profile or brief | /deliverables | CONTEXT.md, profile-template |
| Pitch, outreach, or pipeline work | /sales | CONTEXT.md, target-vendors.md |

## Naming conventions
- Raw data: YYYY-MM-DD_source-name.csv
- Enriched profiles: YYYY-MM_restaurant-name_profile.md
- Decision records: NNNN-title.md (sequential)
- Outreach drafts: vendor-name_outreach_vN.md

## Discipline rules
- No tooling work in a week with zero sales conversations
- No new tech in the stack without a /strategy/decisions/ entry
- Enrichment stays human until there are paying clients
- Demo first, operation second
- Reference /strategy/decisions/0003 before agreeing to any scope expansion

---
## Deliverable quality gates (hard — a brief that violates any of these does not ship)

### One canonical brief
- Exactly one current brief exists per metro per month. On regeneration, the prior
  version moves to /deliverables/archive/ — never presented alongside the new one.
  Two live briefs is a defect, not a variant.
- All sales materials (scripts, target lists) are generated FROM the current canonical
  brief. Any number asserted in a script ("owner contacts for 8 of them") must be
  literally true against that brief at generation time. No hand-entered counts.

### No-dig gate (the product's core promise)
- A lead ships in an ACTIONABLE tier only if the brief itself contains a named
  decision-maker with at least one reachable contact, OR a named back-channel route
  (GC, architect, landlord, adjacent tenant) that reaches the operator.
- Offloading research to the client is a defect. "Run an SOS lookup," "search Apollo,"
  "call Development Services for the applicant name" are NOT actionable instructions —
  that work is done before ship, or the lead drops to the Watch tier.
- For any TABC-confirmed opening tied to a named LLC, a Texas SOS SOSDirect
  managing-member lookup is MANDATORY before ship. The $1 lookup is our job.
- Unknown-operator leads ship in an actionable tier ONLY with a named back-channel
  route. "Operator unknown" + no route = Watch tier.

### Window honesty
- The headline promise is early signal within the trailing 45-day window. A lead whose
  most recent signal predates the window may appear ONLY in a labeled "Standing
  Portfolio Targets" section, never mixed into the early-signal ranking — and the
  "before any public announcement" claim is dropped for those leads.

### Accuracy and trust
- Every factual claim in a shipped lead traces to a named source. Estimated/inferred
  values are visibly marked (extend current email/phone labeling to revenue, location
  count, operator identity).
- Load-bearing claims — a person's identity, wealth, or role used as a pitch hook — are
  verified before ship, not inferred (e.g. the "daughter of billionaire Paul Foster" line).
- A correction to any lead immediately supersedes ALL prior briefs carrying the old
  fact; superseded briefs are archived the same session.
---

## END
