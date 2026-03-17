"""Compatibility shim for placement flows."""

import sys
from importlib import import_module

_placement = import_module("brain_sync.application.placement")

sys.modules[__name__] = _placement
