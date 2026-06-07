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

## END
