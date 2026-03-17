"""Compatibility shim for portable source-manifest helpers."""

import sys

from brain_sync.brain import manifest as _manifest

sys.modules[__name__] = _manifest
