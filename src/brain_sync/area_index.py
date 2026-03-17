"""Compatibility shim for query area indexing."""

import sys
from importlib import import_module

_area_index = import_module("brain_sync.query.area_index")

sys.modules[__name__] = _area_index
