"""Compatibility shim for application config flows."""

import sys
from importlib import import_module

_config = import_module("brain_sync.application.config")

sys.modules[__name__] = _config
