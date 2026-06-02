"""Audit logging for write operations — shared infrastructure (write_side_design.md).

Every WRITE primitive records one JSON-Lines entry per call to
``logs/writes_<YYYY-MM-DD>.jsonl``. Read-only primitives are NOT logged: the audit trail
exists to answer "what changed and when", and a read changes nothing. So
``list_savepoints`` (a filesystem scan) is not logged, while ``create_savepoint``,
``restore_savepoint`` and ``set_active_dof`` are.

Entry shape (per the design doc, with the extra detail this project uses):

    {
      "timestamp": "2026-06-02T19:51:53.359000+00:00",   # ISO-8601 UTC
      "operation": "set_active_dof",
      "parameters": { ... all args incl. dry_run, confirm ... },
      "result": "applied" | "preview_only" | "error_<code>",
      "result_details": { ... },
      "elapsed_ms": 12
    }

Implementation choices (pre-flight notes, brechas §21):
  * Plain ``open(path, "a")`` + ``json.dumps`` — no logging stdlib, no third-party dep.
    JSONL is append-only; one line per operation; rotation is by date in the filename.
  * Concurrency: the bridge serialises OAPI calls under a process-wide lock and is
    single-consumer in normal use, so appends do not interleave. Multi-consumer writing
    is explicitly out of scope (design doc, "Lo que NO cubre"). A failed log write must
    NEVER break the operation it records — logging errors are swallowed and warned.
"""
from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

logger = logging.getLogger("sap_bridge.audit_log")

_LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")


def _log_path() -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return os.path.join(_LOGS_DIR, f"writes_{day}.jsonl")


def write_entry(
    operation: str,
    parameters: dict[str, Any],
    result: str,
    result_details: dict[str, Any] | None,
    elapsed_ms: int,
) -> None:
    """Append one audit entry. Never raises — a logging failure must not break the write."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "parameters": parameters,
        "result": result,
        "result_details": result_details or {},
        "elapsed_ms": elapsed_ms,
    }
    try:
        os.makedirs(_LOGS_DIR, exist_ok=True)
        with open(_log_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — audit logging must never break the operation
        logger.warning("audit log write failed for %s: %s", operation, exc)


@contextmanager
def audited(operation: str, parameters: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Context manager that times a write and logs exactly one audit entry.

    Use ``ctx["result"]`` / ``ctx["result_details"]`` inside the block to set the outcome.
    On an exception (a SapSessionError carrying a ``code``, or any error), the entry is
    logged as ``error_<code>`` and the exception re-raised — so failures are audited too.

        with audited("set_active_dof", params) as ctx:
            ...
            ctx["result"] = "applied"
            ctx["result_details"] = {...}
    """
    start = time.monotonic()
    ctx: dict[str, Any] = {"result": "applied", "result_details": {}}
    try:
        yield ctx
    except Exception as exc:  # noqa: BLE001 — log the failure, then re-raise unchanged
        elapsed = int((time.monotonic() - start) * 1000)
        code = getattr(exc, "code", None) or type(exc).__name__
        write_entry(operation, parameters, f"error_{code}", {"message": str(exc)}, elapsed)
        raise
    else:
        elapsed = int((time.monotonic() - start) * 1000)
        write_entry(operation, parameters, ctx["result"], ctx.get("result_details"), elapsed)
