"""Interface-neutral application operations for user-visible workflows.

Owns orchestration that is shared across CLI and MCP surfaces.
Does not own durable persistence primitives or transport-specific handling.

Usage:
    from brain_sync.application import add_source, list_sources
    sources = list_sources()  # auto-discovers brain root from config
"""

from brain_sync.application.doctor import DoctorResult, Finding, Severity, deregister_missing, doctor, rebuild_db
from brain_sync.application.init import InitResult, init_brain, update_skill
from brain_sync.application.insights import (
    delete_insight_state,
    load_all_insight_states,
    load_insight_state,
    save_insight_state,
)
from brain_sync.application.query_index import AreaIndex, load_area_index
from brain_sync.application.reconcile import TreeReconcileResult, reconcile_knowledge_tree
from brain_sync.application.regen import RegenFailed, classify_folder_change, invalidate_global_context_cache, run_regen
from brain_sync.application.roots import BrainNotFoundError, InvalidBrainRootError, resolve_root, validate_brain_root
from brain_sync.application.source_state import load_state
from brain_sync.application.sources import (
    AddResult,
    InvalidChildDiscoveryRequestError,
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
from brain_sync.application.status import StatusSummary, build_status_summary, get_usage_summary
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
    "AreaIndex",
    "BrainNotFoundError",
    "DoctorResult",
    "Finding",
    "InitResult",
    "InvalidBrainRootError",
    "InvalidChildDiscoveryRequestError",
    "MigrateResult",
    "MoveResult",
    "PlacementCandidate",
    "PlacementSelection",
    "ReconcileResult",
    "RegenFailed",
    "RemoveResult",
    "Severity",
    "SourceAlreadyExistsError",
    "SourceInfo",
    "SourceKind",
    "SourceNotFoundError",
    "StatusSummary",
    "SuggestPlacementResult",
    "TreeReconcileResult",
    "UpdateResult",
    "add_source",
    "build_status_summary",
    "check_source_exists",
    "classify_folder_change",
    "classify_source",
    "delete_insight_state",
    "deregister_missing",
    "doctor",
    "extract_file_excerpt",
    "extract_title_from_url",
    "get_usage_summary",
    "init_brain",
    "invalidate_global_context_cache",
    "list_sources",
    "load_all_insight_states",
    "load_area_index",
    "load_insight_state",
    "load_state",
    "migrate_sources",
    "move_source",
    "rebuild_db",
    "reconcile_knowledge_tree",
    "reconcile_sources",
    "remove_source",
    "resolve_root",
    "run_regen",
    "save_insight_state",
    "suggest_placement",
    "update_skill",
    "update_source",
    "validate_brain_root",
]
