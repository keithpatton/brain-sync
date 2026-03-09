from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


class ManifestError(Exception):
    pass


@dataclass(frozen=True)
class SourceEntry:
    url: str
    file: str
    include_links: bool = False
    include_children: bool = False
    include_attachments: bool = False
    link_depth: int = 1


@dataclass(frozen=True)
class Manifest:
    path: Path
    touch_dirty_relative_path: str | None
    sources: list[SourceEntry]


MANIFEST_FILENAME = "sync-manifest.yaml"


def load_manifest(path: Path) -> Manifest:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ManifestError(f"Cannot read {path}: {e}") from e

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ManifestError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(data, dict):
        raise ManifestError(f"Expected mapping at top level in {path}")

    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) == 0:
        raise ManifestError(f"'sources' must be a non-empty list in {path}")

    sources: list[SourceEntry] = []
    for i, entry in enumerate(raw_sources):
        if not isinstance(entry, dict):
            raise ManifestError(f"sources[{i}] must be a mapping in {path}")
        url = entry.get("url")
        file = entry.get("file")
        if not isinstance(url, str) or not url.strip():
            raise ManifestError(f"sources[{i}].url is required in {path}")
        if file is None:
            file = "auto"
        if not isinstance(file, str) or not file.strip():
            raise ManifestError(f"sources[{i}].file must be a string in {path}")
        file = file.strip()
        if file != "auto" and ("/" in file or "\\" in file):
            raise ManifestError(f"sources[{i}].file must be a bare filename or 'auto', got '{file}' in {path}")
        include_links = bool(entry.get("include_links", False))
        include_children = bool(entry.get("include_children", False))
        include_attachments = bool(entry.get("include_attachments", False))
        link_depth = entry.get("link_depth", 1)
        if not isinstance(link_depth, int) or link_depth not in (0, 1):
            raise ManifestError(f"sources[{i}].link_depth must be 0 or 1, got {link_depth!r} in {path}")
        sources.append(
            SourceEntry(
                url=url.strip(),
                file=file,
                include_links=include_links,
                include_children=include_children,
                include_attachments=include_attachments,
                link_depth=link_depth,
            )
        )

    dirty_path = data.get("touch_dirty_relative_path")
    if dirty_path is not None and not isinstance(dirty_path, str):
        raise ManifestError(f"touch_dirty_relative_path must be a string in {path}")

    return Manifest(
        path=path.resolve(),
        touch_dirty_relative_path=dirty_path,
        sources=sources,
    )


def discover_manifests(root: Path) -> dict[Path, Manifest]:
    manifests: dict[Path, Manifest] = {}
    for manifest_path in root.rglob(MANIFEST_FILENAME):
        try:
            manifests[manifest_path.resolve()] = load_manifest(manifest_path)
        except ManifestError as e:
            log.warning("Skipping invalid manifest: %s", e)
    return manifests
