"""Unit tests for source adapter abstraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from brain_sync.sources import SourceType, extract_id
from brain_sync.sources.base import (
    AuthProvider,
    Comment,
    SourceAdapter,
    UpdateCheckResult,
    UpdateStatus,
)
from brain_sync.sources.confluence import ConfluenceAdapter
from brain_sync.sources.conversion import _escape_md, format_comments
from brain_sync.sources.registry import get_adapter, reset_registry
from brain_sync.sync.source_state import SourceState

pytestmark = pytest.mark.unit


class TestProtocolCompliance:
    def test_confluence_adapter_satisfies_protocol(self):
        assert isinstance(ConfluenceAdapter(), SourceAdapter)

    def test_confluence_auth_satisfies_protocol(self):
        adapter = ConfluenceAdapter()
        assert isinstance(adapter.auth_provider, AuthProvider)


class TestCapabilities:
    def test_confluence_capabilities(self):
        caps = ConfluenceAdapter().capabilities
        assert caps.supports_version_check is True
        assert caps.supports_children is True
        assert caps.supports_attachments is True
        assert caps.supports_comments is True


class TestConfluenceFetch:
    async def test_fetch_resolves_user_mentions_status_and_emoticons(self):
        adapter = ConfluenceAdapter()
        source_state = SourceState(
            canonical_id="confluence:12345",
            source_url="https://acme.atlassian.net/wiki/spaces/X/pages/12345/Test",
            source_type="confluence",
            knowledge_path="area/c12345-test.md",
        )
        html = (
            '<p><ac:link><ri:user ri:account-id="user-1" /></ac:link></p>'
            '<p><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">APPROVER</ac:parameter>'
            '<ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro></p>'
            '<p><ac:emoticon ac:name="cross" ac:emoji-fallback=":cross_mark:" /></p>'
        )

        with (
            patch(
                "brain_sync.sources.confluence.fetch_page_body",
                AsyncMock(return_value=(html, "Title", 7, "2026-03-01T00:00:00Z")),
            ),
            patch("brain_sync.sources.confluence.fetch_structured_comments", AsyncMock(return_value=[])),
            patch(
                "brain_sync.sources.confluence.fetch_users_by_account_ids",
                AsyncMock(return_value={"user-1": "Alice"}),
            ),
        ):
            result = await adapter.fetch(source_state, object(), AsyncMock())

        assert "Alice" in result.body_markdown
        assert "APPROVER" in result.body_markdown
        assert "APPROVERYellow" not in result.body_markdown
        assert "No" in result.body_markdown


class TestRegistry:
    def setup_method(self):
        reset_registry()

    def teardown_method(self):
        reset_registry()

    def test_get_adapter_confluence(self):
        adapter = get_adapter(SourceType.CONFLUENCE)
        assert isinstance(adapter, ConfluenceAdapter)

    def test_get_adapter_caches(self):
        a1 = get_adapter(SourceType.CONFLUENCE)
        a2 = get_adapter(SourceType.CONFLUENCE)
        assert a1 is a2

    def test_reset_registry_clears_cache(self):
        a1 = get_adapter(SourceType.CONFLUENCE)
        reset_registry()
        a2 = get_adapter(SourceType.CONFLUENCE)
        assert a1 is not a2

    def test_get_adapter_unknown_raises(self):
        with pytest.raises(ValueError, match="No adapter"):
            get_adapter("nonexistent")  # pyright: ignore[reportArgumentType]


class TestExtractId:
    def test_confluence(self):
        url = "https://acme.atlassian.net/wiki/spaces/X/pages/12345/Test"
        assert extract_id(SourceType.CONFLUENCE, url) == "12345"

    def test_google_docs(self):
        url = "https://docs.google.com/document/d/abc123-XY/edit"
        assert extract_id(SourceType.GOOGLE_DOCS, url) == "abc123-XY"


class TestFormatComments:
    def test_basic_comments(self):
        comments = [
            Comment(author="Alice", created="2026-01-01T00:00:00Z", content="<p>Great work!</p>"),
            Comment(author="Bob", created="2026-01-02T00:00:00Z", content="<p>Needs review.</p>"),
        ]
        result = format_comments(comments)
        assert "### Comment Thread `unknown`" in result
        assert "Author: Alice" in result
        assert "Created: 2026-01-01T00:00:00Z" in result
        assert "Body:" in result
        assert "Great work!" in result
        assert "Author: Bob" in result
        assert "Needs review." in result

    def test_empty_list(self):
        assert format_comments([]) == ""

    def test_resolved_comment(self):
        comments = [
            Comment(author="Alice", created="2026-01-01", content="<p>Done</p>", resolved=True),
        ]
        result = format_comments(comments)
        assert "[resolved]" in result

    def test_threaded_replies(self):
        comments = [
            Comment(
                author="Alice",
                created="2026-01-01",
                content="<p>Question?</p>",
                replies=[
                    Comment(author="Bob", created="2026-01-02", content="<p>Answer.</p>"),
                ],
            ),
        ]
        result = format_comments(comments)
        assert "Replies:" in result
        assert "1. Reply `unknown`" in result
        assert "Author: Bob" in result
        assert "Created: 2026-01-02" in result
        assert "Answer." in result

    def test_inline_comment_metadata(self):
        comments = [
            Comment(
                author="Alice",
                created="2026-01-01",
                content="<p>Check this section.</p>",
                id="123",
                comment_type="inline",
                resolution_status="reopened",
                anchor_text="Important requirement",
                anchor_ref="marker-1",
            ),
        ]
        result = format_comments(comments)
        assert "### Comment Thread `123` [inline] [reopened]" in result
        assert 'Anchor Text: "Important requirement"' in result
        assert "Anchor Ref:" not in result

    def test_replies_do_not_repeat_parent_resolution_metadata(self):
        comments = [
            Comment(
                author="Alice",
                created="2026-01-01",
                content="<p>Question?</p>",
                id="root-1",
                comment_type="footer",
                resolution_status="resolved",
                replies=[
                    Comment(
                        author="Bob",
                        created="2026-01-02",
                        content="<p>Answer.</p>",
                        id="reply-1",
                        comment_type="footer",
                        resolution_status="open",
                    ),
                ],
            ),
        ]
        result = format_comments(comments)
        assert "### Comment Thread `root-1` [footer] [resolved]" in result
        assert "1. Reply `reply-1`" in result
        assert "[open]" not in result


class TestEscapeMd:
    def test_escapes_heading(self):
        assert _escape_md("# Title") == "\\# Title"

    def test_escapes_star(self):
        assert _escape_md("* item") == "\\* item"

    def test_escapes_dash(self):
        assert _escape_md("- item") == "\\- item"

    def test_escapes_plus(self):
        assert _escape_md("+ item") == "\\+ item"

    def test_preserves_indentation(self):
        assert _escape_md("  # Indented") == "  \\# Indented"

    def test_no_escape_normal_text(self):
        assert _escape_md("Hello world") == "Hello world"

    def test_no_escape_blockquote(self):
        assert _escape_md("> quote") == "> quote"


class TestUpdateCheckResultStates:
    def test_unchanged_status(self):
        result = UpdateCheckResult(status=UpdateStatus.UNCHANGED, fingerprint="5")
        assert result.status == UpdateStatus.UNCHANGED
        assert result.fingerprint == "5"

    def test_changed_status(self):
        result = UpdateCheckResult(status=UpdateStatus.CHANGED, fingerprint="6")
        assert result.status == UpdateStatus.CHANGED

    def test_unknown_status(self):
        result = UpdateCheckResult(status=UpdateStatus.UNKNOWN)
        assert result.fingerprint is None
        assert result.adapter_state is None
