"""Compatibility shim for the application API."""

import brain_sync.application as _application

__all__ = [name for name in dir(_application) if not name.startswith("__")]

globals().update({name: getattr(_application, name) for name in __all__})
