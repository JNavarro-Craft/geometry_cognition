"""OAPI session management for SAP2000 via pythonnet.

Ports the lifecycle PATTERN of RhinoSAP/Core/SapConnector.cs to Python — not the
code verbatim, and deliberately NOT its domain configuration:

  * attach to a running instance (default; the only path enabled this phase),
  * a cheap health probe (``GetModelIsLocked`` round-trip = process alive),
  * disciplined COM release on teardown (Marshal.ReleaseComObject equivalent),
  * an honest reset when the process dies.

What it does NOT do, by design (Principle 3 of the project brief): it never
pre-configures materials, sections, load patterns, combinations or active DOFs, and
it never opens or saves a model. It is a read-only window onto whatever the user
already has open in SAP2000.

The ``mode`` seam is intentional: ``attach`` is the default and the only mode wired
up now; a future ``start`` mode (launch a new SAP2000 like RhinoSAP's
StartNewInstance) can be added without changing callers.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from . import error_codes
from .path_resolver import resolve_oapi_dll

logger = logging.getLogger("sap_bridge.session")

_PROGID = "CSI.SAP2000.API.SapObject"


class SapSessionError(Exception):
    """Raised for session/transport failures. Carries a stable ``code`` from
    ``error_codes`` so the HTTP layer can map it to a structured ErrorResponse."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _load_oapi_namespace() -> Any:
    """Load the SAP2000v1 assembly via pythonnet and return its namespace module.

    Isolated here so the import cost (and its failure modes) are explicit. pythonnet
    lazy-loads namespace members, so the returned module's ``dir()`` may look empty;
    attribute access (``SAP2000v1.Helper``) resolves the type on demand.
    """
    try:
        import clr  # noqa: F401  (pythonnet)
    except ImportError as exc:
        raise SapSessionError(
            error_codes.PYTHONNET_UNAVAILABLE,
            "pythonnet is not installed; cannot load the SAP2000 OAPI assembly",
        ) from exc

    dll = resolve_oapi_dll(os.environ.get("SAP_VERSION"))
    if not dll:
        raise SapSessionError(
            error_codes.ASSEMBLY_NOT_FOUND,
            "SAP2000v1.dll not found; set SAP_OAPI_DLL to its absolute path",
        )

    import clr  # noqa: F811

    clr.AddReference(dll)
    import SAP2000v1  # type: ignore

    logger.info("Loaded SAP2000 OAPI assembly from %s", dll)
    return SAP2000v1


class SapSession:
    """Holds one attached SAP2000 OAPI session. Not safe for concurrent OAPI calls;
    a process-wide lock serializes access since COM/OAPI is single-threaded."""

    def __init__(self) -> None:
        self._oapi: Any | None = None
        self._helper: Any | None = None
        self._sap_object: Any | None = None
        self._sap_model: Any | None = None
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------

    def attach(self) -> None:
        """Attach to a SAP2000 instance the user already has open (COM GetObject).

        Attach-only by design this phase. Raises SapSessionError on failure; never
        launches SAP2000 and never opens a model.
        """
        with self._lock:
            if self.is_alive():
                return
            if self._oapi is None:
                self._oapi = _load_oapi_namespace()
            try:
                # GetObject/CreateObject live on the cHelper INTERFACE, which the
                # concrete Helper implements explicitly — pythonnet needs the cast.
                self._helper = self._oapi.cHelper(self._oapi.Helper())
                self._sap_object = self._helper.GetObject(_PROGID)
                if self._sap_object is None:
                    raise SapSessionError(
                        error_codes.SAP_NOT_RUNNING,
                        "no running SAP2000 instance found to attach to",
                    )
                self._sap_model = self._sap_object.SapModel
                if self._sap_model is None:
                    self._cleanup()
                    raise SapSessionError(
                        error_codes.NO_MODEL_OPEN,
                        "attached to SAP2000 but no SapModel is available",
                    )
                logger.info("Attached to running SAP2000 instance")
            except SapSessionError:
                raise
            except Exception as exc:  # COM failures surface here
                self._cleanup()
                raise SapSessionError(
                    error_codes.SAP_NOT_RUNNING,
                    f"failed to attach to SAP2000: {type(exc).__name__}: {exc}",
                ) from exc

    def is_alive(self) -> bool:
        """Cheap liveness probe: a model handle that answers GetModelIsLocked.

        Mirrors RhinoSAP's CheckProcessAlive. On COM failure the session is reset so
        a subsequent attach starts clean rather than reusing a dead handle.
        """
        with self._lock:
            if self._sap_object is None or self._sap_model is None:
                return False
            try:
                self._sap_model.GetModelIsLocked()
                return True
            except Exception:
                logger.warning("SAP2000 instance stopped responding; resetting session")
                self._cleanup()
                return False

    def sap_model(self) -> Any:
        """Return the live cSapModel, attaching on demand. Raises if unavailable."""
        with self._lock:
            if not self.is_alive():
                self.attach()
            if self._sap_model is None:
                raise SapSessionError(
                    error_codes.SESSION_NOT_ATTACHED,
                    "no SAP2000 session is attached",
                )
            return self._sap_model

    def lock(self) -> threading.RLock:
        """Process-wide lock guarding OAPI calls (COM is single-threaded)."""
        return self._lock

    def oapi_namespace(self) -> Any:
        """The loaded SAP2000v1 module (for enum access, e.g. eFramePropType).
        Loads it on demand if not yet attached."""
        with self._lock:
            if self._oapi is None:
                self._oapi = _load_oapi_namespace()
            return self._oapi

    def detach(self) -> None:
        """Release the session WITHOUT closing SAP2000. The user owns the process;
        attach-only means we never call ApplicationExit."""
        with self._lock:
            self._cleanup()

    # -- internals ---------------------------------------------------------

    def _cleanup(self) -> None:
        """Release COM references in order. The Python GC would eventually do this,
        but explicit release (RhinoSAP's Marshal.ReleaseComObject discipline) avoids
        leaving dangling RCWs that confuse a later attach."""
        try:
            import System  # type: ignore
            from System.Runtime.InteropServices import Marshal  # type: ignore

            for ref in (self._sap_model, self._sap_object, self._helper):
                if ref is not None and Marshal.IsComObject(ref):
                    Marshal.ReleaseComObject(ref)
        except Exception as exc:  # cleanup must never raise
            logger.debug("COM release skipped: %s", exc)
        finally:
            self._sap_model = None
            self._sap_object = None
            self._helper = None


# Process-wide singleton: one bridge process == one SAP session.
_session = SapSession()


def get_session() -> SapSession:
    return _session
