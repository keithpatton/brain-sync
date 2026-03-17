# Plan architecture-hardening.2 Implementation Notes

2026-03-18T09:55:07+13:00
Note: Phase 5 now makes the config-dir runtime semantics explicit in code: `runtime.config.active_brain_root()` and `application.roots.resolve_active_root()` select only the first configured root, while token telemetry and daemon-status helpers are config-dir scoped and no longer accept unused `root` parameters.
Why it matters: The remaining root-parameter cleanup is concentrated in broader `runtime.repository` DB entrypoints. Those APIs are still threaded widely through sync and regen callers, so the next slice should treat them as a dedicated seam cleanup rather than mixing them into unrelated workflow changes.

2026-03-17T21:45:00+13:00
Note: Child-discovery intent is now runtime-only request state in `child_discovery_requests`, not durable manifest or `SourceState` data.
Why it matters: Any future work that reads manifests to infer `fetch_children` / `child_path` is reintroducing the exact split-brain model this plan removed. Treat child discovery as machine-local, one-shot daemon handoff state only.

2026-03-17T23:40:00+13:00
Note: Phase 2 hardening was not just package movement; it also restored disk-before-DB ordering for insight save/delete paths and ratcheted supported `v23 -> v24` runtime DB migration.
Why it matters: Later refactors around application workflows or repository boundaries must preserve those semantics, even when the call graph gets cleaner.

2026-03-18T07:45:00+13:00
Note: The old mixed-plane DTO ownership deferment is retired. `runtime/repository.py` should stay limited to runtime persistence records and locks; composed cross-plane read models belong in `application/`.
Why it matters: If a later slice needs a merged source/insight/sync view, add it in `application/` rather than letting `runtime/` quietly absorb projection logic again.

2026-03-18T08:05:00+13:00
Note: Phase 4 transport thinning has started with shared application workflows for placement, local-file add/remove, and brain browse/query/open flows. The next high-value Phase 4 slice is shared reconcile, reporting, and source-management orchestration.
Why it matters: The remaining payoff is in stopping policy/result-shaping changes from requiring parallel CLI and MCP edits. Start with `interfaces/cli/handlers.py`, `interfaces/mcp/server.py`, `application/sources.py`, `application/status.py`, and `application/reconcile.py`.

2026-03-18T08:20:00+13:00
Note: `brain_sync.application.__init__` must remain an application-only barrel. Do not hide lower-level query/source/brain concepts behind it just to make transport imports look thinner.
Why it matters: The Phase 4 boundary ratchet now depends on transports importing real application-owned seams, not cosmetic re-exports that bypass the architecture tests.
