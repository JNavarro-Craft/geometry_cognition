"""Locate the SAP2000v1.dll OAPI assembly on Windows.

Ported from RhinoSAP/Utils/PathResolver.cs. The C# version searched for SAP2000.exe;
for the Python OAPI binding we need the managed assembly ``SAP2000v1.dll`` instead,
which ships in the same install directory. Honors an explicit override via the
``SAP_OAPI_DLL`` environment variable so a non-standard install still works.
"""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_BASES = (
    Path(r"C:\Program Files\Computers and Structures"),
    Path(r"C:\Program Files (x86)\Computers and Structures"),
)
_ASSEMBLY_NAME = "SAP2000v1.dll"


def resolve_oapi_dll(preferred_version: str | None = None) -> str | None:
    """Return an absolute path to SAP2000v1.dll, or None if not found.

    Resolution order:
      1. ``SAP_OAPI_DLL`` env var (explicit override), if it points at a file.
      2. ``SAP2000 <preferred_version>`` under each standard base, if requested.
      3. The highest-numbered ``SAP2000 NN`` directory under each standard base.
    """
    override = os.environ.get("SAP_OAPI_DLL")
    if override and Path(override).is_file():
        return str(Path(override))

    if preferred_version:
        for base in _DEFAULT_BASES:
            candidate = base / f"SAP2000 {preferred_version}" / _ASSEMBLY_NAME
            if candidate.is_file():
                return str(candidate)

    for base in _DEFAULT_BASES:
        found = _find_latest(base)
        if found:
            return found
    return None


def _find_latest(base: Path) -> str | None:
    if not base.is_dir():
        return None
    latest_version = -1
    latest_path: str | None = None
    for entry in base.iterdir():
        if not entry.is_dir() or not entry.name.startswith("SAP2000 "):
            continue
        suffix = entry.name[len("SAP2000 "):].strip()
        try:
            version = int(suffix)
        except ValueError:
            continue
        candidate = entry / _ASSEMBLY_NAME
        if candidate.is_file() and version > latest_version:
            latest_version = version
            latest_path = str(candidate)
    return latest_path
