# Plan source-lifecycle-hardening-v2 2 Implementation Notes

2026-03-21T10:20:00+13:00
Change: Treat the current published docs as the intended description of the supported lifecycle model unless the approved v2 work intentionally changes that contract. For this hardening round, do not casually weaken `docs/RULES.md`, `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`, or `docs/sync/README.md` to match current implementation shortcuts when the docs already describe the correct supported behavior.
Reason: The repo now has a clearer authority split: `docs/RULES.md` owns normative invariants, `docs/runtime/` owns runtime schema/reference, `docs/architecture/` owns rationale, and `docs/sync/README.md` owns synced-source lifecycle explanation. The implementer should use that split to align code upward to the documented contract where practical, and update docs only when v2 intentionally changes the contract or explanation.
Status: Clarified.

2026-03-21T10:20:00+13:00
Change: Current code/documentation misalignment is already known in three important areas and should be treated as explicit alignment work during implementation: (1) cross-process finalization freshness is still count-based in code even though the docs say persisted runtime rows must not by themselves preserve cross-process lifecycle eligibility, (2) `docs/RULES.md` still says normal `sync` dependencies are `brain / runtime / sources / util` while production `sync` code and the architecture fitness test still allow `sync -> regen`, and (3) the new single-active-daemon rule is documented as the supported contract while current code/tests still mainly demonstrate graceful handling rather than explicit startup enforcement.
Reason: Capturing these mismatches here avoids leaving the implementer to infer whether the docs are aspirational or stale. For this round, the agent should preserve awareness that current docs are mostly aligned to the intended model, but a few seams still lag in code and/or tests. If implementation changes one of these areas, the resulting code, tests, and docs should be made mutually consistent rather than leaving the mismatch implicit.
Status: Clarified.

2026-03-21T10:20:00+13:00
Change: The approved v2 hardening plan remains materially ahead of the current implementation. In particular, `remove_source` still bypasses same-source leasing, `move_source` still surfaces ordinary lease contention via exception-style handling instead of the approved deterministic result model, non-lease paths such as missing observation / reconcile repair / watcher batch rewrites do not yet implement the approved `revalidate and skip` rule, the shared exact-target canonical-id validator is still duplicated in CLI and MCP, and runtime schema/session freshness changes for `v28` are not yet present.
Reason: This note preserves the distinction between "code does not yet match the approved v2 target" and "code does not yet match the already-published contract." The next implementation pass should use that distinction when deciding whether a change is contract-alignment, approved hardening execution, or a follow-up outside scope.
Status: Clarified.

2026-03-21T10:20:00+13:00
Change: Use `docs/sync/README.md` as the explanatory scenario map for sync test design and maintenance, while continuing to treat `docs/RULES.md` and the schema docs as the normative contract. When adding or updating sync tests, the expected lifecycle behavior should be alignable to the event matrix and state diagram in `docs/sync/README.md`, and the implementer is free to build or maintain a lightweight scenario-to-test matrix so long as it stays subordinate to the authoritative rules/schema docs.
Reason: The sync docs now provide the clearest compact model of lifecycle entry paths, events, and state transitions. Pointing test reasoning at that artifact should make future hardening easier without turning the explanation doc into a second normative rules file.
Status: Recommended.

2026-03-21T10:20:00+13:00
Change: Any v2 implementation that changes runtime schema, lifecycle semantics, conflict/result contracts, or supported process-model behavior must update the authoritative docs in their owning homes as part of the same change set. At minimum, this approved plan already names `docs/runtime/SCHEMAS.md`, `docs/runtime/README.md`, `docs/RULES.md`, `docs/architecture/ARCHITECTURE.md`, `docs/VERSIONING.md`, `docs/COMPATIBILITY.md`, `docs/sync/README.md`, and `README.md` as documentation surfaces to re-check for consistency.
Reason: The repository now has a more disciplined doc authority model, so the hardening round should not land code-first behavioral changes and leave doc reconciliation for later. Keeping the code, docs, and tests aligned in one pass reduces future agent confusion and drift.
Status: Clarified.
