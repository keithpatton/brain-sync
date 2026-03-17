"""Application-owned local file import and removal workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brain_sync.brain.fileops import ADDFILE_EXTENSIONS, path_exists, path_is_file
from brain_sync.brain.repository import BrainRepository, BrainRepositoryInvariantError
from brain_sync.brain.tree import normalize_path


@dataclass(frozen=True)
class LocalFileAddResult:
    action: str
    path: str


@dataclass(frozen=True)
class LocalFileRemoveResult:
    path: str
    hint: str


class LocalFileNotFoundError(FileNotFoundError):
    """Raised when the source file to import does not exist."""

    def __init__(self, source: Path):
        self.source = source
        super().__init__(f"Local file not found: {source}")


class UnsupportedLocalFileTypeError(ValueError):
    """Raised when a local file extension is not supported for import."""

    def __init__(self, extension: str):
        self.extension = extension
        self.supported_extensions = tuple(sorted(ADDFILE_EXTENSIONS))
        super().__init__(
            f"Unsupported file type: {extension}. add-file supports: {', '.join(self.supported_extensions)}"
        )


class InvalidKnowledgePathError(ValueError):
    """Raised when a knowledge-relative removal path is invalid."""

    def __init__(self, path: str, message: str):
        self.path = path
        super().__init__(message)


class KnowledgeFileNotFoundError(FileNotFoundError):
    """Raised when a requested knowledge file is missing."""

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Knowledge file not found: {path}")


class KnowledgePathIsDirectoryError(IsADirectoryError):
    """Raised when a removal target resolves to a directory."""

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Knowledge path is a directory: {path}")


class LocalFileCollisionError(ValueError):
    """Raised when import collision suffixes are exhausted."""

    pass


def add_local_file(root: Path, *, source: Path, target_path: str, copy: bool = True) -> LocalFileAddResult:
    """Copy or move a local file into one knowledge area."""
    resolved_source = source.resolve()
    if not resolved_source.exists() or not resolved_source.is_file():
        raise LocalFileNotFoundError(resolved_source)

    extension = resolved_source.suffix.lower()
    if extension not in ADDFILE_EXTENSIONS:
        raise UnsupportedLocalFileTypeError(extension)

    repository = BrainRepository(root)
    try:
        destination = repository.add_local_file(resolved_source, target_path, copy=copy)
    except BrainRepositoryInvariantError as exc:
        if "all numeric suffixes are taken" in str(exc):
            raise LocalFileCollisionError(str(exc)) from exc
        raise InvalidKnowledgePathError(target_path, str(exc)) from exc

    return LocalFileAddResult(
        action="copied" if copy else "moved",
        path=normalize_path(destination.relative_to(root)),
    )


def remove_local_file(root: Path, *, path: str) -> LocalFileRemoveResult:
    """Remove one local non-synced file from the knowledge tree."""
    repository = BrainRepository(root)
    target = root / "knowledge" / path
    try:
        deleted = repository.delete_local_file(path)
    except BrainRepositoryInvariantError as exc:
        if path_exists(target) and not path_is_file(target):
            raise KnowledgePathIsDirectoryError(path) from exc
        raise InvalidKnowledgePathError(path, str(exc)) from exc

    if not deleted:
        raise KnowledgeFileNotFoundError(path)

    return LocalFileRemoveResult(
        path=path,
        hint="Insights will update on next regen.",
    )
