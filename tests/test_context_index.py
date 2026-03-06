from __future__ import annotations

from brain_sync.context import CONTEXT_DIR
from brain_sync.context_index import INDEX_FILENAME, generate_context_index
from brain_sync.state import Relationship, SyncState, save_relationship, save_state


def _setup_db(tmp_path):
    """Ensure DB exists."""
    save_state(tmp_path, SyncState())


class TestGenerateContextIndex:
    def test_generates_index_with_sections(self, tmp_path):
        _setup_db(tmp_path)
        manifest_dir = tmp_path / "project"
        manifest_dir.mkdir()

        save_relationship(tmp_path, Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence:200",
            relationship_type="link",
            local_path="_sync-context/linked/c200-page-a.md",
            source_type="confluence",
        ))
        save_relationship(tmp_path, Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence:300",
            relationship_type="child",
            local_path="_sync-context/children/c300-child.md",
            source_type="confluence",
        ))

        generate_context_index("confluence:100", manifest_dir, tmp_path)

        index = (manifest_dir / CONTEXT_DIR / INDEX_FILENAME).read_text()
        assert "# Context Index" in index
        assert "confluence:100" in index
        assert "## Linked Documents" in index
        assert "c200-page-a.md" in index
        assert "## Child Pages" in index
        assert "c300-child.md" in index

    def test_omits_empty_sections(self, tmp_path):
        _setup_db(tmp_path)
        manifest_dir = tmp_path / "project"
        manifest_dir.mkdir()

        save_relationship(tmp_path, Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence:200",
            relationship_type="link",
            local_path="_sync-context/linked/c200.md",
            source_type="confluence",
        ))

        generate_context_index("confluence:100", manifest_dir, tmp_path)

        index = (manifest_dir / CONTEXT_DIR / INDEX_FILENAME).read_text()
        assert "## Linked Documents" in index
        assert "## Child Pages" not in index
        assert "## Attachments" not in index

    def test_alphabetical_ordering(self, tmp_path):
        _setup_db(tmp_path)
        manifest_dir = tmp_path / "project"
        manifest_dir.mkdir()

        for name in ["c300-zebra.md", "c200-alpha.md", "c250-middle.md"]:
            save_relationship(tmp_path, Relationship(
                parent_canonical_id="confluence:100",
                canonical_id=f"confluence:{name[:4]}",
                relationship_type="link",
                local_path=f"_sync-context/linked/{name}",
                source_type="confluence",
            ))

        generate_context_index("confluence:100", manifest_dir, tmp_path)

        index = (manifest_dir / CONTEXT_DIR / INDEX_FILENAME).read_text()
        lines = [l for l in index.splitlines() if l.startswith("- ")]
        paths = [l.split(" (")[0].lstrip("- ") for l in lines]
        assert paths == sorted(paths)

    def test_removes_index_when_no_relationships(self, tmp_path):
        _setup_db(tmp_path)
        manifest_dir = tmp_path / "project"
        (manifest_dir / CONTEXT_DIR).mkdir(parents=True)
        index_path = manifest_dir / CONTEXT_DIR / INDEX_FILENAME
        index_path.write_text("old content")

        generate_context_index("confluence:100", manifest_dir, tmp_path)

        assert not index_path.exists()

    def test_idempotent(self, tmp_path):
        _setup_db(tmp_path)
        manifest_dir = tmp_path / "project"
        manifest_dir.mkdir()

        save_relationship(tmp_path, Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence:200",
            relationship_type="link",
            local_path="_sync-context/linked/c200.md",
            source_type="confluence",
        ))

        generate_context_index("confluence:100", manifest_dir, tmp_path)
        content1 = (manifest_dir / CONTEXT_DIR / INDEX_FILENAME).read_text()

        generate_context_index("confluence:100", manifest_dir, tmp_path)
        content2 = (manifest_dir / CONTEXT_DIR / INDEX_FILENAME).read_text()

        assert content1 == content2
