"""Compatibility shim for the regen queue."""

import sys
from importlib import import_module

_queue = import_module("brain_sync.regen.queue")

sys.modules[__name__] = _queue
