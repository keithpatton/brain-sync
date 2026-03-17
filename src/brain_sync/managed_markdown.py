"""Compatibility shim for managed-markdown helpers."""

import sys

from brain_sync.brain import managed_markdown as _managed_markdown

sys.modules[__name__] = _managed_markdown
