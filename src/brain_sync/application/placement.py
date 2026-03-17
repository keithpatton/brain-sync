"""Compatibility shim for query placement helpers."""

import sys
from importlib import import_module

_placement = import_module("brain_sync.query.placement")

sys.modules[__name__] = _placement
