"""Source manifest read/write utilities.

Each registered source has a JSON manifest at .brain-sync/sources/{id}.json.
Manifests are the authoritative durable record of synced-source truth.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from brain_sync.brain.fileops import (
    atomic_write_bytes,
    canonical_prefix,
    iterdir_paths,
    path_exists,
    path_is_dir,
    read_bytes,
)
from brain_sync.brain.layout import BRAIN_MANIFEST_FILENAME, SOURCE_MANIFEST_VERSION, source_manifests_dir
from brain_sync.brain.tree import normalize_path

log = logging.getLogger(__name__)

MANIFEST_DIR = ".brain-sync/sources"
MANIFEST_VERSION_FILE = f".brain-sync/{BRAIN_MANIFEST_FILENAME}"
MANIFEST_VERSION = SOURCE_MANIFEST_VERSION
KnowledgeState = Literal["awaiting", "materialized", "stale", "missing"]
KNOWLEDGE_STATES: frozenset[str] = frozenset({"awaiting", "materialized", "stale", "missing"})


def _to_durable_source_type(source_type: str) -> str:
    if source_type == "googledocs":
        return "google_doc"
    return source_type


def _from_durable_source_type(source_type: str) -> str:
    if source_type == "google_doc":
        return "googledocs"
    return source_type


class ManifestValidationError(ValueError):
    """Raised when a source manifest violates the durable state contract."""


@dataclass(init=False)
class SourceManifest:
    """On-disk representation of a registered source."""

    version: int
    canonical_id: str
    source_url: str
    source_type: str
    sync_attachments: bool
    knowledge_path: str
    knowledge_state: KnowledgeState
    missing_since_utc: str | None
    content_hash: str | None
    remote_fingerprint: str | None
    materialized_utc: str | None

    def __init__(
        self,
        *,
        version: int | None = None,
        manifest_version: int | None = None,
        canonical_id: str,
        source_url: str,
        source_type: str,
        sync_attachments: bool,
        knowledge_path: str,
        knowledge_state: KnowledgeState,
        missing_since_utc: str | None = None,
        content_hash: str | None = None,
        remote_fingerprint: str | None = None,
        materialized_utc: str | None = None,
    ) -> None:
        self.version = (
            version if version is not None else manifest_version if manifest_version is not None else MANIFEST_VERSION
        )
        self.canonical_id = canonical_id
        self.source_url = source_url
        self.source_type = source_type
        self.sync_attachments = sync_attachments
        self.knowledge_path = _normalize_manifest_knowledge_path(knowledge_path)
        self.knowledge_state = knowledge_state
        self.missing_since_utc = missing_since_utc
        self.content_hash = content_hash
        self.remote_fingerprint = remote_fingerprint
        self.materialized_utc = materialized_utc
        self.validate()

    @property
    def manifest_version(self) -> int:
        return self.version

    @property
    def target_path(self) -> str:
        return normalize_path(Path(self.knowledge_path).parent)

    def validate(self) -> None:
        if self.version != MANIFEST_VERSION:
            raise ManifestValidationError(
                f"Unsupported manifest schema version {self.version} for {self.canonical_id} "
                f"(expected {MANIFEST_VERSION})"
            )
        if self.knowledge_state not in KNOWLEDGE_STATES:
            raise ManifestValidationError(f"Invalid knowledge_state '{self.knowledge_state}' for {self.canonical_id}")
        if not self.knowledge_path:
            raise ManifestValidationError(f"knowledge_path is required for {self.canonical_id}")

        if self.knowledge_state == "awaiting":
            _require_null(self.missing_since_utc, "missing_since_utc", self.canonical_id)
            _require_null(self.content_hash, "content_hash", self.canonical_id)
            _require_null(self.remote_fingerprint, "remote_fingerprint", self.canonical_id)
            _require_null(self.materialized_utc, "materialized_utc", self.canonical_id)
            return

        if self.knowledge_state in {"materialized", "stale"}:
            _require_null(self.missing_since_utc, "missing_since_utc", self.canonical_id)
            _require_set(self.content_hash, "content_hash", self.canonical_id)
            _require_set(self.remote_fingerprint, "remote_fingerprint", self.canonical_id)
            _require_set(self.materialized_utc, "materialized_utc", self.canonical_id)
            return

        if self.knowledge_state == "missing":
            _require_set(self.missing_since_utc, "missing_since_utc", self.canonical_id)


def _normalize_manifest_knowledge_path(knowledge_path: str) -> str:
    normalized = normalize_path(knowledge_path)
    path_obj = Path(normalized)
    if (
        not normalized
        or path_obj.is_absolute()
        or any(part == ".." for part in path_obj.parts)
        or normalized.endswith("/")
        or path_obj.suffix.lower() != ".md"
    ):
        raise ManifestValidationError(f"Invalid knowledge_path '{knowledge_path}'")
    return normalized


def _require_null(value: str | None, field_name: str, canonical_id: str) -> None:
    if value is not None:
        raise ManifestValidationError(f"{field_name} must be null for {canonical_id}")


def _require_set(value: str | None, field_name: str, canonical_id: str) -> None:
    if value is None or value == "":
        raise ManifestValidationError(f"{field_name} must be set for {canonical_id}")


def manifest_filename(canonical_id: str) -> str:
    """Convert a canonical_id to the spec-aligned manifest filename."""
    return canonical_prefix(canonical_id).rstrip("-") + ".json"


def derive_provisional_knowledge_path(area_path: str, canonical_id: str) -> str:
    """Derive the durable first materialization anchor from an area hint."""
    normalized_area = normalize_path(area_path)
    source_dir_id = canonical_prefix(canonical_id).rstrip("-")
    filename = f"{source_dir_id}.md"
    return normalize_path(Path(normalized_area) / filename) if normalized_area else filename


def _manifest_path(root: Path, canonical_id: str) -> Path:
    return root / MANIFEST_DIR / manifest_filename(canonical_id)


def ensure_manifest_dir(root: Path) -> None:
    """Create .brain-sync/sources/ if it does not exist."""
    source_manifests_dir(root).mkdir(parents=True, exist_ok=True)


def _serialize_manifest(manifest: SourceManifest) -> bytes:
    manifest.validate()
    data = asdict(manifest)
    data["source_type"] = _to_durable_source_type(data["source_type"])
    for field_name in ("missing_since_utc", "content_hash", "remote_fingerprint", "materialized_utc"):
        if data.get(field_name) is None:
            del data[field_name]
    return (json.dumps(data, indent=2, sort_keys=False) + "\n").encode("utf-8")


class UnsupportedManifestVersion(Exception):
    """Raised when a manifest has an unrecognised version."""

    def __init__(self, path: str, version: int):
        self.path = path
        self.version = version
        super().__init__(f"Unsupported manifest version {version} in {path} (supported: {MANIFEST_VERSION})")


def _deserialize_manifest(data: bytes, *, source_path: str = "<unknown>") -> SourceManifest:
    raw = json.loads(data)
    version = raw.get("version", raw.get("manifest_version"))
    if not isinstance(version, int):
        raise ValueError(f"Invalid or missing version in {source_path}")
    if version != MANIFEST_VERSION:
        raise UnsupportedManifestVersion(source_path, version)
    return SourceManifest(
        version=version,
        canonical_id=raw["canonical_id"],
        source_url=raw["source_url"],
        source_type=_from_durable_source_type(raw["source_type"]),
        sync_attachments=raw["sync_attachments"],
        knowledge_path=raw["knowledge_path"],
        knowledge_state=raw["knowledge_state"],
        missing_since_utc=raw.get("missing_since_utc"),
        content_hash=raw.get("content_hash"),
        remote_fingerprint=raw.get("remote_fingerprint"),
        materialized_utc=raw.get("materialized_utc"),
    )


def write_source_manifest(root: Path, manifest: SourceManifest) -> None:
    """Atomically write a source manifest to disk."""
    ensure_manifest_dir(root)
    target = _manifest_path(root, manifest.canonical_id)
    atomic_write_bytes(target, _serialize_manifest(manifest))
    log.debug("Wrote manifest %s", target)


def delete_source_manifest(root: Path, canonical_id: str) -> None:
    """Delete a source manifest from disk."""
    target = _manifest_path(root, canonical_id)
    if path_exists(target):
        target.unlink()
        log.debug("Deleted manifest %s", target)


def read_source_manifest(root: Path, canonical_id: str) -> SourceManifest | None:
    """Read a single source manifest. Returns None if not found."""
    target = _manifest_path(root, canonical_id)
    if not path_exists(target):
        return None
    try:
        return _deserialize_manifest(read_bytes(target), source_path=str(target))
    except UnsupportedManifestVersion:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ManifestValidationError) as exc:
        log.warning("Failed to read manifest %s: %s", target, exc)
        return None


def read_all_source_manifests(root: Path) -> dict[str, SourceManifest]:
    """Read all source manifests. Returns {canonical_id: manifest}."""
    manifest_dir = source_manifests_dir(root)
    if not path_is_dir(manifest_dir):
        return {}
    result: dict[str, SourceManifest] = {}
    for path in iterdir_paths(manifest_dir):
        if path.suffix != ".json":
            continue
        try:
            manifest = _deserialize_manifest(read_bytes(path), source_path=str(path))
            result[manifest.canonical_id] = manifest
        except UnsupportedManifestVersion:
            raise
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, ManifestValidationError) as exc:
            log.warning("Skipping malformed manifest %s: %s", path, exc)
    return result


def mark_manifest_missing(root: Path, canonical_id: str, utc_now: str) -> None:
    """Mark a manifest as missing (first stage of two-stage deregistration)."""
    manifest = read_source_manifest(root, canonical_id)
    if manifest is None:
        return
    manifest.knowledge_state = "missing"
    manifest.missing_since_utc = utc_now
    write_source_manifest(root, manifest)
    log.info("Marked source %s as missing (grace period)", canonical_id)


def clear_manifest_missing(root: Path, canonical_id: str) -> None:
    """Clear the missing state and mark the source stale until rematerialized."""
    manifest = read_source_manifest(root, canonical_id)
    if manifest is None:
        return
    manifest.knowledge_state = "stale"
    manifest.missing_since_utc = None
    write_source_manifest(root, manifest)
    log.info("Cleared missing state for %s and marked it stale", canonical_id)


def update_manifest_knowledge_path(root: Path, canonical_id: str, knowledge_path: str) -> None:
    """Update the knowledge_path in a manifest."""
    manifest = read_source_manifest(root, canonical_id)
    if manifest is None:
        return
    manifest.knowledge_path = _normalize_manifest_knowledge_path(knowledge_path)
    write_source_manifest(root, manifest)


def update_manifest_materialization(
    root: Path,
    canonical_id: str,
    *,
    knowledge_path: str,
    content_hash: str,
    remote_fingerprint: str,
    materialized_utc: str,
) -> None:
    """Persist the settled last-successful source state after materialization."""
    manifest = read_source_manifest(root, canonical_id)
    if manifest is None:
        return
    manifest.knowledge_path = _normalize_manifest_knowledge_path(knowledge_path)
    manifest.knowledge_state = "materialized"
    manifest.missing_since_utc = None
    manifest.content_hash = content_hash
    manifest.remote_fingerprint = remote_fingerprint
    manifest.materialized_utc = materialized_utc
    write_source_manifest(root, manifest)
