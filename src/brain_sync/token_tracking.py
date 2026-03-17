"""Compatibility shim for runtime token tracking."""

import sys

from brain_sync.runtime import token_tracking as _token_tracking

sys.modules[__name__] = _token_tracking
