"""Unit tests for Google Docs source adapter and OAuth2 authentication."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

pytest.importorskip("google.auth", reason="google-auth not installed (install brain-sync[google])")

from brain_sync.sources.base import (
    AuthProvider,
    SourceAdapter,
    SourceFetchResult,
    UpdateStatus,
)
from brain_sync.sources.googledocs import GoogleDocsAdapter
from brain_sync.sources.googledocs.auth import (
    GoogleDocsAuthProvider,
    GoogleOAuthCredentials,
    _load_cached_token,
    _save_token,
    run_oauth_flow,
)
from brain_sync.sources.googledocs.rest import (
    DriveDocMetadata,
    FetchError,
    TabData,
    TabsDocument,
    _flatten_tabs,
    compute_semantic_fingerprint,
    extract_canonical_text,
    extract_title_from_html,
    fetch_all_tabs,
    fetch_drive_metadata,
    generate_tabs_markdown,
)

pytestmark = pytest.mark.unit


class TestProtocolCompliance:
    def test_adapter_satisfies_protocol(self):
        assert isinstance(GoogleDocsAdapter(), SourceAdapter)

    def test_auth_satisfies_protocol(self):
        adapter = GoogleDocsAdapter()
        assert isinstance(adapter.auth_provider, AuthProvider)


class TestCapabilities:
    def test_all_capabilities_correct(self):
        caps = GoogleDocsAdapter().capabilities
        assert caps.supports_version_check is True
        assert caps.supports_children is False
        assert caps.supports_attachments is True
        assert caps.supports_comments is False


class TestCheckForUpdate:
    @pytest.fixture
    def adapter(self):
        return GoogleDocsAdapter()

    @pytest.fixture
    def source_state(self):
        from brain_sync.application.source_state import SourceState

        return SourceState(
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
        )

    async def test_returns_unchanged_when_drive_version_matches(self, adapter, source_state):
        source_state.remote_fingerprint = "42"
        with patch(
            "brain_sync.sources.googledocs.fetch_drive_metadata",
            new_callable=AsyncMock,
            return_value=DriveDocMetadata(title="My Doc", version="42"),
        ):
            result = await adapter.check_for_update(source_state, Mock(), AsyncMock())
        assert result.status == UpdateStatus.UNCHANGED
        assert result.fingerprint == "42"
        assert result.title == "My Doc"

    async def test_returns_changed_when_drive_version_differs(self, adapter, source_state):
        source_state.remote_fingerprint = "41"
        with patch(
            "brain_sync.sources.googledocs.fetch_drive_metadata",
            new_callable=AsyncMock,
            return_value=DriveDocMetadata(title="My Doc", version="42"),
        ):
            result = await adapter.check_for_update(source_state, Mock(), AsyncMock())
        assert result.status == UpdateStatus.CHANGED
        assert result.fingerprint == "42"

    async def test_returns_changed_when_no_prior_fingerprint(self, adapter, source_state):
        with patch(
            "brain_sync.sources.googledocs.fetch_drive_metadata",
            new_callable=AsyncMock,
            return_value=DriveDocMetadata(title="My Doc", version="42"),
        ):
            result = await adapter.check_for_update(source_state, Mock(), AsyncMock())
        assert result.status == UpdateStatus.CHANGED

    async def test_returns_unknown_when_metadata_unavailable(self, adapter, source_state):
        with patch("brain_sync.sources.googledocs.fetch_drive_metadata", new_callable=AsyncMock, return_value=None):
            result = await adapter.check_for_update(source_state, Mock(), AsyncMock())
        assert result.status == UpdateStatus.UNKNOWN

    async def test_adapter_state_contains_drive_version(self, adapter, source_state):
        with patch(
            "brain_sync.sources.googledocs.fetch_drive_metadata",
            new_callable=AsyncMock,
            return_value=DriveDocMetadata(title="My Doc", version="42"),
        ):
            result = await adapter.check_for_update(source_state, Mock(), AsyncMock())
        assert result.adapter_state is not None
        assert result.adapter_state["version"] == "42"
        assert result.adapter_state["title"] == "My Doc"


class TestFetch:
    @pytest.fixture
    def adapter(self):
        return GoogleDocsAdapter()

    @pytest.fixture
    def source_state(self):
        from brain_sync.application.source_state import SourceState

        return SourceState(
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
        )

    def _make_tabs_doc(self, title: str | None = "My Doc") -> TabsDocument:
        return TabsDocument(
            title=title,
            tabs=[
                TabData(
                    tab_id="t1",
                    title="Main",
                    number="1",
                    body_content=[
                        {"paragraph": {"elements": [{"textRun": {"content": "Hello"}}]}},
                        {"paragraph": {"elements": [{"textRun": {"content": "World"}}]}},
                    ],
                )
            ],
        )

    async def test_fetch_returns_correct_result(self, adapter, source_state):
        tabs_doc = self._make_tabs_doc()
        with (
            patch("brain_sync.sources.googledocs.fetch_all_tabs", new_callable=AsyncMock, return_value=tabs_doc),
            patch(
                "brain_sync.sources.googledocs.fetch_drive_metadata",
                new_callable=AsyncMock,
                return_value=DriveDocMetadata(title="Drive Title", version="42"),
            ),
        ):
            result = await adapter.fetch(source_state, Mock(), AsyncMock())

        assert isinstance(result, SourceFetchResult)
        assert "Hello" in result.body_markdown
        assert "World" in result.body_markdown
        assert result.title == "My Doc"
        assert result.comments == []
        assert result.remote_fingerprint == "42"
        assert result.source_html is None

    async def test_fetch_returns_drive_version_from_adapter_state(self, adapter, source_state):
        tabs_doc = self._make_tabs_doc()
        with patch("brain_sync.sources.googledocs.fetch_all_tabs", new_callable=AsyncMock, return_value=tabs_doc):
            result = await adapter.fetch(
                source_state, Mock(), AsyncMock(), prior_adapter_state={"version": "42", "title": "Drive Title"}
            )

        assert result.remote_fingerprint == "42"

    async def test_fetch_uses_title_from_adapter_state(self, adapter, source_state):
        # tabs_doc.title is None — title should come from prior_adapter_state
        tabs_doc = self._make_tabs_doc(title=None)
        with patch("brain_sync.sources.googledocs.fetch_all_tabs", new_callable=AsyncMock, return_value=tabs_doc):
            result = await adapter.fetch(
                source_state,
                Mock(),
                AsyncMock(),
                prior_adapter_state={"version": "42", "title": "Adapter Title"},
            )

        assert result.title == "Adapter Title"
        assert result.remote_fingerprint == "42"

    async def test_fetch_falls_back_to_api_title_when_no_adapter_state(self, adapter, source_state):
        tabs_doc = self._make_tabs_doc(title=None)
        with (
            patch("brain_sync.sources.googledocs.fetch_all_tabs", new_callable=AsyncMock, return_value=tabs_doc),
            patch("brain_sync.sources.googledocs.fetch_drive_metadata", new_callable=AsyncMock, return_value=None),
            patch("brain_sync.sources.googledocs.fetch_doc_title", new_callable=AsyncMock, return_value="API Title"),
        ):
            result = await adapter.fetch(source_state, Mock(), AsyncMock())

        assert result.title == "API Title"
        assert result.remote_fingerprint.startswith("gdocs:v3:")

    async def test_fetch_uses_drive_title_before_docs_title_fallback(self, adapter, source_state):
        tabs_doc = self._make_tabs_doc(title=None)
        with (
            patch("brain_sync.sources.googledocs.fetch_all_tabs", new_callable=AsyncMock, return_value=tabs_doc),
            patch(
                "brain_sync.sources.googledocs.fetch_drive_metadata",
                new_callable=AsyncMock,
                return_value=DriveDocMetadata(title="Drive Title", version="42"),
            ),
            patch("brain_sync.sources.googledocs.fetch_doc_title", new_callable=AsyncMock) as mock_title,
        ):
            result = await adapter.fetch(source_state, Mock(), AsyncMock())

        assert result.title == "Drive Title"
        assert result.remote_fingerprint == "42"
        mock_title.assert_not_awaited()

    async def test_fetch_title_none_when_both_sources_fail(self, adapter, source_state):
        tabs_doc = self._make_tabs_doc(title=None)
        with (
            patch("brain_sync.sources.googledocs.fetch_all_tabs", new_callable=AsyncMock, return_value=tabs_doc),
            patch("brain_sync.sources.googledocs.fetch_drive_metadata", new_callable=AsyncMock, return_value=None),
            patch("brain_sync.sources.googledocs.fetch_doc_title", new_callable=AsyncMock, return_value=None),
        ):
            result = await adapter.fetch(source_state, Mock(), AsyncMock())

        assert result.title is None

    async def test_fetch_propagates_error(self, adapter, source_state):
        with (
            patch("brain_sync.sources.googledocs.fetch_all_tabs", new_callable=AsyncMock, return_value=None),
            pytest.raises(FetchError),
        ):
            await adapter.fetch(source_state, Mock(), AsyncMock())


class TestExtractCanonicalText:
    def _make_tabs_doc(self, content: list[dict]) -> TabsDocument:
        return TabsDocument(title=None, tabs=[TabData(tab_id="t1", title="Tab 1", number="1", body_content=content)])

    def _para(self, text: str, style: str | None = None, bullet: bool = False) -> dict:
        para: dict = {
            "paragraph": {
                "elements": [{"textRun": {"content": text}}],
            }
        }
        if style:
            para["paragraph"]["paragraphStyle"] = {"namedStyleType": style}
        if bullet:
            para["paragraph"]["bullet"] = {}
        return para

    def test_empty_body(self):
        doc = self._make_tabs_doc([])
        result = extract_canonical_text(doc)
        assert result == "TAB:1:Tab 1"

    def test_plain_paragraph(self):
        doc = self._make_tabs_doc([self._para("Hello world")])
        result = extract_canonical_text(doc)
        assert "Hello world" in result

    def test_heading_prefixed(self):
        doc = self._make_tabs_doc([self._para("My Heading", style="HEADING_1")])
        result = extract_canonical_text(doc)
        assert "H:My Heading" in result

    def test_list_item_prefixed(self):
        doc = self._make_tabs_doc([self._para("List item", bullet=True)])
        result = extract_canonical_text(doc)
        assert "LI:List item" in result

    def test_empty_paragraphs_skipped(self):
        doc = self._make_tabs_doc([self._para("   "), self._para("Real content")])
        result = extract_canonical_text(doc)
        assert "Real content" in result

    def test_table_row_prefixed(self):
        doc = self._make_tabs_doc(
            [
                {
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {"content": [self._para("Cell A")]},
                                    {"content": [self._para("Cell B")]},
                                ]
                            }
                        ]
                    }
                }
            ]
        )
        result = extract_canonical_text(doc)
        assert "T:Cell A|Cell B" in result

    def test_whitespace_normalised(self):
        doc = self._make_tabs_doc([self._para("Hello\n"), self._para("World\n")])
        result = extract_canonical_text(doc)
        assert "\n" not in result
        assert "Hello" in result
        assert "World" in result

    def test_multiple_elements_in_paragraph(self):
        para = {
            "paragraph": {
                "elements": [
                    {"textRun": {"content": "Hello "}},
                    {"textRun": {"content": "world"}},
                ]
            }
        }
        doc = self._make_tabs_doc([para])
        result = extract_canonical_text(doc)
        assert "Hello world" in result

    def test_multi_tab_canonical_text_includes_tab_prefix(self):
        tabs_doc = TabsDocument(
            title=None,
            tabs=[
                TabData(tab_id="t1", title="Overview", number="1", body_content=[self._para("Intro text")]),
                TabData(tab_id="t2", title="Details", number="2", body_content=[self._para("Detail text")]),
            ],
        )
        result = extract_canonical_text(tabs_doc)
        assert "TAB:1:Overview" in result
        assert "TAB:2:Details" in result
        assert "Intro text" in result
        assert "Detail text" in result


class TestComputeSemanticFingerprint:
    def test_starts_with_version_prefix(self):
        fp = compute_semantic_fingerprint("hello")
        assert fp.startswith("gdocs:v3:")

    def test_same_text_same_fingerprint(self):
        assert compute_semantic_fingerprint("abc") == compute_semantic_fingerprint("abc")

    def test_different_text_different_fingerprint(self):
        assert compute_semantic_fingerprint("abc") != compute_semantic_fingerprint("xyz")

    def test_fingerprint_is_deterministic(self):
        import hashlib

        text = "test content"
        expected = "gdocs:v3:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert compute_semantic_fingerprint(text) == expected


class TestFetchAllTabs:
    async def test_success_returns_tabs_document(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        data = {
            "title": "My Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t1", "title": "Introduction"},
                    "documentTab": {
                        "body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": "Hello world"}}]}}]}
                    },
                }
            ],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_all_tabs("abc123", auth, client)
        assert result is not None
        assert result.title == "My Doc"
        assert len(result.tabs) == 1
        assert result.tabs[0].tab_id == "t1"
        assert result.tabs[0].title == "Introduction"
        assert len(result.tabs[0].body_content) == 1
        call_args = client.get.call_args
        assert "docs.googleapis.com/v1/documents/abc123" in call_args.args[0]

    async def test_field_mask_and_include_tabs_content(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        data = {
            "title": "Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t1", "title": "Tab"},
                    "documentTab": {"body": {"content": []}},
                }
            ],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = mock_response

        await fetch_all_tabs("abc123", auth, client)
        params = client.get.call_args.kwargs.get("params", {})
        assert "tabs" in params.get("fields", "")
        assert params.get("includeTabsContent") == "true"

    async def test_404_returns_none(self):
        import httpx

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response
        )
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_all_tabs("missing123", auth, client)
        assert result is None

    async def test_network_error_returns_none(self):
        import httpx

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        client = AsyncMock()
        client.get.side_effect = httpx.ConnectError("connection refused")

        result = await fetch_all_tabs("abc123", auth, client)
        assert result is None

    async def test_multi_tab_document_all_tabs_present(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        data = {
            "title": "Multi-tab Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t1", "title": "Tab One"},
                    "documentTab": {"body": {"content": []}},
                },
                {
                    "tabProperties": {"tabId": "t2", "title": "Tab Two"},
                    "documentTab": {"body": {"content": []}},
                },
            ],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_all_tabs("abc123", auth, client)
        assert result is not None
        assert len(result.tabs) == 2
        assert result.tabs[0].title == "Tab One"
        assert result.tabs[1].title == "Tab Two"

    async def test_empty_title_resolved_to_untitled(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        data = {
            "title": "Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t99", "title": ""},
                    "documentTab": {"body": {"content": []}},
                }
            ],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_all_tabs("abc123", auth, client)
        assert result is not None
        assert result.tabs[0].title == "Untitled Tab (t99)"

    async def test_non_document_tab_skipped(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        data = {
            "title": "Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t1", "title": "Real Tab"},
                    "documentTab": {"body": {"content": []}},
                },
                {
                    "tabProperties": {"tabId": "t2", "title": "Other Tab"},
                    # no "documentTab" key — non-document tab type
                },
            ],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_all_tabs("abc123", auth, client)
        assert result is not None
        assert len(result.tabs) == 1
        assert result.tabs[0].tab_id == "t1"

    async def test_missing_tabs_key_returns_none(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        data = {"title": "Doc"}  # no tabs key
        mock_response = MagicMock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_all_tabs("abc123", auth, client)
        assert result is None

    async def test_all_non_document_tabs_returns_none(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        data = {
            "title": "Doc",
            "tabs": [
                {"tabProperties": {"tabId": "t1", "title": "Other"}},  # no documentTab
            ],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_all_tabs("abc123", auth, client)
        assert result is None


class TestExtractTitleFromHtml:
    def test_with_title(self):
        html = "<html><head><title>My Document</title></head><body></body></html>"
        assert extract_title_from_html(html) == "My Document"

    def test_without_title(self):
        html = "<html><head></head><body></body></html>"
        assert extract_title_from_html(html) is None

    def test_empty_title(self):
        html = "<html><head><title></title></head><body></body></html>"
        assert extract_title_from_html(html) is None

    def test_whitespace_title(self):
        html = "<html><head><title>  </title></head><body></body></html>"
        assert extract_title_from_html(html) is None


class TestFlattenTabs:
    def _doc_tab(self, tab_id: str, title: str, children: list[dict] | None = None) -> dict:
        tab: dict = {
            "tabProperties": {"tabId": tab_id, "title": title},
            "documentTab": {"body": {"content": []}},
        }
        if children:
            tab["childTabs"] = children
        return tab

    def _non_doc_tab(self, tab_id: str, title: str) -> dict:
        return {"tabProperties": {"tabId": tab_id, "title": title}}

    def test_flat_tabs(self):
        tabs = [self._doc_tab("t1", "A"), self._doc_tab("t2", "B")]
        result = _flatten_tabs(tabs)
        assert [(num, t["tabProperties"]["tabId"]) for num, t in result] == [("1", "t1"), ("2", "t2")]

    def test_child_tabs(self):
        tabs = [
            self._doc_tab(
                "t1",
                "Parent",
                children=[
                    self._doc_tab("t1a", "Child A"),
                    self._doc_tab("t1b", "Child B"),
                ],
            ),
        ]
        result = _flatten_tabs(tabs)
        nums = [num for num, _ in result]
        assert nums == ["1", "1.1", "1.2"]

    def test_deeply_nested(self):
        tabs = [
            self._doc_tab(
                "t1",
                "L1",
                children=[
                    self._doc_tab(
                        "t1a",
                        "L2",
                        children=[
                            self._doc_tab("t1a1", "L3"),
                        ],
                    ),
                ],
            ),
        ]
        result = _flatten_tabs(tabs)
        nums = [num for num, _ in result]
        assert nums == ["1", "1.1", "1.1.1"]

    def test_mixed_siblings_and_children(self):
        tabs = [
            self._doc_tab("t1", "A"),
            self._doc_tab(
                "t2",
                "B",
                children=[
                    self._doc_tab("t2a", "B1"),
                ],
            ),
            self._doc_tab("t3", "C"),
        ]
        result = _flatten_tabs(tabs)
        nums = [num for num, _ in result]
        assert nums == ["1", "2", "2.1", "3"]


class TestFetchAllTabsChildTabs:
    """Tests for child tab recursion in fetch_all_tabs."""

    async def test_child_tabs_flattened(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        data = {
            "title": "Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t1", "title": "Parent"},
                    "documentTab": {"body": {"content": []}},
                    "childTabs": [
                        {
                            "tabProperties": {"tabId": "t1a", "title": "Child A"},
                            "documentTab": {"body": {"content": []}},
                        },
                        {
                            "tabProperties": {"tabId": "t1b", "title": "Child B"},
                            "documentTab": {"body": {"content": []}},
                        },
                    ],
                },
            ],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_all_tabs("abc123", auth, client)
        assert result is not None
        assert len(result.tabs) == 3
        assert result.tabs[0].number == "1"
        assert result.tabs[0].title == "Parent"
        assert result.tabs[1].number == "1.1"
        assert result.tabs[1].title == "Child A"
        assert result.tabs[2].number == "1.2"
        assert result.tabs[2].title == "Child B"

    async def test_child_tab_non_document_skipped(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        data = {
            "title": "Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t1", "title": "Parent"},
                    "documentTab": {"body": {"content": []}},
                    "childTabs": [
                        {
                            "tabProperties": {"tabId": "t1a", "title": "Non-doc child"},
                            # no documentTab — should be skipped
                        },
                    ],
                },
            ],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_all_tabs("abc123", auth, client)
        assert result is not None
        assert len(result.tabs) == 1
        assert result.tabs[0].tab_id == "t1"


class TestGenerateTabsMarkdown:
    def _tab(self, tab_id: str, title: str, number: str, content: list[dict] | None = None) -> TabData:
        return TabData(tab_id=tab_id, title=title, number=number, body_content=content or [])

    def test_single_tab_uses_h2(self):
        doc = TabsDocument(title="Doc", tabs=[self._tab("t1", "Overview", "1")])
        md = generate_tabs_markdown(doc)
        assert md.startswith("## Overview")
        assert "# Tab" not in md

    def test_multi_tab_uses_h1_with_number(self):
        doc = TabsDocument(
            title="Doc",
            tabs=[
                self._tab("t1", "Overview", "1"),
                self._tab("t2", "Details", "2"),
            ],
        )
        md = generate_tabs_markdown(doc)
        assert "# Tab 1 \u2014 Overview" in md
        assert "# Tab 2 \u2014 Details" in md

    def test_child_tab_numbering(self):
        doc = TabsDocument(
            title="Doc",
            tabs=[
                self._tab("t1", "Parent", "1"),
                self._tab("t1a", "Child", "1.1"),
            ],
        )
        md = generate_tabs_markdown(doc)
        assert "# Tab 1 \u2014 Parent" in md
        assert "# Tab 1.1 \u2014 Child" in md

    def test_separator_between_tabs(self):
        doc = TabsDocument(
            title="Doc",
            tabs=[
                self._tab("t1", "A", "1"),
                self._tab("t2", "B", "2"),
            ],
        )
        md = generate_tabs_markdown(doc)
        assert "\n\n---\n\n" in md

    def test_tab_content_rendered(self):
        content = [{"paragraph": {"elements": [{"textRun": {"content": "Hello world"}}]}}]
        doc = TabsDocument(title="Doc", tabs=[self._tab("t1", "Main", "1", content)])
        md = generate_tabs_markdown(doc)
        assert "Hello world" in md


# --- OAuth2 auth tests ---


class TestLoadCachedToken:
    def test_valid_token_in_config_returns_credentials(self, monkeypatch):
        token_data = {
            "token": "access-token-123",
            "refresh_token": "refresh-token-456",
            "client_id": "client-id",
            "client_secret": "client-secret",
        }
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": token_data}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        result = _load_cached_token()
        assert result is not None
        assert result.token == "access-token-123"

    def test_missing_config_returns_none(self, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        assert _load_cached_token() is None

    def test_corrupt_token_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": {"bad": "data"}}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        # google-auth may accept partial data — at minimum it should not crash
        result = _load_cached_token()
        # Result may be None or a Credentials with no token; either is acceptable
        assert result is None or result.token is None

    def test_migrates_legacy_token_file(self, tmp_path, monkeypatch):
        legacy_file = tmp_path / "google_token.json"
        token_data = {
            "token": "legacy-tok",
            "refresh_token": "legacy-ref",
            "client_id": "cid",
            "client_secret": "csec",
        }
        legacy_file.write_text(json.dumps(token_data), encoding="utf-8")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE", legacy_file)

        saved_configs: list[dict] = []
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"googledocs": {"client_secrets_file": "/old/path"}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.save_config",
            lambda c: saved_configs.append(c),
        )

        result = _load_cached_token()
        assert result is not None
        assert result.token == "legacy-tok"
        # Legacy file should be deleted
        assert not legacy_file.exists()
        # Config should have google.token and no googledocs key
        assert len(saved_configs) == 1
        assert saved_configs[0]["google"]["token"] == token_data
        assert "googledocs" not in saved_configs[0]


class TestSaveToken:
    def test_saves_token_to_config(self, monkeypatch):
        saved_configs: list[dict] = []
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.save_config",
            lambda c: saved_configs.append(c),
        )

        creds = MagicMock()
        creds.to_json.return_value = '{"token": "abc", "refresh_token": "ref"}'

        _save_token(creds)

        assert len(saved_configs) == 1
        assert saved_configs[0]["google"]["token"] == {"token": "abc", "refresh_token": "ref"}

    def test_preserves_existing_config(self, monkeypatch):
        saved_configs: list[dict] = []
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"brains": ["/some/path"], "confluence": {"domain": "x"}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.save_config",
            lambda c: saved_configs.append(c),
        )

        creds = MagicMock()
        creds.to_json.return_value = '{"token": "new"}'

        _save_token(creds)

        assert saved_configs[0]["brains"] == ["/some/path"]
        assert saved_configs[0]["confluence"] == {"domain": "x"}
        assert saved_configs[0]["google"]["token"] == {"token": "new"}


class TestValidateConfig:
    def test_returns_true_with_cached_token(self, monkeypatch):
        """validate_config returns True when cached token exists — no OAuth triggered."""
        token_data = {
            "token": "tok",
            "refresh_token": "ref",
            "client_id": "cid",
            "client_secret": "csec",
        }
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": token_data}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        provider = GoogleDocsAuthProvider()
        assert provider.validate_config() is True

    def test_returns_false_when_no_token(self, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        provider = GoogleDocsAuthProvider()
        assert provider.validate_config() is False


class TestLoadAuth:
    def test_cached_token_returns_oauth_credentials(self, monkeypatch):
        token_data = {
            "token": "tok",
            "refresh_token": "ref",
            "client_id": "cid",
            "client_secret": "csec",
        }
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": token_data}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        provider = GoogleDocsAuthProvider()
        auth = provider.load_auth()
        assert isinstance(auth, GoogleOAuthCredentials)

    def test_no_token_returns_none(self, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        provider = GoogleDocsAuthProvider()
        assert provider.load_auth() is None


class TestGoogleOAuthCredentials:
    async def test_fresh_token_returns_directly(self):
        creds = MagicMock()
        creds.expired = False
        creds.token = "fresh-token"

        oauth = GoogleOAuthCredentials(creds)
        token = await oauth.get_token()
        assert token == "fresh-token"

    async def test_expired_token_triggers_refresh(self):
        creds = MagicMock()
        creds.expired = True
        creds.refresh_token = "ref-tok"
        creds.token = "refreshed-token"
        creds.to_json.return_value = '{"token": "refreshed-token"}'

        with patch("brain_sync.sources.googledocs.auth._save_token") as mock_save:
            oauth = GoogleOAuthCredentials(creds)
            token = await oauth.get_token()

        assert token == "refreshed-token"
        creds.refresh.assert_called_once()
        mock_save.assert_called_once_with(creds)

    async def test_refresh_error_raises_fetch_error(self):
        from google.auth.exceptions import RefreshError

        creds = MagicMock()
        creds.expired = True
        creds.refresh_token = "ref-tok"
        creds.refresh.side_effect = RefreshError("bad")

        oauth = GoogleOAuthCredentials(creds)
        with pytest.raises(FetchError, match=r"OAuth refresh failed.*--reauth"):
            await oauth.get_token()

    async def test_none_token_raises_fetch_error(self):
        creds = MagicMock()
        creds.expired = False
        creds.token = None

        oauth = GoogleOAuthCredentials(creds)
        with pytest.raises(FetchError, match=r"token missing.*--reauth"):
            await oauth.get_token()


class TestRunOAuthFlow:
    def test_runs_flow_and_saves_token(self, monkeypatch):
        saved_configs: list[dict] = []
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.save_config",
            lambda c: saved_configs.append(c),
        )

        from google.oauth2.credentials import Credentials

        fake_creds = MagicMock(spec=Credentials)
        fake_creds.to_json.return_value = '{"token": "new"}'
        fake_flow = MagicMock()
        fake_flow.run_local_server.return_value = fake_creds

        with patch(
            "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
            return_value=fake_flow,
        ) as mock_from:
            result = run_oauth_flow()

        mock_from.assert_called_once()
        fake_flow.run_local_server.assert_called_once_with(port=0)
        assert result is fake_creds
        # Token should have been saved to config
        assert len(saved_configs) == 1
        assert saved_configs[0]["google"]["token"] == {"token": "new"}


class TestConfigureGoogle:
    def test_runs_oauth_when_not_authenticated(self, monkeypatch):
        from brain_sync.application.config import configure_google

        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        with patch("brain_sync.sources.googledocs.auth.run_oauth_flow") as mock_flow:
            result = configure_google()

        assert result is True
        mock_flow.assert_called_once()

    def test_skips_oauth_when_already_authenticated(self, monkeypatch):
        from brain_sync.application.config import configure_google

        token_data = {"token": "tok", "refresh_token": "ref", "client_id": "cid", "client_secret": "csec"}
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": token_data}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        with patch("brain_sync.sources.googledocs.auth.run_oauth_flow") as mock_flow:
            result = configure_google()

        assert result is True
        mock_flow.assert_not_called()

    def test_reauth_forces_oauth_even_when_authenticated(self, monkeypatch):
        from brain_sync.application.config import configure_google

        token_data = {"token": "tok", "refresh_token": "ref", "client_id": "cid", "client_secret": "csec"}
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": token_data}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        with patch("brain_sync.sources.googledocs.auth.run_oauth_flow") as mock_flow:
            result = configure_google(reauth=True)

        assert result is True
        mock_flow.assert_called_once()

    def test_configure_raises(self):
        provider = GoogleDocsAuthProvider()
        with pytest.raises(NotImplementedError):
            provider.configure()


class TestFetchDocTitle:
    async def test_success_returns_title(self):
        from brain_sync.sources.googledocs.rest import fetch_doc_title

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"title": "My Doc"}
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_doc_title("abc123", auth, client)
        assert result == "My Doc"
        client.get.assert_called_once()
        call_kwargs = client.get.call_args
        assert "docs.googleapis.com/v1/documents/abc123" in call_kwargs.args[0]

    async def test_404_returns_none(self):
        import httpx

        from brain_sync.sources.googledocs.rest import fetch_doc_title

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response
        )

        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_doc_title("missing123", auth, client)
        assert result is None

    async def test_network_error_returns_none(self):
        import httpx

        from brain_sync.sources.googledocs.rest import fetch_doc_title

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"

        client = AsyncMock()
        client.get.side_effect = httpx.ConnectError("connection refused")

        result = await fetch_doc_title("abc123", auth, client)
        assert result is None


class TestFetchDriveMetadata:
    async def test_success_returns_title_and_version(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"name": "My Doc", "version": "42"}
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_drive_metadata("abc123", auth, client)
        assert result == DriveDocMetadata(title="My Doc", version="42")
        call_kwargs = client.get.call_args
        assert "www.googleapis.com/drive/v3/files/abc123" in call_kwargs.args[0]
        assert call_kwargs.kwargs["params"]["fields"] == "name,version"
        assert call_kwargs.kwargs["params"]["supportsAllDrives"] == "true"

    async def test_404_returns_none(self):
        import httpx

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response
        )
        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_drive_metadata("missing123", auth, client)
        assert result is None

    async def test_network_error_returns_none(self):
        import httpx

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        client = AsyncMock()
        client.get.side_effect = httpx.ConnectError("connection refused")

        result = await fetch_drive_metadata("abc123", auth, client)
        assert result is None
