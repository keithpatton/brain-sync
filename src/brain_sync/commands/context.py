"""Compatibility shim for brain root resolution."""

import sys
from importlib import import_module

_roots = import_module("brain_sync.application.roots")

sys.modules[__name__] = _roots
