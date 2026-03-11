from __future__ import annotations

import pytest

from brain_sync.sources.confluence import _preprocess_html

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
            '<p>Before</p>'
            '<ac:image><ri:attachment ri:filename="a.png"/></ac:image>'
            '<p>Middle</p>'
            '<ac:image><ri:attachment ri:filename="b.png"/></ac:image>'
            '<p>After</p>'
        )
        result = _preprocess_html(html)
        assert 'attachment-ref:a.png' in result
        assert 'attachment-ref:b.png' in result
        assert '<p>Before</p>' in result
        assert '<p>Middle</p>' in result
        assert '<p>After</p>' in result

    def test_no_confluence_tags(self):
        html = '<p>Normal <strong>HTML</strong></p>'
        result = _preprocess_html(html)
        assert result == html

    def test_filename_with_query_params(self):
        html = '<ac:image><ri:attachment ri:filename="GetClipboardImage.ashx?Id=abc&DC=GAU3"/></ac:image>'
        result = _preprocess_html(html)
        assert 'attachment-ref:GetClipboardImage.ashx?Id=abc&DC=GAU3' in result
