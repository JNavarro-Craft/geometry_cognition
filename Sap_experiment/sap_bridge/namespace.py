"""Namespace prefix enforcement — shared write-side infrastructure (write_side_design.md §1).

Every object a consumer of the bridge CREATES must carry a configurable prefix in its name
(default ``AI_`` for the MCP; others may be ``RHINO_``, ``EW_AUTO_``…). The prefix marks
which objects the bridge owns, so it can tell "mine" from "the user's model" and apply the
right confirm rules. Enforcement is UNIVERSAL: every ``create_<noun>`` primitive uses this
utility, no exceptions. The prefix is a property of the SYSTEM, not of any caller — code
that hardcodes a prefix string elsewhere is wrong; it must go through here.

Configuration: ``BRIDGE_NAMESPACE_PREFIX`` env var, read ONCE at import (cacheable; the
bridge is one process per session). Validation is a plain ``startswith`` — no regex.
"""
from __future__ import annotations

import os

from . import error_codes
from .sap_session import SapSessionError

_DEFAULT_PREFIX = "AI_"
# Read once at import. A new prefix needs a bridge restart — fine for a single-process,
# single-consumer bridge (multi-consumer is out of scope, design doc "Lo que NO cubre").
_PREFIX = os.environ.get("BRIDGE_NAMESPACE_PREFIX", _DEFAULT_PREFIX)


def get_bridge_prefix() -> str:
    """The active namespace prefix (from BRIDGE_NAMESPACE_PREFIX, default 'AI_')."""
    return _PREFIX


def has_bridge_prefix(name: str) -> bool:
    """True if ``name`` carries the bridge's prefix (a plain startswith, not regex)."""
    return isinstance(name, str) and name.startswith(_PREFIX)


def assert_prefix_required(name: str) -> None:
    """Raise PREFIX_REQUIRED unless ``name`` carries the bridge prefix.

    Used by create_<noun>: the bridge only creates objects in its own namespace.
    """
    if not has_bridge_prefix(name):
        raise SapSessionError(
            error_codes.PREFIX_REQUIRED,
            f"new objects must be named with the bridge prefix '{_PREFIX}'; "
            f"got '{name}'. Use e.g. '{_PREFIX}{name}'",
        )


def assert_no_conflict(name: str, existing_names: list[str]) -> None:
    """Raise NAME_ALREADY_EXISTS if ``name`` is already taken.

    Essential because SAP's Set* calls overwrite a same-named object SILENTLY (no error),
    so a create without this check would clobber an existing object (verified, brechas §23).
    """
    if name in existing_names:
        raise SapSessionError(
            error_codes.NAME_ALREADY_EXISTS,
            f"an object named '{name}' already exists; choose a different name "
            "(delete is not implemented this phase)",
        )
