# Architecture Reviews

This directory holds repeatable architecture review artifacts for brain-sync.

Architecture reviews are not plans. They are periodic diagnostic assessments
that evaluate the current implementation, identify structural risks, and make
recommendations.

Use:

- [`TEMPLATE.md`](./TEMPLATE.md) for a rerunnable, evidence-based review rubric
- [`2026-03-17-baseline.md`](./2026-03-17-baseline.md) for the first baseline assessment after the package refactor
- [`2026-03-18-review-2.md`](./2026-03-18-review-2.md) for the second review rerun after `plan_architecture-hardening_2`

These reviews are explanatory artifacts. They assess the current implementation
against the documented architecture, refactor goals, and operational risks.
They do not replace the normative rules in [`../RULES.md`](../RULES.md) or the
system explanation in [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

If an architecture review leads to implementation work:

- create that work in [`../../plans/`](../../plans/README.md)
- treat the review as an input, not as implementation authorization
- add a link from the plan back to the review that motivated it
- update the review to list only approved derived plans when that relationship
  is useful

That two-way link is intentional. It lets a review and its resulting plans act
like a lightweight decision trail without turning review artifacts into plans.
