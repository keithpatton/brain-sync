"""Compatibility shim for CLI handlers."""

import sys
from importlib import import_module

_handlers = import_module("brain_sync.interfaces.cli.handlers")

sys.modules[__name__] = _handlers
