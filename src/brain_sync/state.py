"""Compatibility shim for machine-local runtime state access."""

import sys

from brain_sync.runtime import repository as _repository

sys.modules[__name__] = _repository
