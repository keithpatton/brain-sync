# Plan plugin-delivery 2 Implementation Notes

2026-04-10T10:35:00+12:00
Change: Codex plugin follow-up completed by advertising the full MCP tool surface from launcher startup while keeping full-tool calls fail-closed until `brain_sync_init` or `brain_sync_attach_root` succeeds.
Reason: Real Codex plugin sessions cache the initial MCP tool list, so a launcher that started in bootstrap mode could attach a root successfully but still leave `brain_sync_query` and related tools unavailable for the rest of that session.
Status: Completed.

2026-04-09T18:05:00+12:00
Change: Third adversarial-review follow-up completed by failing full MCP tool requests closed whenever a root rebind cannot establish a healthy daemon for the newly active root, while leaving `brain_sync_status` available to report the stale daemon state.
Reason: The third adversarial review found a plausible split-root path where a long-lived launcher session could rebind content tools to root B while the shared launcher-background daemon remained live on root A.
Status: Completed.

2026-04-09T15:35:00+12:00
Change: Second adversarial-review follow-up completed by requiring `daemon.json` to carry its own recorded PID before launcher health/adoption can be marked healthy, and by making launcher background start succeed only when the spawned daemon finishes in a healthy post-start classification for the current active root.
Reason: The second adversarial review found two fail-open launcher paths: incomplete `daemon.json` snapshots could still be promoted to healthy by borrowing guard state, and `start` could report success for a daemon that was already stale after an active-root race.
Status: Completed.

2026-04-09T12:05:00+12:00
Change: Adversarial-review follow-up completed by rebinding long-lived MCP full-tool sessions to the current active root before full-tool use and ensure-running, plus adding explicit regression coverage for external `attach-root` during an existing launcher session.
Reason: The adversarial review found a split-brain path where a launcher session could keep serving the previously cached root while status/admin followed the newly attached active root.
Status: Completed.

2026-04-09T11:20:00+12:00
Change: Review follow-up completed by tightening launcher admin control so only healthy `launcher-background` daemons are remotely stoppable/restartable, adding direct MCP bootstrap proof for `brain_sync_init`, and adding proof that a healthy `terminal-foreground` daemon remains adoptable for full MCP tool use without remote control.
Reason: The latest implementation review identified stale root-mismatch launcher control drift plus missing proof for the approved bootstrap-init path.
Status: Completed.

2026-04-09T10:55:00+12:00
Change: Windows packaging smoke confirmed the installed `brain-sync-mcp` entrypoint after `python -m pip install -e .`; `Get-Command brain-sync-mcp` resolved to the generated console script under the active Python Scripts directory.
Reason: The approved wrapper objective required a user-facing launcher command surface instead of exposing raw `python -m ...` module invocation in checked-in wrapper manifests.
Status: Completed.

2026-04-09T10:40:00+12:00
Change: Review follow-up completed by adding the installed `brain-sync-mcp` launcher command, repointing wrapper artifacts/docs away from raw `python -m ...`, and adding direct MCP/system daemon-admin proof for status/start/stop/restart.
Reason: The standard implementation review identified a packaging gap in the wrapper command surface plus missing proof for MCP admin semantics and direct CLI stop coverage.
Status: Completed.

2026-04-09T10:05:00+12:00
Change: Approved plan implementation completed with thin wrapper artifacts checked in as repo-local manifests at `.mcp.json`, `docs/examples/claude-desktop.mcp.json`, and `plugins/brain-sync/`.
Reason: The approved slice required Claude Code, Claude Desktop, and Codex wrappers to stay thin, share one launcher seam, and avoid depending on another wrapper's install path or marketplace cache location.
Status: Completed.
