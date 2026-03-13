"""brain-sync commands — importable Python API.

Usage:
    from brain_sync.commands import list_sources, add_source
    sources = list_sources()  # auto-discovers brain root from config
"""

from brain_sync.commands.context import BrainNotFoundError, InvalidBrainRootError, resolve_root, validate_brain_root
from brain_sync.commands.init import InitResult, init_brain, update_skill
from brain_sync.commands.placement import (
    PlacementCandidate,
    PlacementSelection,
    SourceKind,
    SuggestPlacementResult,
    classify_source,
    extract_file_excerpt,
    extract_title_from_url,
    suggest_placement,
)
from brain_sync.commands.sources import (
    AddResult,
    MigrateResult,
    MoveResult,
    ReconcileResult,
    RemoveResult,
    SourceAlreadyExistsError,
    SourceInfo,
    SourceNotFoundError,
    UpdateResult,
    add_source,
    check_source_exists,
    list_sources,
    migrate_sources,
    move_source,
    reconcile_sources,
    remove_source,
    update_source,
)

__all__ = [
    "AddResult",
    "BrainNotFoundError",
    "InitResult",
    "InvalidBrainRootError",
    "MigrateResult",
    "MoveResult",
    "PlacementCandidate",
    "PlacementSelection",
    "ReconcileResult",
    "RemoveResult",
    "SourceAlreadyExistsError",
    "SourceInfo",
    "SourceKind",
    "SourceNotFoundError",
    "SuggestPlacementResult",
    "UpdateResult",
    "add_source",
    "check_source_exists",
    "classify_source",
    "extract_file_excerpt",
    "extract_title_from_url",
    "init_brain",
    "list_sources",
    "migrate_sources",
    "move_source",
    "reconcile_sources",
    "remove_source",
    "resolve_root",
    "suggest_placement",
    "update_skill",
    "update_source",
    "validate_brain_root",
]
