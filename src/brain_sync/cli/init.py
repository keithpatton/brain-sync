from __future__ import annotations

import json
import logging
import shutil
from importlib import resources
from pathlib import Path

log = logging.getLogger(__name__)

SKILL_INSTALL_DIR = Path.home() / ".claude" / "skills" / "brain-sync"
CONFIG_DIR = Path.home() / ".brain-sync"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _template_path(name: str) -> Path:
    """Get the path to a template file bundled with the package."""
    ref = resources.files("brain_sync.templates").joinpath(name)
    # resources.files returns a Traversable; for reading we need the real path
    with resources.as_file(ref) as p:
        return Path(p)


def _copy_template(name: str, dest: Path, dry_run: bool = False) -> None:
    """Copy a template file to dest, creating parent dirs as needed."""
    if dry_run:
        log.info("[dry-run] Would copy template %s -> %s", name, dest)
        return
    src = _template_path(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dest))
    log.info("Installed %s", dest)


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


def run_init(root: Path, dry_run: bool = False) -> None:
    """Initialise a brain at the given root directory."""
    root = root.resolve()
    is_existing = root.exists()

    if not is_existing:
        _ensure_dir(root, dry_run)

    print(f"{'[dry-run] ' if dry_run else ''}Initialising brain at: {root}")
    if is_existing:
        print("  Existing directory detected, will add missing structure")

    # Create required directories
    _ensure_dir(root / "knowledge", dry_run)
    _ensure_dir(root / "knowledge" / "_core", dry_run)
    _ensure_dir(root / "insights", dry_run)
    _ensure_dir(root / "insights" / "_core", dry_run)

    # Install skill (SKILL.md + INSTRUCTIONS.md into skill dir)
    _copy_template("SKILL.md", SKILL_INSTALL_DIR / "SKILL.md", dry_run)
    _copy_template("INSTRUCTIONS.md", SKILL_INSTALL_DIR / "INSTRUCTIONS.md", dry_run)

    # Initialise SQLite (importing here to avoid circular deps)
    if not dry_run:
        from brain_sync.state import _connect
        conn = _connect(root)
        conn.close()
        log.info("SQLite state database ready at %s", root / ".sync-state.sqlite")

    # Register in config
    _register_brain_root(root, dry_run)

    print(f"{'[dry-run] ' if dry_run else ''}Brain initialised successfully")
    print(f"  knowledge/       - Add your content here")
    print(f"  knowledge/_core/ - Always-loaded reference material")
    print(f"  insights/        - Auto-generated summaries and journal")
    print(f"  Skill installed to {SKILL_INSTALL_DIR}")
