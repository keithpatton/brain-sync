"""Compatibility shim for docx conversion helpers."""

from brain_sync.sources.docx import (
    _W_NS,
    append_comments_to_markdown,
    docx_to_markdown,
    extract_comments,
    extract_comments_from_bytes,
)

__all__ = [
    "_W_NS",
    "append_comments_to_markdown",
    "docx_to_markdown",
    "extract_comments",
    "extract_comments_from_bytes",
]
