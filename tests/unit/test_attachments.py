from __future__ import annotations

import pytest

from brain_sync.attachments import (
    ATTACHMENTS_DIR,
    LEGACY_CONTEXT_DIR,
    DiscoveredDoc,
    RelType,
    SafetyError,
    attachment_local_path,
    ensure_attachment_dir,
    migrate_legacy_context,
    reconcile,
    remove_synced_file,
)
from brain_sync.state import (
    Relationship,
    SyncState,
    save_state,
)

pytestmark = pytest.mark.unit


class TestReconcile:
    def test_all_new(self):
        discovered = [
            DiscoveredDoc("c:1", "url1", "T1", RelType.ATTACHMENT),
            DiscoveredDoc("c:2", "url2", "T2", RelType.ATTACHMENT),
        ]
        to_add, to_check, to_remove = reconcile(discovered, [])
        assert len(to_add) == 2
        assert len(to_check) == 0
        assert len(to_remove) == 0

    def test_all_existing(self):
        discovered = [DiscoveredDoc("c:1", "url1", "T1", RelType.ATTACHMENT)]
        existing = [Relationship("parent", "c:1", "attachment", "confluence")]
        to_add, to_check, to_remove = reconcile(discovered, existing)
        assert len(to_add) == 0
        assert len(to_check) == 1
        assert len(to_remove) == 0

    def test_mixed(self):
        discovered = [
            DiscoveredDoc("c:1", "url1", "T1", RelType.ATTACHMENT),
            DiscoveredDoc("c:3", "url3", "T3", RelType.ATTACHMENT),
        ]
        existing = [
            Relationship("parent", "c:1", "attachment", "confluence"),
            Relationship("parent", "c:2", "attachment", "confluence"),
        ]
        to_add, to_check, to_remove = reconcile(discovered, existing)
        assert len(to_add) == 1
        assert to_add[0].canonical_id == "c:3"
        assert len(to_check) == 1
        assert to_check[0].canonical_id == "c:1"
        assert to_remove == {"c:2"}


class TestAttachmentLocalPath:
    def test_basic(self):
        path = attachment_local_path("c12345", "789", "diagram.png")
        assert path == "_attachments/c12345/a789-diagram.png"

    def test_no_title(self):
        path = attachment_local_path("c12345", "789", None)
        assert path == "_attachments/c12345/a789"

    def test_with_query_params(self):
        path = attachment_local_path(
            "c12345",
            "111",
            "GetClipboardImage.ashx?Id=aa01b5ea&DC=GAU3&pkey=test",
        )
        assert path == "_attachments/c12345/a111-getclipboardimage.ashx"

    def test_with_spaces(self):
        path = attachment_local_path("c12345", "222", "My Document (v2).pdf")
        assert path == "_attachments/c12345/a222-my-document-v2.pdf"


class TestEnsureAttachmentDir:
    def test_creates_dir(self, tmp_path):
        att_dir = ensure_attachment_dir(tmp_path, "c12345")
        assert att_dir.is_dir()
        assert att_dir == tmp_path / ATTACHMENTS_DIR / "c12345"


class TestRemoveSyncedFile:
    def test_removes_file_in_attachment_dir(self, tmp_path):
        att_dir = ensure_attachment_dir(tmp_path, "c12345")
        f = att_dir / "a789-diagram.png"
        f.write_text("content")
        assert remove_synced_file(f, att_dir) is True
        assert not f.exists()

    def test_refuses_outside_safe_root(self, tmp_path):
        att_dir = ensure_attachment_dir(tmp_path, "c12345")
        outside = tmp_path / "outside.md"
        outside.write_text("content")
        with pytest.raises(SafetyError):
            remove_synced_file(outside, att_dir)

    def test_nonexistent_returns_false(self, tmp_path):
        att_dir = ensure_attachment_dir(tmp_path, "c12345")
        f = att_dir / "gone.png"
        assert remove_synced_file(f, att_dir) is False


class TestMigrateLegacyContext:
    def test_migrates_attachments(self, tmp_path):
        """Attachment files are moved from _sync-context/attachments/ to _attachments/{source_dir_id}/."""
        save_state(tmp_path, SyncState())
        target_dir = tmp_path / "knowledge" / "area"

        # Create legacy layout
        legacy_att = target_dir / LEGACY_CONTEXT_DIR / "attachments"
        legacy_att.mkdir(parents=True)
        (legacy_att / "a789-diagram.png").write_bytes(b"png-data")
        (legacy_att / "a790-photo.jpg").write_bytes(b"jpg-data")
        # Legacy index file
        (target_dir / LEGACY_CONTEXT_DIR / "_index.md").write_text("old index")

        count = migrate_legacy_context(target_dir, "c100", "confluence:100", tmp_path)

        assert count == 2
        # Files moved to new location
        new_dir = target_dir / ATTACHMENTS_DIR / "c100"
        assert (new_dir / "a789-diagram.png").read_bytes() == b"png-data"
        assert (new_dir / "a790-photo.jpg").read_bytes() == b"jpg-data"
        # Legacy dir removed
        assert not (target_dir / LEGACY_CONTEXT_DIR).exists()

    def test_cleans_up_empty_legacy_dir(self, tmp_path):
        """Empty _sync-context/ (no attachments) is removed."""
        save_state(tmp_path, SyncState())
        target_dir = tmp_path / "knowledge" / "area"
        legacy_root = target_dir / LEGACY_CONTEXT_DIR
        legacy_root.mkdir(parents=True)
        # Just an index file, no attachments
        (legacy_root / "_index.md").write_text("old index")

        count = migrate_legacy_context(target_dir, "c100", "confluence:100", tmp_path)

        assert count == 0
        assert not legacy_root.exists()

    def test_noop_when_no_legacy_dir(self, tmp_path):
        """No _sync-context/ — returns 0 with no side effects."""
        target_dir = tmp_path / "knowledge" / "area"
        target_dir.mkdir(parents=True)

        count = migrate_legacy_context(target_dir, "c100", "confluence:100", tmp_path)
        assert count == 0

    def test_cleans_up_children_and_linked_dirs(self, tmp_path):
        """Legacy children/ and linked/ dirs are removed along with _sync-context/."""
        save_state(tmp_path, SyncState())
        target_dir = tmp_path / "knowledge" / "area"
        legacy_root = target_dir / LEGACY_CONTEXT_DIR
        (legacy_root / "children").mkdir(parents=True)
        (legacy_root / "linked").mkdir(parents=True)
        (legacy_root / "children" / "some-page.md").write_text("child content")

        count = migrate_legacy_context(target_dir, "c100", "confluence:100", tmp_path)

        assert count == 0
        assert not legacy_root.exists()

    def test_remigrates_bare_id_dir(self, tmp_path):
        """Files at _attachments/{bare_id}/ are re-migrated to _attachments/{prefixed_id}/."""
        save_state(tmp_path, SyncState())
        target_dir = tmp_path / "knowledge" / "area"

        # Simulate earlier migration that used bare ID
        bare_dir = target_dir / ATTACHMENTS_DIR / "100"
        bare_dir.mkdir(parents=True)
        (bare_dir / "a789-diagram.png").write_bytes(b"png-data")

        count = migrate_legacy_context(target_dir, "c100", "confluence:100", tmp_path)

        assert count == 1
        # File at prefixed location
        new_dir = target_dir / ATTACHMENTS_DIR / "c100"
        assert (new_dir / "a789-diagram.png").read_bytes() == b"png-data"
        # Bare dir removed
        assert not bare_dir.exists()
