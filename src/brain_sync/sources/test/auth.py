"""Trivial auth provider for the test source adapter."""

from __future__ import annotations


class TestAuthProvider:
    def load_auth(self) -> object:
        return {"test": True}

    def configure(self, **kwargs: str) -> None:
        pass

    def validate_config(self) -> bool:
        return True
