# Plan sync-source-command 2 Implementation Notes

2026-03-26T16:17:00+13:00
Change: The implemented `brain-sync sync` command was simplified from
direct single-source execution to an async immediate-poll request model.
Reason: Direct CLI orchestration overlapped too much with the daemon's live
source-processing ownership. By explicit user direction, the safer model keeps
the daemon as the single live sync executor: the CLI now marks all active
sources or the listed active sources due immediately by setting
`sync_polling.next_check_utc` to now, and a running daemon is nudged via the
best-effort runtime `daemon-rescan.flag` so it reloads active sync state
promptly. The command itself no longer fetches remote content or performs
inline regen.
Status: Implemented.

2026-03-26T12:27:24+13:00
Change: The manifest-layer missing-state write log was demoted so the sync CLI
handler owns the first user-visible line for handled `remote_missing` output.
Reason: Implementation review required `Result: <state>` to remain the first
stable CLI line for every handled outcome; the prior `INFO` manifest log leaked
ahead of the handler and violated that contract.
Status: Implemented.

2026-03-26T12:18:49+13:00
Change: Post-review proof gaps were closed by strengthening the sync command
system and e2e tests.
Reason: Implementation review required stronger evidence for the stable handled
CLI output contract and for daemon coexistence against a live daemon-held
source lease rather than a synthetic runtime-row insertion.
Status: Implemented.

2026-03-26T10:48:53+13:00
Change: Approved plan implementation completed in the working tree with the CLI
surface exposed as `brain-sync sync <source>`.
Reason: The approved artifact named the command `sync-source`, but execution
landed the single-verb `sync` form by explicit user direction. The implemented
scope otherwise stays aligned with the approved plan: CLI only, thin
CLI/application seam, shared single-source sync orchestration, and no inline
regen.
Status: Completed.

2026-03-26T10:48:53+13:00
Change: The command name was clarified from `brain-sync sync-source <source>`
to `brain-sync sync <source>` during implementation.
Reason: The repository's existing source-management CLI already uses the
single-verb pattern (`add`, `remove`, `list`, `move`, `update`), so preserving
that shape avoided introducing one inconsistent verb form for this command.
Status: Clarified.
