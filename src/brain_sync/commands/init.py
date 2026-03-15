"""Brain initialisation and skill installation commands."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from brain_sync.config import CONFIG_FILE, load_config, save_config
from brain_sync.fileops import atomic_write_bytes
from brain_sync.layout import BRAIN_MANIFEST_VERSION, brain_manifest_path, source_manifests_dir

log = logging.getLogger(__name__)

SKILL_INSTALL_DIR = Path.home() / ".claude" / "skills" / "brain-sync"


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
    if path.exists():
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
    """Register this brain root and optional settings in ~/.brain-sync/config.json."""
    if dry_run:
        log.info("[dry-run] Would register brain root in %s", CONFIG_FILE)
        return

    config = load_config()
    changed = False

    brains = config.get("brains", [])
    root_str = str(root)
    if root_str not in brains:
        brains.append(root_str)
        config["brains"] = brains
        changed = True

    if model:
        regen = config.get("regen", {})
        regen["model"] = model
        config["regen"] = regen
        changed = True

    if changed:
        save_config(config)
        log.info("Updated config in %s", CONFIG_FILE)


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

    if root.name == "knowledge" and (root.parent / ".brain-sync" / "brain.json").exists():
        raise ValueError(
            f"Path appears to be the '{root.name}/' folder inside an existing brain at {root.parent}. "
            f"Use the parent directory instead: brain-sync init {root.parent}"
        )

    was_existing = root.exists()

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
        "brain_sync.skills.brain_sync",
        "SKILL.md",
        SKILL_INSTALL_DIR / "SKILL.md",
        dry_run,
    )

    _register_brain_root(root, model=model, dry_run=dry_run)

    return InitResult(root=root, was_existing=was_existing, dirs_created=dirs_created)


def update_skill() -> list[Path]:
    """Re-install SKILL.md to the skill directory.

    Returns list of updated file paths.
    """
    updated: list[Path] = []
    _copy_resource(
        "brain_sync.skills.brain_sync",
        "SKILL.md",
        SKILL_INSTALL_DIR / "SKILL.md",
    )
    updated.append(SKILL_INSTALL_DIR / "SKILL.md")
    # Clean up legacy CORE_INSTRUCTIONS.md if present
    legacy = SKILL_INSTALL_DIR / "CORE_INSTRUCTIONS.md"
    if legacy.exists():
        legacy.unlink()
        log.info("Removed legacy %s", legacy)
    return updated
