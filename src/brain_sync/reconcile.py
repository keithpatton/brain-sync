"""Compatibility shim for sync reconciliation."""

import sys
from importlib import import_module

_reconcile = import_module("brain_sync.sync.reconcile")

sys.modules[__name__] = _reconcile
