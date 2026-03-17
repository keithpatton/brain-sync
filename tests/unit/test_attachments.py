from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.sync.attachments import (
    SafetyError,
    attachment_local_path,
    ensure_attachment_dir,
    migrate_legacy_context,
    remove_synced_file,
)

pytestmark = pytest.mark.unit


class TestAttachmentLocalPath:
    def test_basic(self) -> None:
        assert (
            attachment_local_path("c12345", "789", "diagram.png") == ".brain-sync/attachments/c12345/a789-diagram.png"
        )

    def test_no_title(self) -> None:
        assert attachment_local_path("c12345", "789", None) == ".brain-sync/attachments/c12345/a789"

    def test_with_query_params(self) -> None:
        assert (
            attachment_local_path("c12345", "111", "GetClipboardImage.ashx?Id=aa01b5ea&DC=GAU3&pkey=test")
            == ".brain-sync/attachments/c12345/a111-getclipboardimage.ashx"
        )


class TestAttachmentDirs:
    def test_ensure_attachment_dir(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "knowledge" / "area"
        result = ensure_attachment_dir(target_dir, "c12345")

        assert result == target_dir / ".brain-sync" / "attachments" / "c12345"
        assert result.is_dir()

    def test_remove_synced_file_respects_safe_root(self, tmp_path: Path) -> None:
        safe_root = tmp_path / "knowledge" / "area" / ".brain-sync" / "attachments" / "c12345"
        safe_root.mkdir(parents=True)
        target = safe_root / "a789-diagram.png"
        target.write_bytes(b"png-data")

        assert remove_synced_file(target, safe_root) is True
        assert not target.exists()

        outside = tmp_path / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        with pytest.raises(SafetyError):
            remove_synced_file(outside, safe_root)


class TestMigrateLegacyContext:
    def test_moves_sync_context_files_into_managed_namespace(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "knowledge" / "area"
        legacy = target_dir / "_sync-context" / "attachments"
        legacy.mkdir(parents=True)
        (legacy / "a789-diagram.png").write_bytes(b"png-data")

        count = migrate_legacy_context(target_dir, "c100", "confluence:100", tmp_path)

        assert count == 1
        assert (target_dir / ".brain-sync" / "attachments" / "c100" / "a789-diagram.png").is_file()
        assert not (target_dir / "_sync-context").exists()

    def test_moves_bare_id_attachment_dir_into_prefixed_dir(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "knowledge" / "area"
        legacy = target_dir / "_attachments" / "100"
        legacy.mkdir(parents=True)
        (legacy / "a789-diagram.png").write_bytes(b"png-data")

        count = migrate_legacy_context(target_dir, "c100", "confluence:100", tmp_path)

        assert count == 1
        assert (target_dir / ".brain-sync" / "attachments" / "c100" / "a789-diagram.png").is_file()
