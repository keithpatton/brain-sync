"""Compatibility shim for the MCP server surface."""

import sys
from importlib import import_module

_server = import_module("brain_sync.interfaces.mcp.server")

sys.modules[__name__] = _server
