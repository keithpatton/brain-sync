"""Public regeneration API.

Owns the narrow cross-package REGEN surface. Local modules keep orchestration,
deterministic evaluation, prompt planning, and topology rules inside the
subpackage rather than exposing broad engine internals upward.
"""

from brain_sync.regen.diagnostics import build_regen_diagnostic_report
from brain_sync.regen.engine import (
    ChangeEvent,
    FolderEvaluation,
    RegenFailed,
    classify_folder_change,
    evaluate_folder_state,
    invalidate_global_context_cache,
    regen_all,
    regen_path,
)

__all__ = [
    "ChangeEvent",
    "FolderEvaluation",
    "RegenFailed",
    "build_regen_diagnostic_report",
    "classify_folder_change",
    "evaluate_folder_state",
    "invalidate_global_context_cache",
    "regen_all",
    "regen_path",
]
