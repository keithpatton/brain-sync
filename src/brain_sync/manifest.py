"""Source manifest read/write utilities.

Each registered source has a JSON manifest at .brain-sync/sources/{id}.json.
Manifests are the authoritative record of source registration intent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from brain_sync.fileops import atomic_write_bytes, canonical_prefix
from brain_sync.layout import BRAIN_MANIFEST_FILENAME, SOURCE_MANIFEST_VERSION, source_manifests_dir
from brain_sync.sources import from_durable_source_type, to_durable_source_type

log = logging.getLogger(__name__)

MANIFEST_DIR = ".brain-sync/sources"
MANIFEST_VERSION_FILE = f".brain-sync/{BRAIN_MANIFEST_FILENAME}"
MANIFEST_VERSION = SOURCE_MANIFEST_VERSION


@dataclass
class SyncHint:
    """Portable sync freshness hint — not authoritative, just avoids thundering-herd."""

    content_hash: str | None = None
    last_synced_utc: str | None = None


@dataclass(init=False)
class SourceManifest:
    """On-disk representation of a registered source."""

    version: int
    canonical_id: str
    source_url: str
    source_type: str
    materialized_path: str  # full relative path from knowledge/ to file
    sync_attachments: bool
    target_path: str = ""  # placement intent (area within knowledge/)
    status: str = "active"  # "active" or "missing"
    missing_since_utc: str | None = None
    sync_hint: SyncHint | None = None
    # Deprecated runtime-only flags. Readers still tolerate them, but writers do not persist them.
    fetch_children: bool = False
    child_path: str | None = None

    def __init__(
        self,
        *,
        version: int | None = None,
        manifest_version: int | None = None,
        canonical_id: str,
        source_url: str,
        source_type: str,
        materialized_path: str,
        sync_attachments: bool,
        target_path: str = "",
        status: str = "active",
        missing_since_utc: str | None = None,
        sync_hint: SyncHint | None = None,
        fetch_children: bool = False,
        child_path: str | None = None,
    ) -> None:
        self.version = (
            version if version is not None else manifest_version if manifest_version is not None else MANIFEST_VERSION
        )
        self.canonical_id = canonical_id
        self.source_url = source_url
        self.source_type = source_type
        self.materialized_path = materialized_path
        self.sync_attachments = sync_attachments
        self.target_path = target_path
        self.status = status
        self.missing_since_utc = missing_since_utc
        self.sync_hint = sync_hint
        self.fetch_children = fetch_children
        self.child_path = child_path

    @property
    def manifest_version(self) -> int:
        return self.version


def manifest_filename(canonical_id: str) -> str:
    """Convert a canonical_id to the spec-aligned manifest filename."""
    return canonical_prefix(canonical_id).rstrip("-") + ".json"


def _manifest_path(root: Path, canonical_id: str) -> Path:
    return root / MANIFEST_DIR / manifest_filename(canonical_id)


def ensure_manifest_dir(root: Path) -> None:
    """Create .brain-sync/sources/ if it does not exist."""
    source_manifests_dir(root).mkdir(parents=True, exist_ok=True)


def _serialize_manifest(manifest: SourceManifest) -> bytes:
    d = asdict(manifest)
    d["source_type"] = to_durable_source_type(d["source_type"])
    d.pop("fetch_children", None)
    d.pop("child_path", None)
    # Omit empty/None-valued optional fields for cleaner JSON
    if not d.get("target_path"):
        d["target_path"] = ""
    if d.get("missing_since_utc") is None:
        del d["missing_since_utc"]
    if d.get("sync_hint") is None:
        del d["sync_hint"]
    elif d["sync_hint"]:
        # Clean up None values inside sync_hint
        d["sync_hint"] = {k: v for k, v in d["sync_hint"].items() if v is not None}
        if not d["sync_hint"]:
            del d["sync_hint"]
    return (json.dumps(d, indent=2, sort_keys=False) + "\n").encode("utf-8")


class UnsupportedManifestVersion(Exception):
    """Raised when a manifest has an unrecognised version."""

    def __init__(self, path: str, version: int):
        self.path = path
        self.version = version
        super().__init__(f"Unsupported manifest version {version} in {path} (max supported: {MANIFEST_VERSION})")


def _deserialize_manifest(data: bytes, *, source_path: str = "<unknown>") -> SourceManifest:
    d = json.loads(data)
    version = d.get("version", d.get("manifest_version"))
    if not isinstance(version, int) or version < 1:
        raise ValueError(f"Invalid or missing version in {source_path}")
    if version > MANIFEST_VERSION:
        raise UnsupportedManifestVersion(source_path, version)
    hint_raw = d.pop("sync_hint", None)
    hint = SyncHint(**hint_raw) if hint_raw else None
    return SourceManifest(
        version=version,
        canonical_id=d["canonical_id"],
        source_url=d["source_url"],
        source_type=from_durable_source_type(d["source_type"]),
        materialized_path=d["materialized_path"],
        sync_attachments=d["sync_attachments"],
        target_path=d.get("target_path", ""),
        fetch_children=d.get("fetch_children", False),
        child_path=d.get("child_path"),
        status=d.get("status", "active"),
        missing_since_utc=d.get("missing_since_utc"),
        sync_hint=hint,
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
    if target.exists():
        target.unlink()
        log.debug("Deleted manifest %s", target)


def read_source_manifest(root: Path, canonical_id: str) -> SourceManifest | None:
    """Read a single source manifest. Returns None if not found."""
    target = _manifest_path(root, canonical_id)
    if not target.exists():
        return None
    try:
        return _deserialize_manifest(target.read_bytes(), source_path=str(target))
    except UnsupportedManifestVersion:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        log.warning("Failed to read manifest %s: %s", target, e)
        return None


def read_all_source_manifests(root: Path) -> dict[str, SourceManifest]:
    """Read all source manifests. Returns {canonical_id: manifest}."""
    manifest_dir = source_manifests_dir(root)
    if not manifest_dir.is_dir():
        return {}
    result: dict[str, SourceManifest] = {}
    for path in manifest_dir.iterdir():
        if path.suffix != ".json":
            continue
        try:
            manifest = _deserialize_manifest(path.read_bytes(), source_path=str(path))
            result[manifest.canonical_id] = manifest
        except UnsupportedManifestVersion:
            raise
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            log.warning("Skipping malformed manifest %s: %s", path, e)
    return result


def mark_manifest_missing(root: Path, canonical_id: str, utc_now: str) -> None:
    """Mark a manifest as missing (first stage of two-stage deregistration)."""
    manifest = read_source_manifest(root, canonical_id)
    if manifest is None:
        return
    manifest.status = "missing"
    manifest.missing_since_utc = utc_now
    write_source_manifest(root, manifest)
    log.info("Marked source %s as missing (grace period)", canonical_id)


def clear_manifest_missing(root: Path, canonical_id: str) -> None:
    """Clear the missing status (file reappeared during grace period)."""
    manifest = read_source_manifest(root, canonical_id)
    if manifest is None:
        return
    manifest.status = "active"
    manifest.missing_since_utc = None
    write_source_manifest(root, manifest)
    log.info("Cleared missing status for %s (file reappeared)", canonical_id)


def update_manifest_materialized_path(root: Path, canonical_id: str, new_path: str) -> None:
    """Update the materialized_path in a manifest (e.g. after file move)."""
    manifest = read_source_manifest(root, canonical_id)
    if manifest is None:
        return
    manifest.materialized_path = new_path
    write_source_manifest(root, manifest)


def update_manifest_sync_hint(root: Path, canonical_id: str, content_hash: str, last_synced_utc: str) -> None:
    """Update the sync_hint in a manifest after successful sync."""
    manifest = read_source_manifest(root, canonical_id)
    if manifest is None:
        return
    manifest.sync_hint = SyncHint(content_hash=content_hash, last_synced_utc=last_synced_utc)
    write_source_manifest(root, manifest)
