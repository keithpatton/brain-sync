"""Compatibility shim for the sync pipeline."""

import sys
from importlib import import_module

_pipeline = import_module("brain_sync.sync.pipeline")

sys.modules[__name__] = _pipeline
