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
    RemoveResult,
    SourceAlreadyExistsError,
    SourceInfo,
    SourceNotFoundError,
    add_source,
    list_sources,
    move_source,
    remove_source,
)

__all__ = [
    "resolve_root",
    "BrainNotFoundError",
    "add_source",
    "remove_source",
    "list_sources",
    "move_source",
    "init_brain",
    "update_skill",
    "AddResult",
    "RemoveResult",
    "SourceInfo",
    "MoveResult",
    "InitResult",
    "SourceAlreadyExistsError",
    "SourceNotFoundError",
]
