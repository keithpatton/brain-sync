from brain_sync.link_rewriter import rewrite_links


class TestRewriteLinks:
    def test_rewrites_confluence_link(self):
        md = "See [Design Doc](https://x.atlassian.net/wiki/spaces/S/pages/123/Design) for details."
        result = rewrite_links(md, {"confluence:123": "./_sync-context/linked/c123-design.md"})
        assert "[Design Doc](./_sync-context/linked/c123-design.md)" in result

    def test_leaves_unknown_links_intact(self):
        md = "See [Other](https://x.atlassian.net/wiki/spaces/S/pages/999/Unknown)."
        result = rewrite_links(md, {"confluence:123": "path"})
        assert "pages/999" in result

    def test_leaves_non_confluence_links(self):
        md = "See [Google](https://google.com) for more."
        result = rewrite_links(md, {"confluence:123": "path"})
        assert result == md

    def test_rewrites_viewpage_format(self):
        md = "[Page](https://x.atlassian.net/wiki/pages/viewpage.action?pageId=456)"
        result = rewrite_links(md, {"confluence:456": "./linked/c456.md"})
        assert "[Page](./linked/c456.md)" in result

    def test_multiple_links(self):
        md = (
            "See [A](https://x.atlassian.net/wiki/spaces/S/pages/1/A) and "
            "[B](https://x.atlassian.net/wiki/spaces/S/pages/2/B)."
        )
        mapping = {
            "confluence:1": "./linked/c1-a.md",
            "confluence:2": "./linked/c2-b.md",
        }
        result = rewrite_links(md, mapping)
        assert "[A](./linked/c1-a.md)" in result
        assert "[B](./linked/c2-b.md)" in result

    def test_mixed_rewritten_and_intact(self):
        md = (
            "[Known](https://x.atlassian.net/wiki/spaces/S/pages/1/K) and "
            "[Unknown](https://x.atlassian.net/wiki/spaces/S/pages/2/U) and "
            "[External](https://google.com)."
        )
        result = rewrite_links(md, {"confluence:1": "./c1.md"})
        assert "[Known](./c1.md)" in result
        assert "pages/2/U" in result
        assert "google.com" in result

    def test_preserves_non_link_content(self):
        md = "# Title\n\nSome text with no links.\n\n```code```\n"
        result = rewrite_links(md, {})
        assert result == md

    def test_empty_mapping(self):
        md = "[Link](https://x.atlassian.net/wiki/spaces/S/pages/1/X)"
        result = rewrite_links(md, {})
        assert result == md
