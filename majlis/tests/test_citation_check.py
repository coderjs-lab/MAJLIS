import pytest

from majlis.citation_check import check_claims, normalise_quote, summarise
from majlis.schemas import Claim
from tests.trust_helpers import load_fake_kb

KB = load_fake_kb()
EVIDENCE = {"TEST-DOC-A/art-2/en", "TEST-DOC-A/art-2/ar", "TEST-DOC-B/sec-4/en"}


def _one(**kw):
    claim = Claim(claim_id="c1", statement="s", **kw)
    return check_claims([claim], EVIDENCE, KB)[0]


def test_unsupported_legal_claim_without_quote():
    assert _one(claim_type="obligation", clause_id="TEST-DOC-A/art-2/en").status == "UNSUPPORTED"
    assert _one(claim_type="prohibition", quote="anything").status == "UNSUPPORTED"


def test_no_citation_for_non_legal_claim():
    assert _one(claim_type="fact_from_inject").status == "NO_CITATION"


def test_unknown_clause():
    r = _one(claim_type="obligation", clause_id="TEST-DOC-X/art-1/en", quote="x")
    assert r.status == "UNKNOWN_CLAUSE"


def test_not_retrieved():
    r = _one(claim_type="obligation", clause_id="TEST-DOC-C/art-7/en",
             quote="report any major network outage")
    assert r.status == "NOT_RETRIEVED"


def test_verified_exact_and_with_curly_quotes_and_dashes():
    r = _one(claim_type="obligation", clause_id="TEST-DOC-A/art-2/en",
             quote="notify the test office of any personal data breach within 72 hours")
    assert r.status == "VERIFIED" and r.score == 100.0
    # Case, extra whitespace and typographic quotes do not matter.
    r = _one(claim_type="obligation", clause_id="TEST-DOC-A/art-2/en",
             quote="“The   CONTROLLER shall notify”")
    assert r.status == "VERIFIED"


def test_verified_arabic_with_diacritics_and_tatweel():
    # Same Arabic text with harakat, a tatweel and a different alef form.
    quote = "يَجِبُ على المتحـــكم إخطار المكتب التجريبي"
    assert _one(claim_type="obligation", clause_id="TEST-DOC-A/art-2/ar", quote=quote).status == "VERIFIED"


def test_near_match_records_score():
    r = _one(claim_type="obligation", clause_id="TEST-DOC-A/art-2/en",
             quote="notify the test office of any personal data breach within 72 hour of becoming aware")
    assert r.status == "NEAR_MATCH" and 90 <= r.score < 100


def test_failed_paraphrase():
    r = _one(claim_type="obligation", clause_id="TEST-DOC-A/art-2/en",
             quote="breaches must be reported to the regulator within 24 hours")
    assert r.status == "FAILED" and r.score < 90


def test_non_legal_claim_with_clause_but_no_quote_fails():
    assert _one(claim_type="recommendation", clause_id="TEST-DOC-A/art-2/en").status == "FAILED"


def test_order_unknown_before_not_retrieved():
    # Unknown clause wins even though it is also not in evidence.
    assert _one(claim_type="definition", clause_id="NOPE", quote="q").status == "UNKNOWN_CLAUSE"


@pytest.mark.parametrize("raw,expected", [
    ("‘a’ «b»", "'a' \"b\""),
    ("x – y — z ‑ w", "x - y - z - w"),
    ("  A\n\tB  ", "a b"),
    ("ＡＢ", "ab"),                      # NFKC full-width
    ("أإآى", "اااي"),                             # alef forms, alef maqsura
    ("فوراً", "فورا"),                            # tanween stripped
])
def test_normalise_quote(raw, expected):
    assert normalise_quote(raw) == expected


def test_summarise_counts_all_statuses():
    claims = [Claim(claim_id="a", statement="s", claim_type="fact_from_inject"),
              Claim(claim_id="b", statement="s", claim_type="obligation")]
    counts = summarise(check_claims(claims, EVIDENCE, KB))
    assert counts["NO_CITATION"] == 1 and counts["UNSUPPORTED"] == 1 and counts["VERIFIED"] == 0
    assert len(counts) == 7


def test_accepts_dict_claims():
    r = check_claims([{"claim_id": "d", "statement": "s", "claim_type": "fact_from_inject"}], set(), KB)
    assert r[0].status == "NO_CITATION"


def test_too_short_quote_fails():
    from majlis.citation_check import check_claims
    from majlis.schemas import Claim
    from tests.trust_helpers import load_fake_kb
    kb = load_fake_kb()
    claim = Claim(claim_id="c1", statement="x", claim_type="obligation",
                  clause_id="TEST-DOC-A/art-2/en", quote="72 hours")
    [r] = check_claims([claim], {"TEST-DOC-A/art-2/en"}, kb)
    assert r.status == "FAILED" and "too short" in (r.note or "")
