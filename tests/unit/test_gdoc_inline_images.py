"""Unit tests for Google Docs inline image support."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

pytest.importorskip("google.auth", reason="google-auth not installed (install brain-sync[google])")

from brain_sync.attachments import ATTACHMENTS_DIR, process_inline_images
from brain_sync.fileops import canonical_prefix
from brain_sync.sources.base import DiscoveredImage
from brain_sync.sources.googledocs.rest import (
    InlineImageInfo,
    TabData,
    TabsDocument,
    _extract_inline_objects,
    _walk_body,
    _walk_body_markdown,
    extract_canonical_text,
    generate_tabs_markdown,
    image_filename,
)
from brain_sync.state import SyncState, save_state

pytestmark = pytest.mark.unit


# --- _walk_body_markdown with inline images ---


class TestWalkBodyMarkdownInlineImages:
    def _inline_element(self, obj_id: str) -> dict:
        return {"inlineObjectElement": {"inlineObjectId": obj_id}}

    def _text_element(self, text: str) -> dict:
        return {"textRun": {"content": text}}

    def _para(self, *elements: dict) -> dict:
        return {"paragraph": {"elements": list(elements)}}

    def _make_inline_objects(self) -> dict[str, InlineImageInfo]:
        return {
            "kix.abc123": InlineImageInfo(
                object_id="kix.abc123",
                content_uri="https://example.com/img1.png",
                title="Diagram",
                description="Architecture diagram",
                mime_type="image/png",
            ),
            "kix.def456": InlineImageInfo(
                object_id="kix.def456",
                content_uri="https://example.com/img2.jpg",
                title=None,
                description=None,
                mime_type="image/jpeg",
            ),
        }

    def test_inline_image_emits_attachment_ref(self):
        content = [self._para(self._inline_element("kix.abc123"))]
        parts: list[str] = []
        _walk_body_markdown(content, parts, self._make_inline_objects(), "docXYZ")
        assert len(parts) == 1
        assert parts[0] == "![Architecture diagram](attachment-ref:gdoc-image:docXYZ:kix.abc123)"

    def test_inline_image_alt_fallback_to_title(self):
        """When description is None, alt should use title."""
        inline_objects = {
            "kix.abc123": InlineImageInfo(
                object_id="kix.abc123",
                content_uri="https://example.com/img.png",
                title="My Title",
                description=None,
            ),
        }
        content = [self._para(self._inline_element("kix.abc123"))]
        parts: list[str] = []
        _walk_body_markdown(content, parts, inline_objects, "doc1")
        assert "![My Title]" in parts[0]

    def test_inline_image_alt_fallback_to_image(self):
        """When both description and title are None, alt should be 'image'."""
        content = [self._para(self._inline_element("kix.def456"))]
        parts: list[str] = []
        _walk_body_markdown(content, parts, self._make_inline_objects(), "doc1")
        assert "![image]" in parts[0]

    def test_mixed_text_and_image_paragraph(self):
        content = [
            self._para(
                self._text_element("See the diagram: "),
                self._inline_element("kix.abc123"),
                self._text_element(" above."),
            )
        ]
        parts: list[str] = []
        _walk_body_markdown(content, parts, self._make_inline_objects(), "docXYZ")
        assert len(parts) == 1
        result = parts[0]
        assert "See the diagram:" in result
        assert "![Architecture diagram](attachment-ref:gdoc-image:docXYZ:kix.abc123)" in result
        assert "above." in result

    def test_unknown_object_id_ignored(self):
        content = [self._para(self._inline_element("kix.unknown"))]
        parts: list[str] = []
        _walk_body_markdown(content, parts, self._make_inline_objects(), "doc1")
        assert len(parts) == 0  # unknown image, no text → empty

    def test_no_inline_objects_skips_images(self):
        """When inline_objects is None, inlineObjectElement is ignored (backwards compat)."""
        content = [self._para(self._text_element("Hello "), self._inline_element("kix.abc123"))]
        parts: list[str] = []
        _walk_body_markdown(content, parts)
        assert len(parts) == 1
        assert parts[0] == "Hello"


class TestWalkBodyFingerprintWithImages:
    def test_img_marker_in_fingerprint(self):
        content = [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Before "}},
                        {"inlineObjectElement": {"inlineObjectId": "kix.abc"}},
                        {"textRun": {"content": " after"}},
                    ]
                }
            }
        ]
        parts: list[str] = []
        _walk_body(content, parts)
        assert "IMG:kix.abc" in parts

    def test_image_changes_fingerprint(self):
        content_with_img = [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "text"}},
                        {"inlineObjectElement": {"inlineObjectId": "kix.img1"}},
                    ]
                }
            }
        ]
        content_without_img = [{"paragraph": {"elements": [{"textRun": {"content": "text"}}]}}]
        parts1: list[str] = []
        parts2: list[str] = []
        _walk_body(content_with_img, parts1)
        _walk_body(content_without_img, parts2)
        assert parts1 != parts2


class TestExtractCanonicalTextWithImages:
    def test_img_marker_included(self):
        content = [
            {
                "paragraph": {
                    "elements": [
                        {"inlineObjectElement": {"inlineObjectId": "kix.obj1"}},
                        {"textRun": {"content": "caption"}},
                    ]
                }
            }
        ]
        doc = TabsDocument(title=None, tabs=[TabData(tab_id="t1", title="Tab", number="1", body_content=content)])
        text = extract_canonical_text(doc)
        assert "IMG:kix.obj1" in text


# --- generate_tabs_markdown with inline images ---


class TestGenerateTabsMarkdownWithImages:
    def test_single_tab_with_image(self):
        inline_objects = {
            "kix.img1": InlineImageInfo(
                object_id="kix.img1",
                content_uri="https://example.com/img.png",
                title="Photo",
                description="A photo",
            ),
        }
        content = [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Look at this: "}},
                        {"inlineObjectElement": {"inlineObjectId": "kix.img1"}},
                    ]
                }
            }
        ]
        doc = TabsDocument(
            title="Doc",
            tabs=[TabData(tab_id="t1", title="Main", number="1", body_content=content, inline_objects=inline_objects)],
        )
        md = generate_tabs_markdown(doc, doc_id="abc123")
        assert "![A photo](attachment-ref:gdoc-image:abc123:kix.img1)" in md


# --- _extract_inline_objects ---


class TestExtractInlineObjects:
    def test_extracts_image(self):
        raw = {
            "kix.obj1": {
                "inlineObjectProperties": {
                    "embeddedObject": {
                        "title": "My Image",
                        "description": "A description",
                        "imageProperties": {
                            "contentUri": "https://lh3.googleusercontent.com/abc",
                        },
                    }
                }
            }
        }
        result = _extract_inline_objects(raw)
        assert "kix.obj1" in result
        img = result["kix.obj1"]
        assert img.object_id == "kix.obj1"
        assert img.content_uri == "https://lh3.googleusercontent.com/abc"
        assert img.title == "My Image"
        assert img.description == "A description"

    def test_skips_non_image_objects(self):
        raw = {
            "kix.obj1": {
                "inlineObjectProperties": {
                    "embeddedObject": {
                        "title": "Not an image",
                    }
                }
            }
        }
        result = _extract_inline_objects(raw)
        assert len(result) == 0

    def test_skips_missing_content_uri(self):
        raw = {
            "kix.obj1": {
                "inlineObjectProperties": {
                    "embeddedObject": {
                        "imageProperties": {},  # no contentUri
                    }
                }
            }
        }
        result = _extract_inline_objects(raw)
        assert len(result) == 0

    def test_empty_title_becomes_none(self):
        raw = {
            "kix.obj1": {
                "inlineObjectProperties": {
                    "embeddedObject": {
                        "title": "",
                        "description": "",
                        "imageProperties": {"contentUri": "https://example.com/img"},
                    }
                }
            }
        }
        result = _extract_inline_objects(raw)
        assert result["kix.obj1"].title is None
        assert result["kix.obj1"].description is None


# --- canonical_prefix for gdoc-image ---


class TestCanonicalPrefixGdocImage:
    def test_gdoc_image_three_parts(self):
        assert canonical_prefix("gdoc-image:docABC:kix.obj1") == "gidocABC-kix.obj1-"

    def test_gdoc_image_two_parts(self):
        assert canonical_prefix("gdoc-image:docABC") == "gidocABC-"

    def test_does_not_interfere_with_gdoc(self):
        assert canonical_prefix("gdoc:abc123") == "gabc123-"

    def test_canonical_id_includes_doc_id(self):
        """Ensure docId is part of the prefix to avoid cross-doc collision."""
        prefix1 = canonical_prefix("gdoc-image:doc1:kix.obj1")
        prefix2 = canonical_prefix("gdoc-image:doc2:kix.obj1")
        assert prefix1 != prefix2


# --- image_filename ---


class TestImageFilename:
    def test_with_title_and_mime(self):
        result = image_filename("kix.abc", "my-diagram.png", None, "image/png")
        assert result.startswith("akix.abc-")
        assert result.endswith(".png")

    def test_no_title_uses_object_id(self):
        result = image_filename("kix.abc123", None, None, "image/png")
        assert result.startswith("akix.abc123-")
        assert result.endswith(".png")

    def test_description_used_as_slug(self):
        result = image_filename("kix.abc", None, "Architecture Overview", "image/jpeg")
        assert "architecture-overview" in result

    def test_unknown_mime_fallback_to_bin(self):
        result = image_filename("kix.abc", None, None, "application/octet-stream")
        assert result.endswith(".bin")

    def test_no_mime_no_title_fallback(self):
        result = image_filename("kix.abc", None, None, None)
        assert result.endswith(".bin")

    def test_long_slug_truncated(self):
        long_title = "a" * 200 + ".png"
        result = image_filename("kix.abc", long_title, None, "image/png")
        # slug should be max 80 chars
        stem = result.split("-", 1)[1].rsplit(".", 1)[0]
        assert len(stem) <= 80


# --- MIME-to-extension fallback chain ---


class TestMimeExtensionFallback:
    def test_png(self):
        result = image_filename("obj1", None, None, "image/png")
        assert result.endswith(".png")

    def test_jpeg(self):
        result = image_filename("obj1", None, None, "image/jpeg")
        assert result.endswith(".jpg")

    def test_gif(self):
        result = image_filename("obj1", None, None, "image/gif")
        assert result.endswith(".gif")

    def test_webp(self):
        result = image_filename("obj1", None, None, "image/webp")
        assert result.endswith(".webp")

    def test_title_derived_extension(self):
        result = image_filename("obj1", "photo.bmp", None, None)
        assert result.endswith(".bmp")


# --- Deduplication across tabs ---


class TestDeduplicationAcrossTabs:
    def test_same_object_in_two_tabs_deduplicated(self):
        """Same objectId in multiple tabs should produce one DiscoveredImage."""
        inline_objects = {
            "kix.img1": InlineImageInfo(
                object_id="kix.img1",
                content_uri="https://example.com/img.png",
                title="Photo",
            ),
        }

        tabs_doc = TabsDocument(
            title="Doc",
            tabs=[
                TabData(tab_id="t1", title="Tab 1", number="1", body_content=[], inline_objects=inline_objects),
                TabData(tab_id="t2", title="Tab 2", number="2", body_content=[], inline_objects=inline_objects),
            ],
        )

        # Simulate the dedup logic from the adapter
        images_by_cid: dict[str, DiscoveredImage] = {}
        doc_id = "docXYZ"
        for tab in tabs_doc.tabs:
            for obj_id, img in tab.inline_objects.items():
                cid = f"gdoc-image:{doc_id}:{obj_id}"
                if cid not in images_by_cid:
                    images_by_cid[cid] = DiscoveredImage(
                        canonical_id=cid,
                        download_url=img.content_uri,
                        title=img.title,
                        mime_type=img.mime_type,
                    )

        assert len(images_by_cid) == 1
        assert "gdoc-image:docXYZ:kix.img1" in images_by_cid


# --- process_inline_images ---


class TestProcessInlineImages:
    @pytest.fixture
    def setup_root(self, tmp_path):
        save_state(tmp_path, SyncState())
        target_dir = tmp_path / "knowledge" / "area"
        target_dir.mkdir(parents=True)
        return tmp_path, target_dir

    def _make_image(self, doc_id: str = "doc1", obj_id: str = "kix.img1") -> DiscoveredImage:
        return DiscoveredImage(
            canonical_id=f"gdoc-image:{doc_id}:{obj_id}",
            download_url=f"https://example.com/{obj_id}.png",
            title="diagram.png",
            mime_type="image/png",
        )

    async def test_downloads_and_stores_new_image(self, setup_root):
        root, target_dir = setup_root
        img = self._make_image()

        mock_response = MagicMock()
        mock_response.content = b"PNG-DATA"
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "image/png"}
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await process_inline_images(
            images=[img],
            headers={"Authorization": "Bearer token"},
            client=client,
            target_dir=target_dir,
            primary_canonical_id="gdoc:doc1",
            root=root,
        )

        assert len(result) == 1
        cid = "gdoc-image:doc1:kix.img1"
        assert cid in result
        local_path = result[cid]
        assert (target_dir / local_path).exists()
        assert (target_dir / local_path).read_bytes() == b"PNG-DATA"

    async def test_download_failure_skips_image(self, setup_root):
        root, target_dir = setup_root
        img = self._make_image()

        client = AsyncMock()
        client.get.side_effect = httpx.ConnectError("connection refused")

        result = await process_inline_images(
            images=[img],
            headers={},
            client=client,
            target_dir=target_dir,
            primary_canonical_id="gdoc:doc1",
            root=root,
        )

        # Image should be skipped, not raise
        assert len(result) == 0

    async def test_content_hash_skip_avoids_rewrite(self, setup_root):
        root, target_dir = setup_root
        img = self._make_image()

        # First sync
        mock_response = MagicMock()
        mock_response.content = b"PNG-DATA"
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "image/png"}
        client = AsyncMock()
        client.get.return_value = mock_response

        result1 = await process_inline_images(
            images=[img],
            headers={},
            client=client,
            target_dir=target_dir,
            primary_canonical_id="gdoc:doc1",
            root=root,
        )

        # Record mtime
        local_path = result1["gdoc-image:doc1:kix.img1"]
        mtime_before = (target_dir / local_path).stat().st_mtime

        # Second sync — same content
        import time

        time.sleep(0.05)  # ensure mtime would differ if rewritten
        await process_inline_images(
            images=[img],
            headers={},
            client=client,
            target_dir=target_dir,
            primary_canonical_id="gdoc:doc1",
            root=root,
        )

        mtime_after = (target_dir / local_path).stat().st_mtime
        assert mtime_before == mtime_after  # file not rewritten

    async def test_removal_of_stale_image(self, setup_root):
        root, target_dir = setup_root
        img = self._make_image()

        mock_response = MagicMock()
        mock_response.content = b"PNG-DATA"
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "image/png"}
        client = AsyncMock()
        client.get.return_value = mock_response

        # First sync — add image
        await process_inline_images(
            images=[img],
            headers={},
            client=client,
            target_dir=target_dir,
            primary_canonical_id="gdoc:doc1",
            root=root,
        )

        # Second sync — no images (removed from doc)
        result = await process_inline_images(
            images=[],
            headers={},
            client=client,
            target_dir=target_dir,
            primary_canonical_id="gdoc:doc1",
            root=root,
        )

        assert len(result) == 0
        # Attachment dir should exist but be empty (or image file gone)
        att_dir = target_dir / ATTACHMENTS_DIR / "gdoc1"
        if att_dir.exists():
            assert list(att_dir.iterdir()) == []

    async def test_file_missing_triggers_redownload(self, setup_root):
        root, target_dir = setup_root
        img = self._make_image()

        mock_response = MagicMock()
        mock_response.content = b"PNG-DATA"
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "image/png"}
        client = AsyncMock()
        client.get.return_value = mock_response

        # First sync
        result1 = await process_inline_images(
            images=[img],
            headers={},
            client=client,
            target_dir=target_dir,
            primary_canonical_id="gdoc:doc1",
            root=root,
        )

        # Delete the file manually
        local_path = result1["gdoc-image:doc1:kix.img1"]
        (target_dir / local_path).unlink()

        # Second sync — should re-download
        result2 = await process_inline_images(
            images=[img],
            headers={},
            client=client,
            target_dir=target_dir,
            primary_canonical_id="gdoc:doc1",
            root=root,
        )

        assert "gdoc-image:doc1:kix.img1" in result2
        assert (target_dir / result2["gdoc-image:doc1:kix.img1"]).exists()


# --- GoogleDocsAdapter capabilities ---


class TestGoogleDocsAdapterCapabilities:
    def test_supports_attachments_true(self):
        from brain_sync.sources.googledocs import GoogleDocsAdapter

        caps = GoogleDocsAdapter().capabilities
        assert caps.supports_attachments is True


# --- attachment-ref regex with colons ---


class TestAttachmentRefWithColons:
    """Verify the pipeline regex handles canonical IDs containing colons."""

    def test_colon_in_ref_id_matched(self):
        import re

        pattern = re.compile(r"\[([^\]]*)\]\(attachment-ref:([^)]+)\)")
        md = "![diagram](attachment-ref:gdoc-image:doc1:kix.abc123)"
        m = pattern.search(md)
        assert m is not None
        assert m.group(1) == "diagram"
        assert m.group(2) == "gdoc-image:doc1:kix.abc123"
