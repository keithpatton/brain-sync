"""Compatibility shim for doctor flows."""

import sys
from importlib import import_module

_doctor = import_module("brain_sync.application.doctor")

sys.modules[__name__] = _doctor
