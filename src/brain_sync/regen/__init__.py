"""Regen subsystem package."""

from importlib import import_module

_engine = import_module("brain_sync.regen.engine")

__all__ = [name for name in dir(_engine) if not name.startswith("__")]

globals().update({name: getattr(_engine, name) for name in __all__})
