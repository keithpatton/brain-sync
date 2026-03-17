"""Tests for the placement suggestion module.

Unit tests for keyword extraction, score accumulation, subtree filtering,
and the suggest_placement() function.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.query.area_index import AreaIndex
from brain_sync.query.placement import (
    MAX_QUERY_TERMS,
    InvalidSourceSpecifierError,
    PlacementCandidate,
    SourceKind,
    SuggestPlacementResult,
    _extract_query_terms,
    classify_source,
    extract_file_excerpt,
    extract_title_from_url,
    suggest_placement,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def brain_root(tmp_path: Path) -> Path:
    """Create a brain with several areas for placement tests."""
    root = tmp_path / "brain"

    # Area: initiatives/tps
    (root / "knowledge" / "initiatives" / "tps").mkdir(parents=True)
    (root / "knowledge" / "initiatives" / "tps" / "doc.md").write_text("TPS report docs.", encoding="utf-8")
    (root / "insights" / "initiatives" / "tps").mkdir(parents=True)
    (root / "insights" / "initiatives" / "tps" / "summary.md").write_text(
        "# TPS Initiative\n\nTPS report processing and workflow automation.",
        encoding="utf-8",
    )

    # Sub-area: initiatives/tps/meetings
    (root / "knowledge" / "initiatives" / "tps" / "meetings").mkdir(parents=True)
    (root / "insights" / "initiatives" / "tps" / "meetings").mkdir(parents=True)
    (root / "insights" / "initiatives" / "tps" / "meetings" / "summary.md").write_text(
        "# TPS Meetings\n\nMeeting notes and decisions for TPS initiative.",
        encoding="utf-8",
    )

    # Area: initiatives/payments
    (root / "knowledge" / "initiatives" / "payments").mkdir(parents=True)
    (root / "insights" / "initiatives" / "payments").mkdir(parents=True)
    (root / "insights" / "initiatives" / "payments" / "summary.md").write_text(
        "# Payments\n\nPayment processing system and gateway integration.",
        encoding="utf-8",
    )

    # Sub-area: initiatives/payments/architecture
    (root / "knowledge" / "initiatives" / "payments" / "architecture").mkdir(parents=True)
    (root / "insights" / "initiatives" / "payments" / "architecture").mkdir(parents=True)
    (root / "insights" / "initiatives" / "payments" / "architecture" / "summary.md").write_text(
        "# Payment Architecture\n\nAPI gateway and routing infrastructure design.",
        encoding="utf-8",
    )

    # Area: organisation/platform
    (root / "knowledge" / "organisation" / "platform").mkdir(parents=True)
    (root / "insights" / "organisation" / "platform").mkdir(parents=True)
    (root / "insights" / "organisation" / "platform" / "summary.md").write_text(
        "# Platform\n\nPlatform team structure and responsibilities.",
        encoding="utf-8",
    )

    return root


# ---------------------------------------------------------------------------
# _extract_query_terms tests
# ---------------------------------------------------------------------------


class TestExtractQueryTerms:
    def test_basic_filename(self):
        terms = _extract_query_terms("tps-architecture-review")
        assert terms == ["tps", "architecture", "review"]

    def test_stop_words_removed(self):
        terms = _extract_query_terms("the-architecture-of-the-system")
        assert "the" not in terms
        assert "of" not in terms
        assert "architecture" in terms
        assert "system" in terms

    def test_deduplication(self):
        terms = _extract_query_terms("api-api-gateway", excerpt="api gateway service")
        assert terms.count("api") == 1
        assert terms.count("gateway") == 1

    def test_cap_at_max_terms(self):
        # Filename with many words
        stem = "-".join(f"word{i}" for i in range(20))
        terms = _extract_query_terms(stem)
        assert len(terms) <= MAX_QUERY_TERMS

    def test_excerpt_words_come_after_filename(self):
        terms = _extract_query_terms("report", excerpt="gateway infrastructure design")
        assert terms[0] == "report"
        assert "gateway" in terms

    def test_empty_inputs(self):
        terms = _extract_query_terms("", excerpt="")
        assert terms == []

    def test_single_word(self):
        terms = _extract_query_terms("payments")
        assert terms == ["payments"]

    def test_excerpt_truncated(self):
        long_excerpt = "word " * 1000
        terms = _extract_query_terms("title", excerpt=long_excerpt, max_excerpt_chars=20)
        # Should not have terms from beyond the truncation point
        assert len(terms) <= MAX_QUERY_TERMS

    def test_punctuation_stripped(self):
        terms = _extract_query_terms("hello_world.v2")
        assert "hello" in terms
        assert "world" in terms
        assert "v2" in terms

    def test_only_stop_words(self):
        terms = _extract_query_terms("the-and-or-of")
        assert terms == []


# ---------------------------------------------------------------------------
# suggest_placement tests
# ---------------------------------------------------------------------------


class TestSuggestPlacement:
    def test_single_term_match(self, brain_root):
        index = AreaIndex.build(brain_root)
        result = suggest_placement(index, document_title="tps")
        assert isinstance(result, SuggestPlacementResult)
        assert len(result.candidates) > 0
        assert all(isinstance(c, PlacementCandidate) for c in result.candidates)
        # TPS areas should score highest
        assert "tps" in result.candidates[0].path

    def test_multiple_term_accumulation(self, brain_root):
        index = AreaIndex.build(brain_root)
        result = suggest_placement(index, document_title="tps-meeting-notes")
        # initiatives/tps/meetings should appear because it matches both "tps" and "meeting"
        paths = [c.path for c in result.candidates]
        assert "initiatives/tps/meetings" in paths

    def test_subtree_filtering(self, brain_root):
        index = AreaIndex.build(brain_root)
        result = suggest_placement(
            index,
            document_title="architecture",
            subtree="initiatives/payments",
        )
        for c in result.candidates:
            assert c.path.startswith("initiatives/payments")

    def test_subtree_no_match(self, brain_root):
        index = AreaIndex.build(brain_root)
        result = suggest_placement(
            index,
            document_title="tps",
            subtree="organisation",
        )
        # TPS is under initiatives, not organisation
        assert len(result.candidates) == 0

    def test_empty_index(self, tmp_path):
        root = tmp_path / "empty"
        (root / "insights").mkdir(parents=True)
        (root / "knowledge").mkdir(parents=True)
        index = AreaIndex.build(root)
        result = suggest_placement(index, document_title="anything")
        assert result.candidates == []
        assert result.total_areas == 0

    def test_max_results_respected(self, brain_root):
        index = AreaIndex.build(brain_root)
        result = suggest_placement(index, document_title="tps", max_results=1)
        assert len(result.candidates) <= 1

    def test_max_results_capped_at_10(self, brain_root):
        index = AreaIndex.build(brain_root)
        result = suggest_placement(index, document_title="tps", max_results=100)
        assert len(result.candidates) <= 10

    def test_reasoning_includes_matched_terms(self, brain_root):
        index = AreaIndex.build(brain_root)
        result = suggest_placement(index, document_title="tps")
        for c in result.candidates:
            if "tps" in c.path:
                assert "tps" in c.reasoning.lower()

    def test_no_depth_boost(self, brain_root):
        """Folder depth does not influence scores — only search matches matter."""
        index = AreaIndex.build(brain_root)
        result = suggest_placement(index, document_title="payments")
        scores = {c.path: c.score for c in result.candidates}
        # Both match "payments" in path (x3 from path segment).
        # initiatives/payments also matches in summary body (x2).
        # initiatives/payments/architecture matches "payments" only via parent path,
        # not in its own path segment, so it should score equal or lower.
        if "initiatives/payments/architecture" in scores and "initiatives/payments" in scores:
            assert scores["initiatives/payments"] >= scores["initiatives/payments/architecture"]

    def test_query_terms_returned(self, brain_root):
        index = AreaIndex.build(brain_root)
        result = suggest_placement(index, document_title="tps-architecture")
        assert "tps" in result.query_terms
        assert "architecture" in result.query_terms

    def test_total_areas_reported(self, brain_root):
        index = AreaIndex.build(brain_root)
        result = suggest_placement(index, document_title="anything")
        assert result.total_areas == len(index.entries)
        assert result.total_areas > 0

    def test_deterministic_ordering(self, brain_root):
        """Same input produces same output."""
        index = AreaIndex.build(brain_root)
        r1 = suggest_placement(index, document_title="tps-meeting")
        r2 = suggest_placement(index, document_title="tps-meeting")
        assert [c.path for c in r1.candidates] == [c.path for c in r2.candidates]
        assert [c.score for c in r1.candidates] == [c.score for c in r2.candidates]

    def test_excerpt_enhances_results(self, brain_root):
        index = AreaIndex.build(brain_root)
        # Without excerpt — only "notes" to search
        suggest_placement(index, document_title="notes")
        # With excerpt mentioning TPS
        r2 = suggest_placement(
            index,
            document_title="notes",
            document_excerpt="Discussion about TPS report processing",
        )
        # r2 should have more or different results thanks to TPS terms
        r2_paths = {c.path for c in r2.candidates}
        assert any("tps" in p for p in r2_paths)

    def test_source_param_accepted(self, brain_root):
        """source param is accepted without changing behavior."""
        index = AreaIndex.build(brain_root)
        r1 = suggest_placement(index, document_title="tps")
        r2 = suggest_placement(index, document_title="tps", source="https://example.com/tps")
        assert [c.path for c in r1.candidates] == [c.path for c in r2.candidates]
        assert [c.score for c in r1.candidates] == [c.score for c in r2.candidates]


# ---------------------------------------------------------------------------
# classify_source tests
# ---------------------------------------------------------------------------


class TestClassifySource:
    def test_url_detected(self):
        assert classify_source("https://example.atlassian.net/wiki/pages/123") == SourceKind.URL

    def test_http_url_detected(self):
        assert classify_source("http://example.com/page") == SourceKind.URL

    def test_file_detected(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("hello", encoding="utf-8")
        assert classify_source(str(f)) == SourceKind.FILE

    def test_neither_raises(self):
        with pytest.raises(InvalidSourceSpecifierError):
            classify_source("not-a-url-and-not-a-file-path-xyz")

    def test_relative_path_not_resolved(self, tmp_path, monkeypatch):
        """classify_source does not resolve symlinks — uses Path.exists() on the raw string."""
        f = tmp_path / "notes.md"
        f.write_text("content", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert classify_source("notes.md") == SourceKind.FILE


# ---------------------------------------------------------------------------
# extract_title_from_url tests
# ---------------------------------------------------------------------------


class TestExtractTitleFromUrl:
    def test_confluence_slug(self):
        title = extract_title_from_url("https://acme.atlassian.net/wiki/spaces/TEAM/pages/12345/API-Gateway-Design")
        assert title == "Api Gateway Design"

    def test_google_docs_empty(self):
        title = extract_title_from_url("https://docs.google.com/document/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ/")
        # Last segment is empty after trailing slash; second-to-last is the ID
        # which gets title-cased
        assert isinstance(title, str)

    def test_encoded_chars_decoded(self):
        title = extract_title_from_url("https://example.com/pages/My%20Design%20Doc")
        assert title == "My Design Doc"

    def test_plus_signs_decoded(self):
        title = extract_title_from_url("https://acme.atlassian.net/wiki/spaces/TEAM/pages/12345/ERD+L3+AAA")
        assert title == "Erd L3 Aaa"

    def test_empty_path(self):
        assert extract_title_from_url("https://example.com") == ""

    def test_underscores_replaced(self):
        title = extract_title_from_url("https://example.com/api_gateway_design")
        assert title == "Api Gateway Design"


# ---------------------------------------------------------------------------
# extract_file_excerpt tests
# ---------------------------------------------------------------------------


class TestExtractFileExcerpt:
    def test_md_reads_first_chars(self, tmp_path):
        f = tmp_path / "doc.md"
        content = "x" * 1000
        f.write_text(content, encoding="utf-8")
        excerpt = extract_file_excerpt(f, limit=500)
        assert len(excerpt) == 500
        assert excerpt == "x" * 500

    def test_txt_reads_first_chars(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("hello world", encoding="utf-8")
        assert extract_file_excerpt(f) == "hello world"

    def test_missing_file_returns_empty(self, tmp_path):
        f = tmp_path / "nonexistent.md"
        assert extract_file_excerpt(f) == ""

    def test_unsupported_extension_returns_empty(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c", encoding="utf-8")
        assert extract_file_excerpt(f) == ""
