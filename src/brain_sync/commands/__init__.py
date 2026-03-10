"""brain-sync commands — importable Python API.

Usage:
    from brain_sync.commands import list_sources, add_source
    sources = list_sources()  # auto-discovers brain root from config
"""

from brain_sync.commands.context import BrainNotFoundError, resolve_root
from brain_sync.commands.init import InitResult, init_brain, update_skill
from brain_sync.commands.sources import (
    AddResult,
    MoveResult,
    ReconcileResult,
    RemoveResult,
    SourceAlreadyExistsError,
    SourceInfo,
    SourceNotFoundError,
    UpdateResult,
    add_source,
    list_sources,
    move_source,
    reconcile_sources,
    remove_source,
    update_source,
)

__all__ = [
    "AddResult",
    "BrainNotFoundError",
    "InitResult",
    "MoveResult",
    "ReconcileResult",
    "RemoveResult",
    "SourceAlreadyExistsError",
    "SourceInfo",
    "SourceNotFoundError",
    "UpdateResult",
    "add_source",
    "init_brain",
    "list_sources",
    "move_source",
    "reconcile_sources",
    "remove_source",
    "resolve_root",
    "update_skill",
    "update_source",
]
