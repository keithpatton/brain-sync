import pytest

from brain_sync.sources import (
    SourceType,
    UnsupportedSourceError,
    URLParseError,
    canonical_filename,
    canonical_id,
    detect_source_type,
    extract_confluence_page_id,
    extract_google_doc_id,
    slugify,
    try_extract_confluence_page_id,
)

pytestmark = pytest.mark.unit


class TestDetectSourceType:
    def test_confluence(self):
        url = "https://acme.atlassian.net/wiki/spaces/PPT/pages/123/Foo"
        assert detect_source_type(url) == SourceType.CONFLUENCE

    def test_google_docs(self):
        url = "https://docs.google.com/document/d/abc123/edit"
        assert detect_source_type(url) == SourceType.GOOGLE_DOCS

    def test_unsupported_raises(self):
        with pytest.raises(UnsupportedSourceError):
            detect_source_type("https://example.com/random")


class TestExtractConfluencePageId:
    def test_standard_url(self):
        url = "https://acme.atlassian.net/wiki/spaces/PPT/pages/4859888213/ERD+Title"
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


class TestSlugify:
    def test_basic_title(self):
        assert slugify("ERD L3 AAA - Traveler Profile Service TPS") == "erd-l3-aaa-traveler-profile-service-tps"

    def test_special_chars_removed(self):
        assert slugify("Hello, World! (v2)") == "hello-world-v2"

    def test_collapses_whitespace(self):
        assert slugify("  lots   of   spaces  ") == "lots-of-spaces"

    def test_empty_string(self):
        assert slugify("") == "untitled"

    def test_only_special_chars(self):
        assert slugify("!!!") == "untitled"

    def test_unicode(self):
        result = slugify("Café Design Doc")
        assert "caf" in result


class TestViewpageUrlParsing:
    def test_viewpage_action(self):
        url = "https://x.atlassian.net/wiki/pages/viewpage.action?pageId=456789"
        assert extract_confluence_page_id(url) == "456789"

    def test_viewpage_with_extra_params(self):
        url = "https://x.atlassian.net/wiki/pages/viewpage.action?spaceKey=S&pageId=789"
        assert extract_confluence_page_id(url) == "789"

    def test_relative_pages_url(self):
        url = "/wiki/spaces/AAA/pages/123456/Page+Title"
        assert extract_confluence_page_id(url) == "123456"

    def test_try_extract_returns_none_on_invalid(self):
        assert try_extract_confluence_page_id("https://example.com/no-id") is None

    def test_try_extract_returns_id_on_valid(self):
        url = "https://x.atlassian.net/wiki/spaces/S/pages/42/Title"
        assert try_extract_confluence_page_id(url) == "42"


class TestCanonicalId:
    def test_confluence(self):
        url = "https://x.atlassian.net/wiki/spaces/S/pages/123/Title"
        assert canonical_id(SourceType.CONFLUENCE, url) == "confluence:123"

    def test_google_docs(self):
        url = "https://docs.google.com/document/d/abc123/edit"
        assert canonical_id(SourceType.GOOGLE_DOCS, url) == "gdoc:abc123"


class TestCanonicalFilename:
    def test_confluence_with_title(self):
        assert canonical_filename(SourceType.CONFLUENCE, "123", "My Page") == "c123-my-page.md"

    def test_confluence_no_title(self):
        assert canonical_filename(SourceType.CONFLUENCE, "123", None) == "c123.md"

    def test_google_docs_no_title(self):
        assert canonical_filename(SourceType.GOOGLE_DOCS, "abc", None) == "gabc.md"

    def test_google_docs_with_title(self):
        assert canonical_filename(SourceType.GOOGLE_DOCS, "abc", "PRD v2") == "gabc-prd-v2.md"
