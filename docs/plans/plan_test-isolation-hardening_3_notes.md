# Plan test-isolation-hardening 3 Implementation Notes

2026-03-22T12:18:00+13:00
Change: Corrected the Phase 4 compatibility bridge by restoring `brain_sync.runtime.repository.RUNTIME_DB_FILE` and `DAEMON_STATUS_FILE` as semipublic compatibility aliases with explicit-override behavior, while keeping `brain_sync.runtime.config` as the default authoritative patch surface.
Reason: Standard implementation review found that several compatibility-oriented tests and consumers still intentionally patch or read the repository-level runtime DB alias; the earlier Phase 4 clarification was too broad because removing the effective alias changed behavior outside the approved narrow hardening scope.
Status: Implemented.

2026-03-22T11:57:57+13:00
Change: Approved plan implementation completed in five validated phases on the working tree.
Reason: The realized change set now includes the root-aware operational-event seam, the caller migration and anti-drift inventories, the shared test isolation substrate, the targeted runtime/config accessor hardening, and the fortress regression guards required by the approved artifact.
Status: Completed.

2026-03-22T11:56:00+13:00
Change: Phase 4 kept runtime/config hardening narrow by moving affected consumers onto `brain_sync.runtime.config` accessors that still read the canonical module-level paths.
Reason: This reduces downstream cached-path patching without silently changing the intended config-dir-scoped behavior or invalidating the existing `runtime.config` patch surface that many tests already use intentionally.
Status: Clarified.

2026-03-22T11:52:00+13:00
Change: Phase 3 centralized subprocess and in-process isolation through `tests/harness/isolation.py` and added AST-backed inventories for approved subprocess env-construction paths.
Reason: The approved plan required explicit coverage of the current bespoke launch seams, including `tests/system/test_cli_commands.py` and `tests/e2e/test_db_contention.py`, plus a durable guard against future ad hoc subprocess env builders.
Status: Implemented.

2026-03-22T11:44:00+13:00
Change: The Phase 1 command-style reproducer closed the known leak signature via `add-file`, and the command now fails closed before any machine-local operational-event write can occur.
Reason: The approved plan required an early proof of the exact no-session/no-owner leak family; the observed stronger behavior still satisfies that requirement because the subprocess path proves no runtime DB is created and no event can leak when isolation is missed.
Status: Implemented.
