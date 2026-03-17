"""Compatibility shim for runtime config access."""

import sys

from brain_sync.runtime import config as _config

sys.modules[__name__] = _config
