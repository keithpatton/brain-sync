"""Compatibility shim for init flows."""

import sys
from importlib import import_module

_init = import_module("brain_sync.application.init")

sys.modules[__name__] = _init
