"""Append-only, SHA-256 hash-chained audit ledger.

Every event of a run is one JSON line in ``run_dir/ledger.jsonl``. Each line
carries the hash of the previous line, so editing, deleting or reordering any
line breaks the chain from that point on. ``verify_chain`` recomputes it.

    hash = sha256(prev_hash + canonical_json(entry_without_hash))
    entry_without_hash = {seq, ts, run_id, stage, actor, event_type, payload, prev_hash}

No LLM is called here.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel

from majlis.schemas import LedgerEntry

GENESIS = "0" * 64
LEDGER_FILE = "ledger.jsonl"
MANIFEST_FILE = "manifest.json"

# event_type -> ITU-T Y.3172 architecture node (CONTRACTS.md table).
Y3172_NODE: dict[str, str] = {
    "run_start": "MLFO",
    "inject": "SRC→C",
    "retrieval": "PP",
    "llm_call": "M",
    "agent_turn": "M",
    "citation_check": "P",
    "gate_decision": "P",
    "human_decision": "SINK (HA)",
    "message": "D",
    "stage_end": "MLFO",
    "gap_candidate": "SINK (GM)",
    "agent_error": "M",
    "metrics": "MLFO",
    "run_end": "MLFO",
}

_HASHED_FIELDS = ("seq", "ts", "run_id", "stage", "actor", "event_type", "payload", "prev_hash")


def _default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no spaces, UTF-8 kept as-is."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def utc_now() -> str:
    """UTC ISO-8601 timestamp ending in 'Z' (millisecond precision)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def entry_hash(entry: dict) -> str:
    """Hash of one entry, computed from its fields other than ``hash``."""
    body = {k: entry.get(k) for k in _HASHED_FIELDS}
    return hashlib.sha256((body["prev_hash"] + canonical_json(body)).encode("utf-8")).hexdigest()


def _ledger_path(path: Path | str) -> Path:
    p = Path(path)
    return p / LEDGER_FILE if p.is_dir() else p


class Ledger:
    """Thread-safe append-only writer. Re-opening an existing ledger resumes
    the chain (next seq, last hash) instead of starting a new one."""

    def __init__(self, run_dir: Path, run_id: str):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / LEDGER_FILE
        self.run_id = run_id
        self._lock = threading.Lock()
        self.seq = 0
        self.prev_hash = GENESIS
        if self.path.exists():
            entries = load_entries(self.path)
            if entries:
                self.seq = entries[-1]["seq"] + 1
                self.prev_hash = entries[-1]["hash"]

    @property
    def head(self) -> str:
        return self.prev_hash

    def append(self, stage: str | None, actor: str, event_type: str, payload: dict) -> LedgerEntry:
        # Round-trip the payload through canonical JSON so the stored payload is
        # exactly what was hashed (pydantic models become plain dicts).
        clean_payload = json.loads(canonical_json(payload))
        with self._lock:
            entry = {
                "seq": self.seq,
                "ts": utc_now(),
                "run_id": self.run_id,
                "stage": stage,
                "actor": actor,
                "event_type": event_type,
                "payload": clean_payload,
                "prev_hash": self.prev_hash,
            }
            entry["hash"] = entry_hash(entry)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(canonical_json(entry) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self.seq += 1
            self.prev_hash = entry["hash"]
        return LedgerEntry(**entry)


def load_entries(path: Path | str) -> list[dict]:
    """Read every line of a ledger (``run_dir`` or the ``.jsonl`` file).
    A line that is not valid JSON is returned as ``{"_invalid_line": text}``
    so ``verify_chain`` can report where it is."""
    entries: list[dict] = []
    with open(_ledger_path(path), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"_invalid_line": line})
    return entries


def verify_chain(path_or_entries: Path | str | Iterable[dict]) -> tuple[bool, int, int | None]:
    """Recompute the chain. Returns ``(ok, n_entries, first_broken_seq)``.

    Entry i is broken if its seq is not i (line deleted/reordered), its
    prev_hash is not the hash of entry i-1, or its stored hash does not match
    the recomputed hash (payload or hash edited).
    """
    if isinstance(path_or_entries, (str, Path)):
        entries = load_entries(path_or_entries)
    else:
        entries = list(path_or_entries)
    prev = GENESIS
    for i, e in enumerate(entries):
        if (
            "_invalid_line" in e
            or e.get("seq") != i
            or e.get("prev_hash") != prev
            or e.get("hash") != entry_hash(e)
        ):
            return False, len(entries), i
        prev = e["hash"]
    return True, len(entries), None


# ---------------------------------------------------------------------------
# Run manifest
# ---------------------------------------------------------------------------

def file_sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit(cwd: Path | str | None = None) -> str | None:
    """Current git commit, or None if not in a repo."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
                             text=True, timeout=5)
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def write_manifest(run_dir: Path, data: dict) -> Path:
    """Write ``run_dir/manifest.json``. The engine supplies git commit, config
    sha256s, KB version, model, backend, mode, approver, lang; ``started_at``
    is filled if missing."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data.setdefault("started_at", utc_now())
    path = run_dir / MANIFEST_FILE
    path.write_text(json.dumps(json.loads(canonical_json(data)), indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n", encoding="utf-8")
    return path
