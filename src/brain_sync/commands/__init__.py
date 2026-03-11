"""brain-sync commands — importable Python API.

Usage:
    from brain_sync.commands import list_sources, add_source
    sources = list_sources()  # auto-discovers brain root from config
"""

from brain_sync.commands.context import BrainNotFoundError, resolve_root
from brain_sync.commands.init import InitResult, init_brain, update_skill
from brain_sync.commands.placement import (
    PlacementCandidate,
    PlacementSelection,
    SourceKind,
    SuggestPlacementResult,
    classify_source,
    extract_file_excerpt,
    extract_title_from_url,
    slugify_title,
    suggest_placement,
)
from brain_sync.commands.sources import (
    AddResult,
    MoveResult,
    RemoveResult,
    SourceAlreadyExistsError,
    SourceInfo,
    SourceNotFoundError,
    UpdateResult,
    add_source,
    check_source_exists,
    list_sources,
    move_source,
    remove_source,
    update_source,
)

__all__ = [
    "AddResult",
    "BrainNotFoundError",
    "InitResult",
    "MoveResult",
    "PlacementCandidate",
    "PlacementSelection",
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
    "move_source",
    "remove_source",
    "resolve_root",
    "slugify_title",
    "suggest_placement",
    "update_skill",
    "update_source",
]
