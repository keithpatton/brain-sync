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
    rediscover_relationship_paths,
    remove_synced_file,
)
from brain_sync.state import (
    Relationship,
    SyncState,
    load_relationships_for_primary,
    save_relationship,
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
        existing = [Relationship("parent", "c:1", "attachment", "path", "confluence")]
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
            Relationship("parent", "c:1", "attachment", "p1", "confluence"),
            Relationship("parent", "c:2", "attachment", "p2", "confluence"),
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


class TestRediscoverRelationshipPaths:
    def test_updates_moved_file(self, tmp_path):
        """File moved from _attachments/ to a different folder — rediscovery finds it."""
        save_state(tmp_path, SyncState())
        manifest_dir = tmp_path / "project"
        manifest_dir.mkdir()

        # File was at _attachments/c100/a789-diagram.png but moved
        new_loc = manifest_dir / "reorganised" / "a789-diagram.png"
        new_loc.parent.mkdir(parents=True)
        new_loc.write_bytes(b"png")

        rel = Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence-attachment:789",
            relationship_type="attachment",
            local_path="_attachments/c100/a789-diagram.png",
            source_type="confluence",
        )
        save_relationship(tmp_path, rel)

        updated = rediscover_relationship_paths(manifest_dir, tmp_path, [rel])
        assert len(updated) == 1
        assert "reorganised/a789-diagram.png" in updated[0].local_path
        assert updated[0].local_path != rel.local_path

        # DB should also be updated
        db_rels = load_relationships_for_primary(tmp_path, "confluence:100")
        assert "reorganised/a789-diagram.png" in db_rels[0].local_path

    def test_no_change_when_file_exists(self, tmp_path):
        """File still at original location — no change."""
        manifest_dir = tmp_path / "project"
        att_dir = manifest_dir / "_attachments" / "c100"
        att_dir.mkdir(parents=True)
        (att_dir / "a789-diagram.png").write_bytes(b"png")

        rel = Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence-attachment:789",
            relationship_type="attachment",
            local_path="_attachments/c100/a789-diagram.png",
            source_type="confluence",
        )

        updated = rediscover_relationship_paths(manifest_dir, tmp_path, [rel])
        assert updated[0].local_path == rel.local_path

    def test_keeps_record_when_not_found(self, tmp_path):
        """File gone entirely — keep original record (will be re-synced)."""
        manifest_dir = tmp_path / "project"
        manifest_dir.mkdir()

        rel = Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence-attachment:789",
            relationship_type="attachment",
            local_path="_attachments/c100/a789-diagram.png",
            source_type="confluence",
        )

        updated = rediscover_relationship_paths(manifest_dir, tmp_path, [rel])
        assert updated[0].local_path == rel.local_path

    def test_finds_attachment(self, tmp_path):
        """Moved attachment is rediscovered."""
        manifest_dir = tmp_path / "project"
        new_loc = manifest_dir / "docs" / "a789-diagram.png"
        new_loc.parent.mkdir(parents=True)
        new_loc.write_bytes(b"png")

        save_state(tmp_path, SyncState())
        rel = Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence-attachment:789",
            relationship_type="attachment",
            local_path="_attachments/c100/a789-diagram.png",
            source_type="confluence",
        )
        save_relationship(tmp_path, rel)

        updated = rediscover_relationship_paths(manifest_dir, tmp_path, [rel])
        assert "docs/a789-diagram.png" in updated[0].local_path


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

        # Create relationship in DB
        save_relationship(
            tmp_path,
            Relationship(
                parent_canonical_id="confluence:100",
                canonical_id="confluence-attachment:789",
                relationship_type="attachment",
                local_path="_sync-context/attachments/a789-diagram.png",
                source_type="confluence",
            ),
        )
        save_relationship(
            tmp_path,
            Relationship(
                parent_canonical_id="confluence:100",
                canonical_id="confluence-attachment:790",
                relationship_type="attachment",
                local_path="_sync-context/attachments/a790-photo.jpg",
                source_type="confluence",
            ),
        )

        count = migrate_legacy_context(target_dir, "c100", "confluence:100", tmp_path)

        assert count == 2
        # Files moved to new location
        new_dir = target_dir / ATTACHMENTS_DIR / "c100"
        assert (new_dir / "a789-diagram.png").read_bytes() == b"png-data"
        assert (new_dir / "a790-photo.jpg").read_bytes() == b"jpg-data"
        # Legacy dir removed
        assert not (target_dir / LEGACY_CONTEXT_DIR).exists()
        # DB relationships updated
        rels = load_relationships_for_primary(tmp_path, "confluence:100")
        paths = {r.local_path for r in rels}
        assert "_attachments/c100/a789-diagram.png" in paths
        assert "_attachments/c100/a790-photo.jpg" in paths

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

        # Relationship in DB with bare-ID path
        save_relationship(
            tmp_path,
            Relationship(
                parent_canonical_id="confluence:100",
                canonical_id="confluence-attachment:789",
                relationship_type="attachment",
                local_path="_attachments/100/a789-diagram.png",
                source_type="confluence",
            ),
        )

        count = migrate_legacy_context(target_dir, "c100", "confluence:100", tmp_path)

        assert count == 1
        # File at prefixed location
        new_dir = target_dir / ATTACHMENTS_DIR / "c100"
        assert (new_dir / "a789-diagram.png").read_bytes() == b"png-data"
        # Bare dir removed
        assert not bare_dir.exists()
        # DB updated
        rels = load_relationships_for_primary(tmp_path, "confluence:100")
        assert rels[0].local_path == "_attachments/c100/a789-diagram.png"
