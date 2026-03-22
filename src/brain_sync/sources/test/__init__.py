"""Test source adapter — reads scripted responses from JSON scenario files.

Used by E2E tests to exercise the full source-sync pipeline without
real external credentials.  URLs use the ``test://`` scheme.

Scenario files live at ``{brain_root}/.test-adapter/{canonical_id}.json``
and contain a JSON object with a ``sequence`` list::

    {
        "sequence": [
            {"status": "CHANGED", "body": "# Topic\\nFirst version", "title": "My Topic"},
            {"status": "UNCHANGED"},
            {"status": "ERROR", "error": "connection timeout"}
        ],
        "delay_ms": 0
    }

The adapter advances through the sequence on each ``check_for_update`` /
``fetch`` call.  After the last entry, the final entry repeats forever.

Cursor state is persisted to a sidecar file
``{root}/.test-adapter/{canonical_id}.cursor`` so restart tests are
deterministic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from brain_sync.sources.base import (
    AuthProvider,
    SourceCapabilities,
    SourceFetchResult,
    SourceStateLike,
    UpdateCheckResult,
    UpdateStatus,
)
from brain_sync.sources.test.auth import TestAuthProvider

log = logging.getLogger(__name__)

_auth_provider = TestAuthProvider()


def _scenario_path(root: Path, canonical_id: str) -> Path:
    """Return the path to the scenario JSON for a given canonical_id."""
    safe_name = canonical_id.replace(":", "_")
    return root / ".test-adapter" / f"{safe_name}.json"


def _cursor_path(root: Path, canonical_id: str) -> Path:
    """Return the path to the persisted cursor file for a given canonical_id."""
    safe_name = canonical_id.replace(":", "_")
    return root / ".test-adapter" / f"{safe_name}.cursor"


def _read_cursor(root: Path, canonical_id: str) -> int:
    """Read the persisted cursor value, defaulting to 0."""
    path = _cursor_path(root, canonical_id)
    if path.exists():
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return 0
    return 0


def _write_cursor(root: Path, canonical_id: str, value: int) -> None:
    """Persist the cursor value to disk."""
    path = _cursor_path(root, canonical_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value), encoding="utf-8")


def _load_scenario_entry(root: Path, canonical_id: str) -> dict[str, Any]:
    """Load the current scenario entry and advance the persisted cursor."""
    path = _scenario_path(root, canonical_id)
    if not path.exists():
        return {"status": "UNCHANGED"}

    data = json.loads(path.read_text(encoding="utf-8"))
    sequence = data.get("sequence", [{"status": "UNCHANGED"}])

    idx = _read_cursor(root, canonical_id)
    # Clamp to last entry (repeat forever)
    entry_idx = min(idx, len(sequence) - 1)
    entry = dict(sequence[entry_idx])  # copy to avoid mutating original

    _write_cursor(root, canonical_id, idx + 1)

    delay_ms = entry.get("delay_ms", data.get("delay_ms", 0))
    if delay_ms > 0:
        entry["_delay_ms"] = delay_ms

    return entry


def reset_call_counters() -> None:
    """Reset all in-memory state (backward compat alias)."""


class TestAdapter:
    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            supports_version_check=True,
            supports_children=False,
            supports_attachments=False,
            supports_comments=False,
        )

    @property
    def auth_provider(self) -> AuthProvider:
        return _auth_provider

    async def check_for_update(
        self,
        source_state: SourceStateLike,
        auth: object,
        client: httpx.AsyncClient,
    ) -> UpdateCheckResult:
        root = _resolve_root(source_state)
        if root is None:
            return UpdateCheckResult(status=UpdateStatus.UNKNOWN)

        entry = _load_scenario_entry(root, source_state.canonical_id)

        delay = entry.get("_delay_ms", 0)
        if delay > 0:
            await asyncio.sleep(delay / 1000.0)

        status_str = entry.get("status", "UNCHANGED")

        if status_str == "ERROR":
            raise RuntimeError(entry.get("error", "test adapter error"))

        if status_str == "UNCHANGED":
            return UpdateCheckResult(status=UpdateStatus.UNCHANGED)

        # CHANGED — compute a fingerprint from the body
        body = entry.get("body", "")
        fingerprint = sha256(body.encode()).hexdigest()[:16]
        return UpdateCheckResult(
            status=UpdateStatus.CHANGED,
            fingerprint=fingerprint,
            title=entry.get("title"),
        )

    async def fetch(
        self,
        source_state: SourceStateLike,
        auth: object,
        client: httpx.AsyncClient,
        root: Path | None = None,
        prior_adapter_state: dict[str, Any] | None = None,
    ) -> SourceFetchResult:
        resolved_root = root or _resolve_root(source_state)
        if resolved_root is None:
            raise RuntimeError("Cannot resolve brain root for test adapter")

        # check_for_update already advanced the cursor, so read cursor-1
        # to get the same entry.
        path = _scenario_path(resolved_root, source_state.canonical_id)
        if not path.exists():
            return SourceFetchResult(body_markdown="", title=None)

        data = json.loads(path.read_text(encoding="utf-8"))
        sequence = data.get("sequence", [{"status": "UNCHANGED"}])
        idx = _read_cursor(resolved_root, source_state.canonical_id) - 1
        entry_idx = min(max(idx, 0), len(sequence) - 1)
        entry = sequence[entry_idx]

        body = entry.get("body", "")
        fingerprint = sha256(body.encode()).hexdigest()[:16]

        return SourceFetchResult(
            body_markdown=body,
            remote_fingerprint=fingerprint,
            title=entry.get("title"),
        )


def _resolve_root(source_state: SourceStateLike) -> Path | None:
    """Resolve brain root from the module-level registry or config."""
    root = _root_registry.get(source_state.canonical_id)
    if root is not None:
        return root

    # Fallback: resolve from config (works in subprocess contexts)
    try:
        from brain_sync.runtime.config import active_brain_root, load_config

        cfg = load_config()
        brain_root = active_brain_root(cfg) or cfg.get("brain_root")
        if brain_root:
            return Path(brain_root)
    except Exception:
        pass
    return None


# Module-level root registry for test adapter (set by harness helpers)
_root_registry: dict[str, Path] = {}


def register_test_root(canonical_id: str, root: Path) -> None:
    """Register the brain root for a test source (called by harness)."""
    _root_registry[canonical_id] = root


def reset_test_adapter() -> None:
    """Full reset of test adapter state (root registry)."""
    _root_registry.clear()
