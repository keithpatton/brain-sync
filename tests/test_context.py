from __future__ import annotations

import pytest

from brain_sync.context import (
    DiscoveredDoc,
    RelType,
    SafetyError,
    _local_path_for_doc,
    discover_links_from_html,
    ensure_context_dirs,
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


class TestDiscoverLinksFromHtml:
    def test_extracts_confluence_links(self):
        html = """
        <p>See <a href="https://x.atlassian.net/wiki/spaces/S/pages/456/Other+Page">Other Page</a></p>
        <p>And <a href="https://x.atlassian.net/wiki/spaces/S/pages/789/Third">Third</a></p>
        """
        links = discover_links_from_html(html, "x.atlassian.net")
        assert len(links) == 2
        ids = {lnk.canonical_id for lnk in links}
        assert "confluence:456" in ids
        assert "confluence:789" in ids
        assert all(lnk.relationship_type == RelType.LINK for lnk in links)

    def test_skips_anchors(self):
        html = '<a href="#section">Jump</a>'
        links = discover_links_from_html(html, "x.atlassian.net")
        assert len(links) == 0

    def test_skips_empty_href(self):
        html = '<a href="">Empty</a>'
        links = discover_links_from_html(html, "x.atlassian.net")
        assert len(links) == 0

    def test_skips_non_confluence_links(self):
        html = '<a href="https://google.com/foo">External</a>'
        links = discover_links_from_html(html, "x.atlassian.net")
        assert len(links) == 0

    def test_deduplicates(self):
        html = """
        <a href="https://x.atlassian.net/wiki/spaces/S/pages/123/A">A</a>
        <a href="https://x.atlassian.net/wiki/spaces/T/pages/123/B">B</a>
        """
        links = discover_links_from_html(html, "x.atlassian.net")
        assert len(links) == 1

    def test_handles_viewpage_format(self):
        html = '<a href="https://x.atlassian.net/wiki/pages/viewpage.action?pageId=999">View</a>'
        links = discover_links_from_html(html, "x.atlassian.net")
        assert len(links) == 1
        assert links[0].canonical_id == "confluence:999"

    def test_resolves_relative_urls(self):
        html = '<a href="/wiki/spaces/S/pages/555/Page">Relative</a>'
        links = discover_links_from_html(html, "x.atlassian.net")
        assert len(links) == 1
        assert links[0].canonical_id == "confluence:555"

    def test_link_title_is_none(self):
        html = '<a href="https://x.atlassian.net/wiki/spaces/S/pages/100/Title">Link</a>'
        links = discover_links_from_html(html, "x.atlassian.net")
        assert links[0].title is None


class TestReconcile:
    def test_all_new(self):
        discovered = [
            DiscoveredDoc("c:1", "url1", "T1", RelType.LINK),
            DiscoveredDoc("c:2", "url2", "T2", RelType.CHILD),
        ]
        to_add, to_check, to_remove = reconcile(discovered, [])
        assert len(to_add) == 2
        assert len(to_check) == 0
        assert len(to_remove) == 0

    def test_all_existing(self):
        discovered = [DiscoveredDoc("c:1", "url1", "T1", RelType.LINK)]
        existing = [Relationship("parent", "c:1", "link", "path", "confluence")]
        to_add, to_check, to_remove = reconcile(discovered, existing)
        assert len(to_add) == 0
        assert len(to_check) == 1
        assert len(to_remove) == 0

    def test_mixed(self):
        discovered = [
            DiscoveredDoc("c:1", "url1", "T1", RelType.LINK),
            DiscoveredDoc("c:3", "url3", "T3", RelType.CHILD),
        ]
        existing = [
            Relationship("parent", "c:1", "link", "p1", "confluence"),
            Relationship("parent", "c:2", "link", "p2", "confluence"),
        ]
        to_add, to_check, to_remove = reconcile(discovered, existing)
        assert len(to_add) == 1
        assert to_add[0].canonical_id == "c:3"
        assert len(to_check) == 1
        assert to_check[0].canonical_id == "c:1"
        assert to_remove == {"c:2"}


class TestLocalPathForDoc:
    def test_link_with_title(self, tmp_path):
        doc = DiscoveredDoc("confluence:123", "url", "My Page", RelType.LINK)
        path = _local_path_for_doc(doc, tmp_path)
        assert path == "_sync-context/linked/c123-my-page.md"

    def test_child_no_title(self, tmp_path):
        doc = DiscoveredDoc("confluence:456", "url", None, RelType.CHILD)
        path = _local_path_for_doc(doc, tmp_path)
        assert path == "_sync-context/children/c456.md"

    def test_attachment(self, tmp_path):
        doc = DiscoveredDoc("confluence-attachment:789", "url", "diagram.png", RelType.ATTACHMENT)
        path = _local_path_for_doc(doc, tmp_path)
        assert path == "_sync-context/attachments/a789-diagram.png"

    def test_attachment_no_title(self, tmp_path):
        doc = DiscoveredDoc("confluence-attachment:789", "url", None, RelType.ATTACHMENT)
        path = _local_path_for_doc(doc, tmp_path)
        assert path == "_sync-context/attachments/a789"

    def test_attachment_with_query_params(self, tmp_path):
        doc = DiscoveredDoc(
            "confluence-attachment:111",
            "url",
            "GetClipboardImage.ashx?Id=aa01b5ea&DC=GAU3&pkey=test",
            RelType.ATTACHMENT,
        )
        path = _local_path_for_doc(doc, tmp_path)
        assert path == "_sync-context/attachments/a111-getclipboardimage.ashx"

    def test_attachment_with_spaces(self, tmp_path):
        doc = DiscoveredDoc(
            "confluence-attachment:222",
            "url",
            "My Document (v2).pdf",
            RelType.ATTACHMENT,
        )
        path = _local_path_for_doc(doc, tmp_path)
        assert path == "_sync-context/attachments/a222-my-document-v2.pdf"


class TestEnsureContextDirs:
    def test_creates_dirs(self, tmp_path):
        context_root = ensure_context_dirs(tmp_path)
        assert (context_root / "linked").is_dir()
        assert (context_root / "children").is_dir()
        assert (context_root / "attachments").is_dir()


class TestRemoveSyncedFile:
    def test_removes_file_in_context(self, tmp_path):
        context_root = ensure_context_dirs(tmp_path)
        f = context_root / "linked" / "test.md"
        f.write_text("content")
        assert remove_synced_file(f, context_root) is True
        assert not f.exists()

    def test_refuses_outside_context(self, tmp_path):
        context_root = ensure_context_dirs(tmp_path)
        outside = tmp_path / "outside.md"
        outside.write_text("content")
        with pytest.raises(SafetyError):
            remove_synced_file(outside, context_root)

    def test_nonexistent_returns_false(self, tmp_path):
        context_root = ensure_context_dirs(tmp_path)
        f = context_root / "linked" / "gone.md"
        assert remove_synced_file(f, context_root) is False


class TestRediscoverRelationshipPaths:
    def test_updates_moved_file(self, tmp_path):
        """File moved from linked/ to a different folder — rediscovery finds it."""
        save_state(tmp_path, SyncState())
        manifest_dir = tmp_path / "project"
        manifest_dir.mkdir()

        # File was at _sync-context/linked/c200-page.md but moved
        new_loc = manifest_dir / "reorganised" / "c200-page.md"
        new_loc.parent.mkdir(parents=True)
        new_loc.write_text("content")

        rel = Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence:200",
            relationship_type="link",
            local_path="_sync-context/linked/c200-page.md",  # no longer exists
            source_type="confluence",
        )
        save_relationship(tmp_path, rel)

        updated = rediscover_relationship_paths(manifest_dir, tmp_path, [rel])
        assert len(updated) == 1
        assert "reorganised/c200-page.md" in updated[0].local_path
        assert updated[0].local_path != rel.local_path

        # DB should also be updated
        db_rels = load_relationships_for_primary(tmp_path, "confluence:100")
        assert "reorganised/c200-page.md" in db_rels[0].local_path

    def test_no_change_when_file_exists(self, tmp_path):
        """File still at original location — no change."""
        manifest_dir = tmp_path / "project"
        ctx = manifest_dir / "_sync-context" / "linked"
        ctx.mkdir(parents=True)
        (ctx / "c200-page.md").write_text("content")

        rel = Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence:200",
            relationship_type="link",
            local_path="_sync-context/linked/c200-page.md",
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
            canonical_id="confluence:200",
            relationship_type="link",
            local_path="_sync-context/linked/c200-page.md",
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
            local_path="_sync-context/attachments/a789-diagram.png",
            source_type="confluence",
        )
        save_relationship(tmp_path, rel)

        updated = rediscover_relationship_paths(manifest_dir, tmp_path, [rel])
        assert "docs/a789-diagram.png" in updated[0].local_path
