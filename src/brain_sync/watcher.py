"""Compatibility shim for sync watcher behavior."""

import sys
from importlib import import_module

_watcher = import_module("brain_sync.sync.watcher")

sys.modules[__name__] = _watcher
