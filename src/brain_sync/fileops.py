"""Compatibility shim for portable-brain filesystem helpers."""

import sys

from brain_sync.brain import fileops as _fileops

sys.modules[__name__] = _fileops
