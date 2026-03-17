"""Compatibility shim for the portable brain repository seam."""

import sys

from brain_sync.brain import repository as _repository

sys.modules[__name__] = _repository
