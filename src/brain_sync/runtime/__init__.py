"""Machine-local runtime persistence and process-local coordination.

Owns runtime DB, config, daemon status, and telemetry state.
Does not own portable-brain semantics or managed brain-root writes.
"""
