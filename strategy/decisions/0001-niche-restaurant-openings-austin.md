# 0001 — Niche: Restaurant openings in Austin, TX

**Status:** Accepted
**Date:** 2026-06-05

## Context
Initial exploration centered on cruising/marine intelligence. Two structural problems killed it:
1. Total addressable market of marine vendors willing to pay for buying-signal intel is small (~100-300 companies nationally, with a hard ceiling of 10-15 paying clients due to category exclusivity).
2. Relying on existing industry relationships biased the model toward the familiar rather than the scalable.

We needed a market where signals are public, the buyer universe is broad enough to expand into adjacent verticals, and geographic expansion adds revenue without proportional research overhead.

## Decision
Build the first wedge around new restaurant openings in Austin, TX. Primary signals: City of Austin Open Data Portal (building permits, business licenses), TABC liquor license applications, Travis County health permits. Sell to non-competing regional vendor categories on a category-exclusive basis per metro.

## Alternatives considered
- New business registrations broadly — too crowded, weak average customer profile.
- Funding announcements / hiring surges — owned by ZoomInfo, Crunchbase, and dozens of AI tools.
- Med spas, gyms, dental, vet clinics, daycares — strong pivot options for year two. Restaurants chosen first for proven vendor demand and shorter sales cycles.
- Nashville, Denver, Phoenix as first metro — Austin's open data is meaningfully better. Reserve as fallback only.

## Consequences
- Direct competition exists: Restaurant Activity Report, Dodge Construction Network, BuildCentral. Differentiation must come from enrichment quality (verified owner contact, sales-ready profile), not data novelty.
- Category-exclusive model creates a natural revenue ceiling per metro (~6-10 buyer categories). Growth path is additional metros or adjacent verticals.
- Commits to learning Austin permit data, TABC workflows, and Travis County health filings.

## Revisit if
- Fewer than 3 vendors agree to a paid pilot after 60 days of validation outreach.
- Austin permit data becomes paywalled or significantly delayed.
- A clearly superior adjacent vertical surfaces during validation.
