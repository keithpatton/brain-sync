"""Tests for attachment-ref resolution in the pipeline."""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.unit

# Inline the same logic used in pipeline.py to test it in isolation
_ATT_REF_RE = re.compile(r"\[([^\]]*)\]\(attachment-ref:([^)]+)\)")


def _resolve_attachment_refs(markdown: str, att_title_to_path: dict[str, str]) -> str:
    def _resolve(m: re.Match[str]) -> str:
        title = m.group(2)
        path = att_title_to_path.get(title)
        return f"[{m.group(1)}](./{path})" if path else m.group(0)

    return _ATT_REF_RE.sub(_resolve, markdown)


class TestResolveAttachmentRefs:
    def test_image_ref_resolved(self):
        md = "![diagram](attachment-ref:diagram.png)"
        result = _resolve_attachment_refs(md, {"diagram.png": "_sync-context/attachments/a789-diagram.png"})
        assert result == "![diagram](./_sync-context/attachments/a789-diagram.png)"

    def test_no_double_bang(self):
        """The ! prefix must not be duplicated."""
        md = "![alt](attachment-ref:photo.jpg)"
        result = _resolve_attachment_refs(md, {"photo.jpg": "attachments/a1-photo.jpg"})
        assert result.count("!") == 1
        assert result == "![alt](./attachments/a1-photo.jpg)"

    def test_link_ref_resolved(self):
        md = "[click here](attachment-ref:report.pdf)"
        result = _resolve_attachment_refs(md, {"report.pdf": "attachments/a2-report.pdf"})
        assert result == "[click here](./attachments/a2-report.pdf)"

    def test_unknown_ref_left_intact(self):
        md = "![missing](attachment-ref:unknown.png)"
        result = _resolve_attachment_refs(md, {"other.png": "attachments/a3-other.png"})
        assert result == md

    def test_empty_map(self):
        md = "![img](attachment-ref:file.png)"
        result = _resolve_attachment_refs(md, {})
        assert result == md

    def test_mixed_content(self):
        md = (
            "# Title\n\n"
            "Some text with ![inline](attachment-ref:img.png) image.\n\n"
            "A [regular link](https://example.com) stays.\n\n"
            "Another ![pic](attachment-ref:other.png) here."
        )
        mapping = {
            "img.png": "attachments/a1-img.png",
            "other.png": "attachments/a2-other.png",
        }
        result = _resolve_attachment_refs(md, mapping)
        assert "![inline](./attachments/a1-img.png)" in result
        assert "![pic](./attachments/a2-other.png)" in result
        assert "[regular link](https://example.com)" in result
