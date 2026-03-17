"""Compatibility shim for regen lifecycle helpers."""

import sys
from importlib import import_module

_lifecycle = import_module("brain_sync.regen.lifecycle")

sys.modules[__name__] = _lifecycle
