"""Compatibility shim for portable insight sidecars."""

import sys

from brain_sync.brain import sidecar as _sidecar

sys.modules[__name__] = _sidecar
