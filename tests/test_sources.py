import pytest

from brain_sync.sources import (
    SourceType,
    URLParseError,
    UnsupportedSourceError,
    detect_source_type,
    extract_confluence_page_id,
    extract_google_doc_id,
)


class TestDetectSourceType:
    def test_confluence(self):
        url = "https://serko.atlassian.net/wiki/spaces/PPT/pages/123/Foo"
        assert detect_source_type(url) == SourceType.CONFLUENCE

    def test_google_docs(self):
        url = "https://docs.google.com/document/d/abc123/edit"
        assert detect_source_type(url) == SourceType.GOOGLE_DOCS

    def test_unsupported_raises(self):
        with pytest.raises(UnsupportedSourceError):
            detect_source_type("https://example.com/random")


class TestExtractConfluencePageId:
    def test_standard_url(self):
        url = "https://serko.atlassian.net/wiki/spaces/PPT/pages/4859888213/ERD+Title"
        assert extract_confluence_page_id(url) == "4859888213"

    def test_url_with_query_params(self):
        url = "https://x.atlassian.net/wiki/spaces/S/pages/999?foo=bar"
        assert extract_confluence_page_id(url) == "999"

    def test_invalid_url_raises(self):
        with pytest.raises(URLParseError):
            extract_confluence_page_id("https://atlassian.net/wiki/spaces/S/overview")


class TestExtractGoogleDocId:
    def test_standard_url(self):
        url = "https://docs.google.com/document/d/1BCNnFdQVvFfgROHQvzTpzsm8a9tXKR9OEy-KoEYYJZ8/edit"
        assert extract_google_doc_id(url) == "1BCNnFdQVvFfgROHQvzTpzsm8a9tXKR9OEy-KoEYYJZ8"

    def test_url_with_tab(self):
        url = "https://docs.google.com/document/d/abc123/edit?tab=t.0#heading=h.xyz"
        assert extract_google_doc_id(url) == "abc123"

    def test_invalid_url_raises(self):
        with pytest.raises(URLParseError):
            extract_google_doc_id("https://docs.google.com/spreadsheets/d/abc")
