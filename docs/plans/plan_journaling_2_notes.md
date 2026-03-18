# Plan journaling 2 Implementation Notes

2026-03-19T08:13:36+13:00
Change: Removed the planned journal config surface (`regen.disable_journal` and legacy `regen.write_journal`) and made journaling always on.
Reason: User-directed implementation variation after approval; the repository no longer needs a journaling toggle and should treat journals as unconditional generated meaning.
Status: Implemented.

