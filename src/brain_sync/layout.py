from __future__ import annotations

import os
from pathlib import Path

APP_VERSION = "0.5.0"
BRAIN_FORMAT_VERSION = "1.0"
BRAIN_MANIFEST_VERSION = 1
SOURCE_MANIFEST_VERSION = 1
INSIGHT_STATE_VERSION = 1
RUNTIME_DB_SCHEMA_VERSION = 23

MANAGED_DIRNAME = ".brain-sync"
KNOWLEDGE_DIRNAME = "knowledge"
SOURCES_DIRNAME = "sources"
INSIGHTS_DIRNAME = "insights"
ATTACHMENTS_DIRNAME = "attachments"
JOURNAL_DIRNAME = "journal"

BRAIN_MANIFEST_FILENAME = "brain.json"
INSIGHT_STATE_FILENAME = "insight-state.json"
SUMMARY_FILENAME = "summary.md"
RUNTIME_DB_DIRNAME = "db"
RUNTIME_DB_FILENAME = "brain-sync.sqlite"
DAEMON_STATUS_FILENAME = "daemon.json"

RESERVED_MANAGED_NAMES = frozenset({MANAGED_DIRNAME})


def brain_sync_user_dir() -> Path:
    if "BRAIN_SYNC_CONFIG_DIR" in os.environ:
        return Path(os.environ["BRAIN_SYNC_CONFIG_DIR"])
    return Path.home() / ".brain-sync"


def runtime_db_path() -> Path:
    return brain_sync_user_dir() / RUNTIME_DB_DIRNAME / RUNTIME_DB_FILENAME


def daemon_status_path() -> Path:
    return brain_sync_user_dir() / DAEMON_STATUS_FILENAME


def brain_managed_dir(root: Path) -> Path:
    return root / MANAGED_DIRNAME


def brain_manifest_path(root: Path) -> Path:
    return brain_managed_dir(root) / BRAIN_MANIFEST_FILENAME


def source_manifests_dir(root: Path) -> Path:
    return brain_managed_dir(root) / SOURCES_DIRNAME


def knowledge_root(root: Path) -> Path:
    return root / KNOWLEDGE_DIRNAME


def area_dir(root: Path, knowledge_path: str = "") -> Path:
    if knowledge_path:
        return knowledge_root(root) / Path(knowledge_path)
    return knowledge_root(root)


def area_managed_dir(root: Path, knowledge_path: str = "") -> Path:
    return area_dir(root, knowledge_path) / MANAGED_DIRNAME


def area_insights_dir(root: Path, knowledge_path: str = "") -> Path:
    return area_managed_dir(root, knowledge_path) / INSIGHTS_DIRNAME


def area_summary_path(root: Path, knowledge_path: str = "") -> Path:
    return area_insights_dir(root, knowledge_path) / SUMMARY_FILENAME


def area_insight_state_path(root: Path, knowledge_path: str = "") -> Path:
    return area_insights_dir(root, knowledge_path) / INSIGHT_STATE_FILENAME


def area_journal_dir(root: Path, knowledge_path: str = "") -> Path:
    return area_managed_dir(root, knowledge_path) / JOURNAL_DIRNAME


def area_attachments_root(root: Path, knowledge_path: str = "") -> Path:
    return area_managed_dir(root, knowledge_path) / ATTACHMENTS_DIRNAME


def is_managed_path(path: Path) -> bool:
    return MANAGED_DIRNAME in path.parts
