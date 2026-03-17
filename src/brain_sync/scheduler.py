"""Compatibility shim for sync scheduling."""

import sys
from importlib import import_module

_scheduler = import_module("brain_sync.sync.scheduler")

sys.modules[__name__] = _scheduler
