from __future__ import annotations

import pytest

from brain_sync.sources.confluence import _extract_user_account_ids, _preprocess_html

pytestmark = pytest.mark.unit


class TestPreprocessHtml:
    def test_basic_image_tag(self):
        html = '<ac:image><ri:attachment ri:filename="diagram.png"/></ac:image>'
        result = _preprocess_html(html)
        assert '<img src="attachment-ref:diagram.png" alt="diagram.png">' in result

    def test_with_extra_attributes(self):
        html = '<ac:image ac:width="600" ac:align="center"><ri:attachment ri:filename="screenshot.png"/></ac:image>'
        result = _preprocess_html(html)
        assert '<img src="attachment-ref:screenshot.png" alt="screenshot.png">' in result

    def test_with_whitespace(self):
        html = """<ac:image>
            <ri:attachment ri:filename="photo.jpg" />
        </ac:image>"""
        result = _preprocess_html(html)
        assert '<img src="attachment-ref:photo.jpg" alt="photo.jpg">' in result

    def test_multiple_images(self):
        html = (
            "<p>Before</p>"
            '<ac:image><ri:attachment ri:filename="a.png"/></ac:image>'
            "<p>Middle</p>"
            '<ac:image><ri:attachment ri:filename="b.png"/></ac:image>'
            "<p>After</p>"
        )
        result = _preprocess_html(html)
        assert "attachment-ref:a.png" in result
        assert "attachment-ref:b.png" in result
        assert "<p>Before</p>" in result
        assert "<p>Middle</p>" in result
        assert "<p>After</p>" in result

    def test_no_confluence_tags(self):
        html = "<p>Normal <strong>HTML</strong></p>"
        result = _preprocess_html(html)
        assert result == html

    def test_filename_with_query_params(self):
        html = '<ac:image><ri:attachment ri:filename="GetClipboardImage.ashx?Id=abc&DC=GAU3"/></ac:image>'
        result = _preprocess_html(html)
        assert "attachment-ref:GetClipboardImage.ashx?Id=abc&DC=GAU3" in result

    def test_status_macro_renders_title_only(self):
        html = (
            '<ac:structured-macro ac:name="status">'
            '<ac:parameter ac:name="title">APPROVER</ac:parameter>'
            '<ac:parameter ac:name="colour">Yellow</ac:parameter>'
            "</ac:structured-macro>"
        )
        result = _preprocess_html(html)
        assert result == "APPROVER"

    def test_emoticon_uses_agent_friendly_text(self):
        html = (
            '<ac:emoticon ac:name="cross" ac:emoji-fallback=":cross_mark:" /> or '
            '<ac:emoticon ac:name="tick" ac:emoji-fallback=":check_mark:" />'
        )
        result = _preprocess_html(html)
        assert result == "No or Yes"

    def test_unknown_emoticon_falls_back_to_name(self):
        html = '<ac:emoticon ac:name="blue-star" ac:emoji-fallback=":slack:" />'
        result = _preprocess_html(html)
        assert result == "blue-star"

    def test_user_mentions_render_display_names(self):
        html = (
            '<p><ac:link><ri:user ri:account-id="user-1" /></ac:link></p>'
            '<p><ac:link><ri:user ri:account-id="user-2" /></ac:link></p>'
        )
        result = _preprocess_html(html, user_names={"user-1": "Alice", "user-2": "Bob"})
        assert "Alice" in result
        assert "Bob" in result

    def test_user_mentions_fall_back_to_account_id_when_unresolved(self):
        html = '<p><ac:link><ri:user ri:account-id="user-1" /></ac:link></p>'
        result = _preprocess_html(html, user_names={})
        assert "user-1" in result


class TestExtractUserAccountIds:
    def test_extracts_unique_user_account_ids(self):
        html = (
            '<ac:link><ri:user ri:account-id="user-1" /></ac:link>'
            '<ac:link><ri:user ri:account-id="user-2" /></ac:link>'
            '<ac:link><ri:user ri:account-id="user-1" /></ac:link>'
        )
        assert _extract_user_account_ids(html) == ["user-1", "user-2"]
