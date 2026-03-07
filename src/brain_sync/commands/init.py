"""Brain initialisation and skill installation commands."""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from brain_sync.commands.context import CONFIG_DIR, CONFIG_FILE

log = logging.getLogger(__name__)

SKILL_INSTALL_DIR = Path.home() / ".claude" / "skills" / "brain-sync"


def _template_path(name: str) -> Path:
    """Get the path to a template file bundled with the package."""
    ref = resources.files("brain_sync.templates").joinpath(name)
    with resources.as_file(ref) as p:
        return Path(p)


def _copy_template(name: str, dest: Path, dry_run: bool = False) -> bool:
    """Copy a template file to dest. Returns True if copied."""
    if dry_run:
        log.info("[dry-run] Would copy template %s -> %s", name, dest)
        return False
    src = _template_path(name)
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


def _register_brain_root(root: Path, dry_run: bool = False) -> None:
    """Register this brain root in ~/.brain-sync/config.json."""
    if dry_run:
        log.info("[dry-run] Would register brain root in %s", CONFIG_FILE)
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    config: dict = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            config = {}

    brains = config.get("brains", [])
    root_str = str(root)
    if root_str not in brains:
        brains.append(root_str)
        config["brains"] = brains
        CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        log.info("Registered brain root in %s", CONFIG_FILE)


@dataclass
class InitResult:
    root: Path
    was_existing: bool
    dirs_created: list[str] = field(default_factory=list)


def init_brain(root: Path, *, dry_run: bool = False) -> InitResult:
    """Initialise a brain at the given root directory."""
    root = root.resolve()
    was_existing = root.exists()

    if not was_existing:
        _ensure_dir(root, dry_run)

    dirs_created: list[str] = []
    for rel in ["knowledge", "knowledge/_core", "insights", "insights/_core"]:
        if _ensure_dir(root / rel, dry_run):
            dirs_created.append(rel)

    _copy_template("SKILL.md", SKILL_INSTALL_DIR / "SKILL.md", dry_run)
    _copy_template("INSTRUCTIONS.md", SKILL_INSTALL_DIR / "INSTRUCTIONS.md", dry_run)

    if not dry_run:
        from brain_sync.state import _connect
        conn = _connect(root)
        conn.close()
        log.info("SQLite state database ready at %s", root / ".sync-state.sqlite")

    _register_brain_root(root, dry_run)

    return InitResult(root=root, was_existing=was_existing, dirs_created=dirs_created)


def update_skill() -> list[Path]:
    """Re-install SKILL.md and INSTRUCTIONS.md from templates.

    Returns list of updated file paths.
    """
    updated: list[Path] = []
    for name in ["SKILL.md", "INSTRUCTIONS.md"]:
        dest = SKILL_INSTALL_DIR / name
        _copy_template(name, dest)
        updated.append(dest)
    return updated
