"""Verify the hash chain of a MAJLIS run ledger.

Usage: .venv/bin/python scripts/verify_ledger.py <run_dir | ledger.jsonl>
Exit code 0 if the chain verifies, 1 if broken, 2 on usage error.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from majlis.ledger import load_entries, verify_chain  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    target = Path(argv[1])
    path = target / "ledger.jsonl" if target.is_dir() else target
    if not path.exists():
        print(f"ERROR: no ledger at {path}")
        return 2
    entries = load_entries(path)
    ok, n, broken = verify_chain(entries)
    if ok:
        head = entries[-1]["hash"][:12] if entries else "(empty)"
        print(f"OK: chain verified, {n} entries, head {head}")
        return 0
    print(f"BROKEN at seq {broken}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
