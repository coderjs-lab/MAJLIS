import json
import subprocess
import sys
import threading
from pathlib import Path

from majlis.ledger import (GENESIS, Y3172_NODE, Ledger, canonical_json, entry_hash, load_entries,
                           verify_chain, write_manifest)
from majlis.schemas import EVENT_TYPES

ROOT = Path(__file__).resolve().parents[1]


def _fill(run_dir, n=5):
    led = Ledger(run_dir, "r1")
    for i in range(n):
        led.append("T1", "engine", "message", {"i": i, "text": "مرحبا", "nested": {"b": 1, "a": [1, 2]}})
    return led


def _rewrite(path, entries):
    path.write_text("".join(canonical_json(e) + "\n" for e in entries), encoding="utf-8")


def test_canonical_json_is_stable():
    assert canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'


def test_append_and_verify(tmp_path):
    led = _fill(tmp_path)
    entries = load_entries(tmp_path)
    assert [e["seq"] for e in entries] == list(range(5))
    assert entries[0]["prev_hash"] == GENESIS
    assert entries[1]["prev_hash"] == entries[0]["hash"]
    assert entries[0]["ts"].endswith("Z")
    assert all(e["hash"] == entry_hash(e) for e in entries)
    assert verify_chain(tmp_path) == (True, 5, None)
    assert verify_chain(tmp_path / "ledger.jsonl") == (True, 5, None)
    assert led.head == entries[-1]["hash"]


def test_tampered_payload_breaks_at_that_seq(tmp_path):
    _fill(tmp_path)
    entries = load_entries(tmp_path)
    entries[2]["payload"]["i"] = 99
    _rewrite(tmp_path / "ledger.jsonl", entries)
    assert verify_chain(tmp_path) == (False, 5, 2)


def test_tampered_hash_breaks(tmp_path):
    _fill(tmp_path)
    entries = load_entries(tmp_path)
    entries[3]["hash"] = "f" * 64
    assert verify_chain(entries) == (False, 5, 3)


def test_recomputed_hash_still_breaks_next_link(tmp_path):
    _fill(tmp_path)
    entries = load_entries(tmp_path)
    entries[1]["payload"]["i"] = 42
    entries[1]["hash"] = entry_hash(entries[1])  # attacker recomputes this hash
    assert verify_chain(entries) == (False, 5, 2)


def test_deleted_line_breaks(tmp_path):
    _fill(tmp_path)
    lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
    del lines[2]
    (tmp_path / "ledger.jsonl").write_text("".join(lines), encoding="utf-8")
    assert verify_chain(tmp_path) == (False, 4, 2)


def test_reordered_lines_break(tmp_path):
    _fill(tmp_path)
    entries = load_entries(tmp_path)
    entries[1], entries[2] = entries[2], entries[1]
    assert verify_chain(entries)[2] == 1


def test_garbage_line_breaks(tmp_path):
    _fill(tmp_path, 3)
    with open(tmp_path / "ledger.jsonl", "a") as f:
        f.write("not json\n")
    assert verify_chain(tmp_path) == (False, 4, 3)


def test_resume_continues_chain(tmp_path):
    _fill(tmp_path, 3)
    led = Ledger(tmp_path, "r1")
    e = led.append(None, "engine", "run_end", {"status": "completed"})
    assert e.seq == 3
    assert verify_chain(tmp_path) == (True, 4, None)


def test_thread_safe_appends(tmp_path):
    led = Ledger(tmp_path, "r1")
    threads = [threading.Thread(target=lambda k=k: [led.append(None, "a", "message", {"k": k, "j": j})
                                                    for j in range(20)]) for k in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert verify_chain(tmp_path) == (True, 100, None)


def test_y3172_covers_every_event_type():
    assert set(EVENT_TYPES) <= set(Y3172_NODE)
    assert Y3172_NODE["gate_decision"] == "P"


def test_manifest(tmp_path):
    p = write_manifest(tmp_path, {"mode": "governed", "backend": "mock"})
    data = json.loads(p.read_text())
    assert data["mode"] == "governed" and data["started_at"].endswith("Z")


def test_verify_script(tmp_path):
    _fill(tmp_path)
    script = ROOT / "scripts" / "verify_ledger.py"
    ok = subprocess.run([sys.executable, str(script), str(tmp_path)], capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout.startswith("OK: chain verified, 5 entries, head ")
    entries = load_entries(tmp_path)
    entries[4]["payload"]["i"] = -1
    _rewrite(tmp_path / "ledger.jsonl", entries)
    bad = subprocess.run([sys.executable, str(script), str(tmp_path / "ledger.jsonl")],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and bad.stdout.strip() == "BROKEN at seq 4"
