import pytest

from brain_sync.sources.conversion import html_to_markdown

pytestmark = pytest.mark.unit


class TestHtmlToMarkdown:
    def test_basic_heading(self):
        md = html_to_markdown("<h1>Title</h1><p>Body text.</p>")
        assert "# Title" in md
        assert "Body text." in md

    def test_strips_script_and_style(self):
        md = html_to_markdown("<style>body{}</style><script>alert(1)</script><p>Clean</p>")
        assert "body{}" not in md
        assert "alert" not in md
        assert "Clean" in md

    def test_collapses_blank_lines(self):
        md = html_to_markdown("<p>A</p><br><br><br><br><p>B</p>")
        assert "\n\n\n" not in md

    def test_trailing_newline(self):
        md = html_to_markdown("<p>Hello</p>")
        assert md.endswith("\n")
        assert not md.endswith("\n\n")

    def test_deterministic(self):
        html = "<h2>Heading</h2><ul><li>One</li><li>Two</li></ul>"
        assert html_to_markdown(html) == html_to_markdown(html)
