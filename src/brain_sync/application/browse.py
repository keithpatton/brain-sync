"""Application-owned brain browsing and query workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brain_sync.application.query_index import AreaIndex, load_area_index
from brain_sync.brain.fileops import iterdir_paths, path_is_dir, path_is_file, read_text
from brain_sync.brain.layout import SUMMARY_FILENAME, area_insights_dir, area_summary_path
from brain_sync.brain.tree import get_child_dirs, is_content_dir, is_readable_file

TRUNCATION_MARKER = "[truncated — call brain_sync_open_file(path=..., offset=N) to read more]"
MAX_SUMMARY_CHARS = 12000
MAX_CHILD_SUMMARY_CHARS = 2000
MAX_CHILDREN = 5
MAX_INSIGHT_FILE_CHARS = 8000
MAX_AREA_PAYLOAD = 40000
MAX_AREAS_LISTED = 50
MAX_GLOBAL_CONTEXT_FILE_CHARS = 4000
MAX_FILE_CHARS = 1_000_000
DEFAULT_FILE_CHARS = 200_000
ALLOWED_EXTENSIONS = frozenset({".md", ".txt", ".json", ".yaml", ".yml"})


@dataclass(frozen=True)
class AreaListing:
    path: str
    has_summary: bool


@dataclass(frozen=True)
class AreaChild:
    name: str
    has_summary: bool


@dataclass(frozen=True)
class GlobalContextView:
    path: str
    content: str
    present: bool


@dataclass(frozen=True)
class BrainQueryResult:
    matches: list[dict]
    areas: list[AreaListing]
    areas_truncated: bool
    total_areas: int
    global_context: GlobalContextView | None = None


@dataclass(frozen=True)
class BrainContextResult:
    global_context: GlobalContextView
    areas: list[AreaListing]
    areas_truncated: bool
    total_areas: int


@dataclass(frozen=True)
class OpenAreaResult:
    path: str
    insights: dict[str, str]
    children: list[AreaChild]
    total_children: int
    child_summaries: dict[str, str] | None = None
    children_truncated: bool | None = None
    knowledge_files: list[str] | None = None


@dataclass(frozen=True)
class OpenFileResult:
    path: str
    content: str
    offset: int
    limit: int
    truncated: bool
    next_offset: int | None = None
    hint: str | None = None


class AreaNotFoundError(LookupError):
    """Raised when an insight area is missing."""

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Area not found: {path}")


class BrainFileNotFoundError(FileNotFoundError):
    """Raised when a requested brain file is missing or escapes the root."""

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Brain file not found: {path}")


class UnsupportedBrainFileTypeError(ValueError):
    """Raised when a requested brain file extension is not supported."""

    def __init__(self, path: str, extension: str):
        self.path = path
        self.extension = extension
        super().__init__(f"Unsupported brain file type: {extension}")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n" + TRUNCATION_MARKER


def _safe_resolve(root: Path, rel_path: str) -> Path | None:
    try:
        resolved = (root / rel_path).resolve()
        if not resolved.is_relative_to(root.resolve()):
            return None
        return resolved
    except (OSError, ValueError):
        return None


def _read_file_safe(path: Path, max_chars: int | None = None) -> str:
    text = read_text(path, encoding="utf-8", errors="ignore")
    if max_chars is not None:
        return _truncate(text, max_chars)
    return text


def _load_global_context(root: Path) -> GlobalContextView:
    summary_path = area_summary_path(root, "_core")
    rel_path = "knowledge/_core/.brain-sync/insights/summary.md"
    if path_is_file(summary_path):
        return GlobalContextView(
            path=rel_path,
            content=_read_file_safe(summary_path, MAX_GLOBAL_CONTEXT_FILE_CHARS),
            present=True,
        )
    return GlobalContextView(path=rel_path, content="", present=False)


def _collect_areas(root: Path) -> list[AreaListing]:
    areas: list[AreaListing] = []
    knowledge_root = root / "knowledge"
    if not path_is_dir(knowledge_root):
        return areas

    def _walk(directory: Path, prefix: str) -> None:
        for child in iterdir_paths(directory):
            if not is_content_dir(child) or child.name == "_core":
                continue
            child_rel = prefix + "/" + child.name if prefix else child.name
            areas.append(
                AreaListing(
                    path=child_rel,
                    has_summary=path_is_file(area_summary_path(root, child_rel)),
                )
            )
            _walk(child, child_rel)

    _walk(knowledge_root, "")
    return areas


def query_brain(
    root: Path,
    *,
    query: str,
    include_global: bool = False,
    max_results: int = 5,
    current_index: AreaIndex | None = None,
) -> tuple[BrainQueryResult, AreaIndex]:
    """Search the brain and return a transport-neutral result."""
    index = load_area_index(root, current=current_index)
    matches = index.search(query, max_results=max_results)
    all_areas = _collect_areas(root)
    total = len(all_areas)
    result = BrainQueryResult(
        matches=matches,
        areas=all_areas[:MAX_AREAS_LISTED],
        areas_truncated=total > MAX_AREAS_LISTED,
        total_areas=total,
        global_context=_load_global_context(root) if include_global else None,
    )
    return result, index


def get_brain_context(root: Path) -> BrainContextResult:
    """Load global brain context and a capped area listing."""
    all_areas = _collect_areas(root)
    total = len(all_areas)
    return BrainContextResult(
        global_context=_load_global_context(root),
        areas=all_areas[:MAX_AREAS_LISTED],
        areas_truncated=total > MAX_AREAS_LISTED,
        total_areas=total,
    )


def open_area(
    root: Path,
    *,
    path: str,
    include_children: bool = False,
    include_knowledge_list: bool = False,
) -> OpenAreaResult:
    """Load insight artifacts for one knowledge area."""
    insights_dir = area_insights_dir(root, path)
    if insights_dir is None or not path_is_dir(insights_dir):
        raise AreaNotFoundError(path)

    knowledge_dir = _safe_resolve(root, "knowledge/" + path)
    payload_size = 0

    insights: dict[str, str] = {}
    for insight_path in iterdir_paths(insights_dir):
        if not path_is_file(insight_path) or insight_path.suffix.lower() not in {".md", ".txt"}:
            continue
        if insight_path.name.startswith("."):
            continue
        if "journal" in insight_path.relative_to(insights_dir).parts:
            continue

        max_chars = MAX_SUMMARY_CHARS if insight_path.name == SUMMARY_FILENAME else MAX_INSIGHT_FILE_CHARS
        content = _read_file_safe(insight_path, max_chars)
        insights[insight_path.name] = content
        payload_size += len(content)

    child_dirs = get_child_dirs(knowledge_dir) if knowledge_dir is not None and path_is_dir(knowledge_dir) else []
    children = [
        AreaChild(
            name=child_dir.name,
            has_summary=path_is_file(area_summary_path(root, f"{path}/{child_dir.name}" if path else child_dir.name)),
        )
        for child_dir in sorted(child_dirs, key=lambda child_dir: child_dir.name)
    ]

    child_summaries: dict[str, str] | None = None
    children_truncated: bool | None = None
    if include_children:
        child_summaries = {}
        children_truncated = False
        for index, child_dir in enumerate(sorted(child_dirs, key=lambda item: item.name)):
            if index >= MAX_CHILDREN:
                children_truncated = True
                break
            child_path = f"{path}/{child_dir.name}" if path else child_dir.name
            summary_path = area_summary_path(root, child_path)
            if path_is_file(summary_path):
                content = _read_file_safe(summary_path, MAX_CHILD_SUMMARY_CHARS)
                child_summaries[child_dir.name] = content
                payload_size += len(content)

    knowledge_files: list[str] | None = None
    if include_knowledge_list:
        knowledge_files = []
        if knowledge_dir is not None and path_is_dir(knowledge_dir):
            for knowledge_path in iterdir_paths(knowledge_dir):
                if is_readable_file(knowledge_path):
                    knowledge_files.append(knowledge_path.name)

    if payload_size > MAX_AREA_PAYLOAD:
        for key in list(insights.keys()):
            if key == SUMMARY_FILENAME:
                continue
            payload_size -= len(insights[key])
            insights[key] = TRUNCATION_MARKER
            payload_size += len(TRUNCATION_MARKER)

    if payload_size > MAX_AREA_PAYLOAD and child_summaries is not None:
        for key in list(child_summaries.keys()):
            old_len = len(child_summaries[key])
            child_summaries[key] = _truncate(child_summaries[key], MAX_CHILD_SUMMARY_CHARS // 2)
            payload_size -= old_len - len(child_summaries[key])

    if payload_size > MAX_AREA_PAYLOAD and SUMMARY_FILENAME in insights:
        old_len = len(insights[SUMMARY_FILENAME])
        insights[SUMMARY_FILENAME] = _truncate(insights[SUMMARY_FILENAME], MAX_AREA_PAYLOAD // 2)
        payload_size -= old_len - len(insights[SUMMARY_FILENAME])

    return OpenAreaResult(
        path=path,
        insights=insights,
        children=children,
        total_children=len(children),
        child_summaries=child_summaries,
        children_truncated=children_truncated,
        knowledge_files=knowledge_files,
    )


def open_file(root: Path, *, path: str, offset: int = 0, limit: int = DEFAULT_FILE_CHARS) -> OpenFileResult:
    """Read one supported text file from the brain root with pagination."""
    resolved = _safe_resolve(root, path)
    if resolved is None or not path_is_file(resolved):
        raise BrainFileNotFoundError(path)

    extension = resolved.suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedBrainFileTypeError(path, extension)

    clamped_limit = min(limit, MAX_FILE_CHARS)
    normalized_offset = max(0, offset)
    text = read_text(resolved, encoding="utf-8", errors="replace")

    if normalized_offset >= len(text):
        return OpenFileResult(
            path=path,
            content="",
            offset=normalized_offset,
            limit=clamped_limit,
            truncated=False,
        )

    raw = text[normalized_offset : normalized_offset + clamped_limit + 512]
    if len(raw) > clamped_limit:
        last_newline = raw.rfind("\n", 0, clamped_limit)
        chunk = raw[: last_newline + 1] if last_newline != -1 else raw[:clamped_limit]
        has_more = True
    else:
        chunk = raw
        has_more = False

    next_offset = normalized_offset + len(chunk)
    return OpenFileResult(
        path=path,
        content=chunk,
        offset=normalized_offset,
        limit=clamped_limit,
        truncated=has_more,
        next_offset=next_offset if has_more else None,
        hint=f'Call brain_sync_open_file(path="{path}", offset={next_offset}) to continue.' if has_more else None,
    )
