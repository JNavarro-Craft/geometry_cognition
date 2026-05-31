"""Observational MCP server for Rhino plugin development.

Captures live snapshots of the active Rhino model via the bridge,
persists them by label, and diffs them so a developer can verify
the effect of a plugin command without the MCP executing anything
inside Rhino itself.
"""
