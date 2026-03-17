"""Compatibility shim for portable-brain tree helpers."""

import sys

from brain_sync.brain import tree as _tree

sys.modules[__name__] = _tree
