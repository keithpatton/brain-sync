"""Brain initialisation and skill installation commands."""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import brain_sync.runtime.config as runtime_config
from brain_sync.application.roots import attach_root
from brain_sync.brain.fileops import atomic_write_bytes, path_exists
from brain_sync.brain.layout import BRAIN_MANIFEST_VERSION, brain_manifest_path, source_manifests_dir
from brain_sync.runtime.paths import ensure_safe_temp_root_runtime

log = logging.getLogger(__name__)

SKILL_INSTALL_DIR_ENV = "BRAIN_SYNC_SKILL_INSTALL_DIR"


def skill_install_dir() -> Path:
    """Return the install directory for the packaged MCP skill."""
    override = os.environ.get(SKILL_INSTALL_DIR_ENV)
    if override:
        return Path(override)
    return Path.home() / ".claude" / "skills" / "brain-sync"


def _resource_path(package: str, name: str) -> Path:
    """Get the path to a bundled resource file."""
    ref = resources.files(package).joinpath(name)
    with resources.as_file(ref) as p:
        return Path(p)


def _copy_resource(
    package: str,
    name: str,
    dest: Path,
    dry_run: bool = False,
) -> bool:
    """Copy a bundled resource file to dest. Returns True if copied."""
    if dry_run:
        log.info("[dry-run] Would copy %s:%s -> %s", package, name, dest)
        return False
    src = _resource_path(package, name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dest))
    log.info("Installed %s", dest)
    return True


def _ensure_dir(path: Path, dry_run: bool = False) -> bool:
    """Create directory if it doesn't exist. Returns True if created."""
    if path_exists(path):
        return False
    if dry_run:
        log.info("[dry-run] Would create %s", path)
        return True
    path.mkdir(parents=True, exist_ok=True)
    log.info("Created %s", path)
    return True


def _register_brain_root(
    root: Path,
    *,
    model: str | None = None,
    dry_run: bool = False,
) -> None:
    """Register this brain root as active and persist optional runtime settings."""
    if dry_run:
        log.info("[dry-run] Would register brain root in %s", runtime_config.config_file_path())
        return

    config = runtime_config.load_config()
    changed = False

    if model:
        regen = config.get("regen", {})
        regen["model"] = model
        config["regen"] = regen
        changed = True

    if changed:
        runtime_config.save_config(config)
        log.info("Updated config in %s", runtime_config.config_file_path())

    attach_result = attach_root(root)
    if attach_result.previous_active_root != attach_result.root:
        log.info("Active brain root: %s", attach_result.root)


@dataclass
class InitResult:
    root: Path
    was_existing: bool
    dirs_created: list[str] = field(default_factory=list)


def init_brain(
    root: Path,
    *,
    model: str | None = None,
    dry_run: bool = False,
) -> InitResult:
    """Initialise a brain at the given root directory."""
    root = root.resolve()
    ensure_safe_temp_root_runtime(root, operation="initialise brain")

    if root.name == "knowledge" and path_exists(root.parent / ".brain-sync" / "brain.json"):
        raise ValueError(
            f"Path appears to be the '{root.name}/' folder inside an existing brain at {root.parent}. "
            f"Use the parent directory instead: brain-sync init {root.parent}"
        )

    was_existing = path_exists(root)

    if not was_existing:
        _ensure_dir(root, dry_run)

    dirs_created: list[str] = []
    for rel in [
        "knowledge",
        "knowledge/_core",
        ".brain-sync",
        ".brain-sync/sources",
    ]:
        if _ensure_dir(root / rel, dry_run):
            dirs_created.append(rel)

    # Write .brain-sync/brain.json (idempotent — always overwrite to latest)
    if not dry_run:
        manifest_file = brain_manifest_path(root)
        version_data = json.dumps({"version": BRAIN_MANIFEST_VERSION}, indent=2) + "\n"
        atomic_write_bytes(manifest_file, version_data.encode("utf-8"))
        source_manifests_dir(root).mkdir(parents=True, exist_ok=True)
        log.info("Wrote %s", manifest_file)

    # Install skill to Claude skill directory (MCP tools handle all context)
    _copy_resource(
        "brain_sync.interfaces.mcp.resources.brain_sync",
        "SKILL.md",
        skill_install_dir() / "SKILL.md",
        dry_run,
    )

    _register_brain_root(root, model=model, dry_run=dry_run)

    return InitResult(root=root, was_existing=was_existing, dirs_created=dirs_created)


def update_skill() -> list[Path]:
    """Re-install SKILL.md to the skill directory.

    Returns list of updated file paths.
    """
    updated: list[Path] = []
    skill_dir = skill_install_dir()
    _copy_resource(
        "brain_sync.interfaces.mcp.resources.brain_sync",
        "SKILL.md",
        skill_dir / "SKILL.md",
    )
    updated.append(skill_dir / "SKILL.md")
    # Clean up legacy CORE_INSTRUCTIONS.md if present
    legacy = skill_dir / "CORE_INSTRUCTIONS.md"
    if legacy.exists():
        legacy.unlink()
        log.info("Removed legacy %s", legacy)
    return updated
