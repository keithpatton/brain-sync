# Review

Plan under review: `docs/plans/plan_structural-health_4_2026-03-27.md`
Reviewer: codex-gpt-5
Date: 2026-03-27

## Summary

This revision resolves most of the earlier blockers well. The semantic-tree
scope is much clearer, the `knowledge_path` parent rule is now explicit, the
manual-file exclusion seam is pointed at the right helper, and the sparse wire
contract is substantially tighter than before.

I am not approving it yet because one public-contract contradiction remains:
the plan still treats `_core/` as unconditionally present, which conflicts with
the authoritative docs and current code reality.

## Findings

### 1. `_core/` is still specified as always present even though the authoritative contract says it is optional

The revision still says the phase-1 tree should:

- include `_core/`

and the acceptance criteria still require that:

- the tree includes `_core/`

That is not consistent with the current authoritative contract.

`docs/GLOSSARY.md` defines `_core` as optional raw core knowledge and says that
if `_core/` is deleted, brain-sync continues by assuming there is no global
context. `docs/RULES.md` repeats that `knowledge/_core/` is optional and that
if it is deleted, the system continues without global context. The semantic
knowledge-area rules in those same docs say an area exists only when a
directory under `knowledge/` contains readable files or descendant knowledge
areas. There is no rule that invents a synthetic `_core/` node when `_core/`
is absent.

Current code matches that reality:

- `src/brain_sync/application/browse.py` loads `_core` summary content only if
  the file actually exists
- `src/brain_sync/brain/tree.py` discovers areas from the filesystem rather
  than forcing a synthetic `_core` node

Because this plan is defining a new public read surface, approval should not
leave the implementer to guess whether to:

- synthesize `_core/` when it does not exist
- hide `_core/` when absent
- or special-case `_core/` differently from every other semantic knowledge
  area

Required revision:

- change the tree contract so `_core/` is included only when it exists as a
  current semantic knowledge area under the same filesystem-driven rules as the
  rest of the tree
- update the acceptance criteria accordingly
- if the planner wants `_core/` to be synthetic and always present, that needs
  an explicit contract change justified against `docs/GLOSSARY.md` and
  `docs/RULES.md` rather than being implied by example

## Verdict

Changes required.

Create a new plan revision that resolves the findings in this review.
This review artifact does not approve the plan and does not authorize
implementation.
