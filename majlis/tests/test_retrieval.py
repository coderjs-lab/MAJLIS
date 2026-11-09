import shutil
from pathlib import Path

import pytest

from majlis.retrieval import KB, normalise_for_search
from majlis.schemas import RetrievalFilters

FIX = Path(__file__).parent / "fixtures" / "kb"


@pytest.fixture(scope="module")
def kb():
    return KB.load(FIX)


def test_normalise_arabic():
    assert normalise_for_search("إِخْطَار  المـكتب") == "اخطار المكتب"
    assert normalise_for_search("مدرسة على") == "مدرسه علي"


def test_bm25_breach(kb):
    res = kb.search("breach notification 72 hours", mode="bm25", k=3)
    assert res[0].clause_id == "TEST-DOC-A/art-2/en"
    assert res[0].rank_bm25 == 1


def test_arabic_query(kb):
    res = kb.search("إخطار المكتب باختراق البيانات", mode="bm25", k=3)
    assert res[0].clause_id == "TEST-DOC-A/art-2/ar"


def test_filters(kb):
    q = "personal data breach controller"
    r = kb.search(q, RetrievalFilters(jurisdiction=["EU"]), mode="bm25")
    assert r and all(e.jurisdiction == "EU" for e in r)
    r = kb.search("artificial intelligence", RetrievalFilters(binding=["non_binding"]), mode="bm25")
    assert r and all(e.binding == "non_binding" for e in r)
    r = kb.search(q, RetrievalFilters(language=["en"]), mode="bm25")
    assert all(e.language == "en" for e in r)
    r = kb.search("health AI", RetrievalFilters(sectors=["telecom"]), mode="bm25")
    assert all(e.clause_id == "TEST-DOC-C/art-7/en" for e in r)


def test_get_parallel_stats(kb):
    assert kb.get("TEST-DOC-A/art-2/en").language == "en"
    assert kb.get("nope") is None
    assert kb.parallel("TEST-DOC-A/art-2/en").clause_id == "TEST-DOC-A/art-2/ar"
    assert kb.parallel("TEST-DOC-A/art-1/en") is None
    s = kb.stats()
    assert s["clauses"] == 10 and s["by_language"]["ar"] == 1
    assert len(kb.version) == 64


def test_no_index_hybrid_degrades(kb):
    assert kb.dense_available is False
    res = kb.search("breach notification 72 hours")
    assert res and res[0].clause_id == "TEST-DOC-A/art-2/en" and res[0].rank_dense is None


@pytest.mark.slow
def test_dense_hybrid(tmp_path):
    try:
        from majlis.retrieval import get_encoder
        get_encoder()
    except Exception as e:
        pytest.skip(f"embedding model unavailable: {e}")
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_index
    d = tmp_path / "kb"
    shutil.copytree(FIX, d)
    assert build_index.main(["--kb-dir", str(d)]) == 0
    kb = KB.load(d)
    assert kb.dense_available
    res = kb.search("breach notification 72 hours", k=5)
    assert res[0].clause_id in {"TEST-DOC-A/art-2/en", "TEST-EU/art-33/en"}
    assert any(e.rank_dense and e.rank_bm25 for e in res)
    assert any(e.rank_dense and e.rank_bm25 is None for e in kb.search("breach notification 72 hours", k=10))
    # cross-lingual: English query reaches the Arabic clause densely
    dres = kb.search("notify the office of a data breach", RetrievalFilters(language=["ar"]), mode="dense")
    assert dres[0].clause_id == "TEST-DOC-A/art-2/ar"
    # stale index ignored
    with open(d / "clauses" / "clauses.jsonl", "a") as f:
        f.write("\n")
    with pytest.warns(UserWarning, match="stale"):
        assert KB.load(d).dense_available is False
