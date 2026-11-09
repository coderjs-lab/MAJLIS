"""Writes the fictional stub KB used by tests (no real legal text).

Run: .venv/bin/python tests/fixtures/make_stub_kb.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from majlis.schemas import Clause  # noqa: E402

ROWS = [
    ("TEST-DOC-A/art-1/en", "TEST-DOC-A", "Test Data Law (fictional fixture)", "Test Issuer", "AE", "binding", ["data", "health"], "1", "Health data storage",
     "Health data of patients shall be stored and processed only within the territory of the test state, except in cases specified by a decision of the test authority."),
    ("TEST-DOC-A/art-2/en", "TEST-DOC-A", "Test Data Law (fictional fixture)", "Test Issuer", "AE", "binding", ["data"], "2", "Breach notification",
     "The controller shall notify the test office of any personal data breach within 72 hours of becoming aware of it."),
    ("TEST-DOC-A/art-2/ar", "TEST-DOC-A", "قانون البيانات التجريبي (نموذج اختبار)", "Test Issuer", "AE", "binding", ["data"], "2", "الإخطار بالاختراق",
     "يجب على المتحكم إخطار المكتب التجريبي بأي اختراق للبيانات الشخصية خلال 72 ساعة من علمه به."),
    ("TEST-DOC-B/sec-3/en", "TEST-DOC-B", "Test Health AI Standard (fictional fixture)", "Test Health Regulator", "AE-AZ", "binding", ["health", "ai"], "3", "Performance monitoring",
     "Providers shall continuously monitor the performance of AI systems and shall suspend use of a system where patient safety may be compromised."),
    ("TEST-DOC-B/sec-4/en", "TEST-DOC-B", "Test Health AI Standard (fictional fixture)", "Test Health Regulator", "AE-AZ", "binding", ["health", "ai"], "4", "Incident reporting",
     "Any adverse event involving an AI system shall be reported to the test health regulator without undue delay."),
    ("TEST-DOC-B/sec-5/en", "TEST-DOC-B", "Test Health AI Standard (fictional fixture)", "Test Health Regulator", "AE-AZ", "binding", ["health"], "5", "Continuity of care",
     "Providers shall ensure continuity of care for patients during any disruption of digital health services."),
    ("TEST-DOC-C/art-7/en", "TEST-DOC-C", "Test Telecom Regulation (fictional fixture)", "Test Telecom Authority", "AE", "binding", ["telecom"], "7", "Outage reporting",
     "Licensees shall report any major network outage to the test telecom authority within 24 hours."),
    ("TEST-DOC-D/sec-1/en", "TEST-DOC-D", "Test AI Strategy (fictional fixture)", "Test Government", "AE", "non_binding", ["ai", "general"], "1", "Vision",
     "The test state aims to become a leader in trustworthy artificial intelligence by 2031."),
    ("TEST-EU/art-33/en", "TEST-EU", "Test Global Regulation (fictional fixture)", "Test Union", "EU", "binding", ["data"], "33", "Notification of a breach",
     "In the case of a personal data breach, the controller shall without undue delay and, where feasible, not later than 72 hours after having become aware of it, notify the supervisory authority."),
    ("TEST-EU/art-49/en", "TEST-EU", "Test Global Regulation (fictional fixture)", "Test Union", "EU", "binding", ["data", "health"], "49", "Derogations",
     "A transfer to a third country may take place where the transfer is necessary in order to protect the vital interests of the data subject."),
]

PARALLEL = {"TEST-DOC-A/art-2/en": "TEST-DOC-A/art-2/ar", "TEST-DOC-A/art-2/ar": "TEST-DOC-A/art-2/en"}


def main() -> None:
    out_dir = ROOT / "tests" / "fixtures" / "kb" / "clauses"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "clauses.jsonl", "w", encoding="utf-8") as f:
        for cid, doc, title, issuer, jur, binding, sectors, art, head, text in ROWS:
            c = Clause(
                clause_id=cid, doc_id=doc, doc_title=title, issuer=issuer, jurisdiction=jur,
                instrument_type="test_fixture", binding=binding, sectors=sectors,
                language="ar" if cid.endswith("/ar") else "en", parallel_clause_id=PARALLEL.get(cid),
                article=art, heading=head, text=text, url="https://example.invalid/test-fixture",
                retrieved_at="2026-11-09", source_sha256="0" * 64, tier="TEST",
            )
            f.write(c.model_dump_json() + "\n")
    print(f"wrote {len(ROWS)} fixture clauses to {out_dir / 'clauses.jsonl'}")


if __name__ == "__main__":
    main()
