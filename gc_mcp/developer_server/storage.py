"""Snapshot persistence for developer_server.

Snapshots live in ``${GC_OUTPUTS_DIR}/dev_snapshots/`` as JSON files named
``snapshot__<timestamp_utc>__<label_slug>.json``. With overwrite semantics:
if a snapshot already exists for a given label, it is replaced.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_OUTPUTS_DIR = r"C:\geometry_cognition\outputs"
SNAPSHOTS_SUBDIR = "dev_snapshots"
SNAPSHOT_SCHEMA = "developer_snapshot.v2"

_LABEL_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_SNAPSHOT_FILENAME_RE = re.compile(
    r"^snapshot__(?P<ts>\d{8}T\d{6}Z)__(?P<label>[a-z0-9_-]+)\.json$"
)


def outputs_dir() -> Path:
    raw = os.environ.get("GC_OUTPUTS_DIR", "").strip()
    return Path(raw or DEFAULT_OUTPUTS_DIR)


def snapshots_dir() -> Path:
    return outputs_dir() / SNAPSHOTS_SUBDIR


def slugify_label(label: str) -> str:
    text = str(label or "").strip().lower().replace(" ", "_")
    text = _LABEL_SLUG_RE.sub("_", text)
    text = text.strip("_-")
    return text


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _snapshot_filename(label_slug: str, timestamp: str) -> str:
    return f"snapshot__{timestamp}__{label_slug}.json"


def list_snapshot_files() -> list[dict[str, Any]]:
    """List snapshot files in chronological order (oldest first by filename)."""
    base = snapshots_dir()
    if not base.exists():
        return []
    out: list[dict[str, Any]] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_file():
            continue
        m = _SNAPSHOT_FILENAME_RE.match(entry.name)
        if not m:
            continue
        out.append(
            {
                "label": m.group("label"),
                "captured_at_utc_compact": m.group("ts"),
                "path": str(entry),
                "size_bytes": entry.stat().st_size,
                "mtime": entry.stat().st_mtime,
            }
        )
    return out


def find_latest_by_label(label_slug: str) -> Path | None:
    """Return the path of the most recent snapshot for a given label slug."""
    if not label_slug:
        return None
    matching = [
        entry for entry in list_snapshot_files() if entry["label"] == label_slug
    ]
    if not matching:
        return None
    matching.sort(key=lambda e: e["mtime"], reverse=True)
    return Path(matching[0]["path"])


def delete_existing_for_label(label_slug: str) -> list[str]:
    """Remove all existing snapshots whose label matches; return deleted paths."""
    deleted: list[str] = []
    for entry in list_snapshot_files():
        if entry["label"] == label_slug:
            try:
                Path(entry["path"]).unlink()
                deleted.append(entry["path"])
            except OSError:
                pass
    return deleted


def prune_snapshots(keep_latest_n: int) -> tuple[list[str], list[str]]:
    """Keep only the ``keep_latest_n`` most recent snapshots per label; delete the rest.

    Grouping is by label, so e.g. ``keep_latest_n=1`` keeps the newest snapshot of
    each label and removes older same-label captures. Returns (kept_paths, deleted_paths).
    """
    keep = max(0, int(keep_latest_n))
    by_label: dict[str, list[dict[str, Any]]] = {}
    for entry in list_snapshot_files():
        by_label.setdefault(entry["label"], []).append(entry)

    kept: list[str] = []
    deleted: list[str] = []
    for entries in by_label.values():
        entries.sort(key=lambda e: e["mtime"], reverse=True)
        for entry in entries[:keep]:
            kept.append(entry["path"])
        for entry in entries[keep:]:
            try:
                Path(entry["path"]).unlink()
                deleted.append(entry["path"])
            except OSError:
                pass
    return kept, deleted


def write_snapshot(payload: dict[str, Any], label_slug: str) -> tuple[Path, str, list[str]]:
    """Persist a snapshot payload (overwrite semantics).

    Returns (path, captured_at_utc_compact, replaced_paths).
    """
    base = snapshots_dir()
    base.mkdir(parents=True, exist_ok=True)
    replaced = delete_existing_for_label(label_slug)
    timestamp = _utc_timestamp()
    path = base / _snapshot_filename(label_slug, timestamp)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=False)
    return path, timestamp, replaced


def read_snapshot(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("snapshot_invalid_shape")
    return data


def captured_at_iso(compact: str) -> str:
    """Convert ``20260525T143012Z`` to ``2026-05-25T14:30:12Z``."""
    if not compact or len(compact) != 16:
        return compact
    return (
        f"{compact[0:4]}-{compact[4:6]}-{compact[6:8]}"
        f"T{compact[9:11]}:{compact[11:13]}:{compact[13:15]}Z"
    )
