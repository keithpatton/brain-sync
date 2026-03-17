"""Confluence authentication provider."""

from __future__ import annotations

from brain_sync.confluence_rest import ConfluenceAuth, get_confluence_auth


class ConfluenceAuthProvider:
    def load_auth(self) -> ConfluenceAuth | None:
        return get_confluence_auth()

    def configure(self, **kwargs: str) -> None:
        from brain_sync.application.config import configure_confluence

        configure_confluence(domain=kwargs["domain"], email=kwargs["email"], token=kwargs["token"])

    def validate_config(self) -> bool:
        return self.load_auth() is not None
