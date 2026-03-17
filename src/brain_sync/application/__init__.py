"""brain-sync application API.

Usage:
    from brain_sync.application import add_source, list_sources
    sources = list_sources()  # auto-discovers brain root from config
"""

from brain_sync.application.doctor import DoctorResult, Finding, Severity, deregister_missing, doctor, rebuild_db
from brain_sync.application.init import InitResult, init_brain, update_skill
from brain_sync.application.roots import BrainNotFoundError, InvalidBrainRootError, resolve_root, validate_brain_root
from brain_sync.application.sources import (
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
from brain_sync.query.placement import (
    PlacementCandidate,
    PlacementSelection,
    SourceKind,
    SuggestPlacementResult,
    classify_source,
    extract_file_excerpt,
    extract_title_from_url,
    suggest_placement,
)

__all__ = [
    "AddResult",
    "BrainNotFoundError",
    "DoctorResult",
    "Finding",
    "InitResult",
    "InvalidBrainRootError",
    "MigrateResult",
    "MoveResult",
    "PlacementCandidate",
    "PlacementSelection",
    "ReconcileResult",
    "RemoveResult",
    "Severity",
    "SourceAlreadyExistsError",
    "SourceInfo",
    "SourceKind",
    "SourceNotFoundError",
    "SuggestPlacementResult",
    "UpdateResult",
    "add_source",
    "check_source_exists",
    "classify_source",
    "deregister_missing",
    "doctor",
    "extract_file_excerpt",
    "extract_title_from_url",
    "init_brain",
    "list_sources",
    "migrate_sources",
    "move_source",
    "rebuild_db",
    "reconcile_sources",
    "remove_source",
    "resolve_root",
    "suggest_placement",
    "update_skill",
    "update_source",
    "validate_brain_root",
]
