# 0003 — Phase discipline: Validation only, no operation builds

**Status:** Accepted
**Date:** 2026-06-05

## Context
Solo operator with strong sales skills, no engineering team, 15-20 weekly hours, intermittent connectivity. The most common failure mode for lead intelligence businesses is founders building tooling, infrastructure, and dashboards before validating buyer willingness to pay. The temptation to over-build is the primary identified risk to this project.

## Decision
For at least the first 90 days, all work is scoped to validation. Concrete rules apply to both human work and any Claude Code session operating in this project:

- Build a demo (5-10 sample lead profiles) sufficient to show on pitch calls. No production pipeline.
- Manual enrichment only. No LLM-based contact enrichment automation.
- No scrapers for sites without public APIs. APIs only (Austin Open Data Portal, TABC).
- No deployed infrastructure. All scripts run locally.
- No client-facing portal, dashboard, or SaaS. Shared Airtable views or PDF briefs only.
- No team, no VA, no contractors during validation.
- No tooling work in any week with zero sales conversations.

This decision is a hard constraint on the project until formally superseded by a new decision record.

## Alternatives considered
- Build production pipeline first, sell second: textbook failure mode for this business type.
- Hire a VA before first sale: premature, because the enrichment playbook isn't written yet — nothing to delegate.
- Build a client portal from day one: theoretically justifies higher pricing, but Airtable views deliver the same buyer experience at $0 cost.

## Consequences
- Scaling will be slower once paying clients exist; operation buildout will happen under deadline pressure with revenue funding it.
- Some manual work that could be automated will stay manual through validation.
- Project file structure is intentionally simple. Expect restructuring when validation completes.
- Claude Code sessions in this project should reference this record when scope creep is requested.

## Revisit if
- 3+ paying clients close — triggers a formal phase transition and a new decision record covering scaling questions.
- Manual workload exceeds 20 hrs/week before any paying clients exist — indicates a structural model problem, not a phase problem.
- A vendor explicitly conditions purchase on infrastructure that doesn't yet exist (e.g., a real-time portal). Evaluate case-by-case rather than blanket-build.
