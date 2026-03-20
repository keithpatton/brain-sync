"""Source adapter protocol and shared data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    import httpx


@runtime_checkable
class SourceStateLike(Protocol):
    canonical_id: str
    source_url: str
    source_type: str
    knowledge_path: str
    knowledge_state: str
    sync_attachments: bool
    last_checked_utc: str | None
    content_hash: str | None
    remote_fingerprint: str | None
    materialized_utc: str | None

    @property
    def target_path(self) -> str: ...


class UpdateStatus(Enum):
    UNCHANGED = auto()
    CHANGED = auto()
    UNKNOWN = auto()


class RemoteSourceMissingError(RuntimeError):
    """Raised when the upstream source reports the document no longer exists."""

    def __init__(self, *, source_type: str, source_id: str, details: str | None = None) -> None:
        self.source_type = source_type
        self.source_id = source_id
        message = details or f"{source_type}:{source_id} is missing upstream"
        super().__init__(message)


@dataclass(frozen=True)
class SourceCapabilities:
    supports_version_check: bool = True
    supports_children: bool = False
    supports_attachments: bool = False
    supports_comments: bool = True


@dataclass(frozen=True)
class UpdateCheckResult:
    status: UpdateStatus
    fingerprint: str | None = None
    title: str | None = None
    adapter_state: dict[str, Any] | None = None


@dataclass
class Comment:
    author: str
    created: str
    content: str
    resolved: bool = False
    replies: list[Comment] = field(default_factory=list)


@dataclass(frozen=True)
class DiscoveredImage:
    """An inline image discovered during source fetch (e.g. Google Docs inline objects)."""

    canonical_id: str  # e.g. "gdoc-image:1AbcXyz:kix.abc123" — also used as attachment-ref key
    download_url: str  # Direct download URL (may be ephemeral)
    title: str | None  # Filename hint
    mime_type: str | None  # e.g. "image/png"


@dataclass
class SourceFetchResult:
    body_markdown: str
    comments: list[Comment] = field(default_factory=list)
    remote_fingerprint: str | None = None
    title: str | None = None
    source_html: str | None = None
    inline_images: list[DiscoveredImage] = field(default_factory=list)
    download_headers: dict[str, str] = field(default_factory=dict)
    attachment_parent_id: str | None = None


@runtime_checkable
class AuthProvider(Protocol):
    def load_auth(self) -> object | None: ...
    def configure(self, **kwargs: str) -> None: ...
    def validate_config(self) -> bool: ...


@runtime_checkable
class SourceAdapter(Protocol):
    @property
    def capabilities(self) -> SourceCapabilities: ...

    @property
    def auth_provider(self) -> AuthProvider: ...

    async def check_for_update(
        self,
        source_state: SourceStateLike,
        auth: object,
        client: httpx.AsyncClient,
    ) -> UpdateCheckResult: ...

    async def fetch(
        self,
        source_state: SourceStateLike,
        auth: object,
        client: httpx.AsyncClient,
        root: Path | None = None,
        prior_adapter_state: dict[str, Any] | None = None,
    ) -> SourceFetchResult: ...
