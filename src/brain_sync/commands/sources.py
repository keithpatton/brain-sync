"""Compatibility shim for source-management flows."""

import sys
from importlib import import_module

_sources = import_module("brain_sync.application.sources")

sys.modules[__name__] = _sources
