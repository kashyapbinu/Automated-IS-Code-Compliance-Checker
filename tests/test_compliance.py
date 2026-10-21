from src.agents import compliance, validator
from src.agents.checks import checks_for
from src.rag.retriever import Hit
from src.report import build_markdown
from src.schemas import DrawingType

from tests.conftest import make_extraction

COVER_HIT = Hit("a", "[IS456 | Cl. 26.4.2.2]\nFor footings minimum cover shall be 50 mm.",
                {"source": "IS456", "clause": "26.4.2.2", "page": 47, "type": "text", "label": ""})
OTHER_HIT = Hit("b", "[SP34 | Cl. 7.1]\nColumns longitudinal bars ...", {"source": "SP34", "clause": "7.1", "page": 90, "type": "text"})


def _check(cid):
    return next(c for c in checks_for(DrawingType.FOUNDATION) if c.id == cid)


def test_guard_accepts_grounded_verdict():
    r = compliance.guard({"status": "Non-Compliant", "clause": "26.4.2.2", "sources": ["S1"], "provided": "40 mm",
                          "requirement": ">= 50 mm"}, _check("cover_footing"), {"S1": COVER_HIT})
    assert r.status == "Non-Compliant" and r.grounded
    assert r.citations[0]["ref"] == "IS456, Cl. 26.4.2.2, p. 47"


def test_guard_rejects_citation_from_other_check():
    r = compliance.guard({"status": "Compliant", "clause": "26.4.2.2", "sources": ["S9"]},
                         _check("cover_footing"), {"S1": COVER_HIT})
    assert r.status == "Insufficient Data" and not r.grounded


def test_guard_rejects_clause_not_in_passages():
    r = compliance.guard({"status": "Compliant", "clause": "34.1.2", "sources": ["S1"]},
                         _check("cover_footing"), {"S1": COVER_HIT})
    assert r.status == "Insufficient Data"
    assert "does not appear" in r.reasoning


def test_guard_allows_insufficient_without_citation():
    r = compliance.guard({"status": "Insufficient Data", "sources": []}, _check("cover_footing"), {"S1": COVER_HIT})
    assert r.status == "Insufficient Data" and r.grounded


class StubRetriever:
    def __init__(self):
        self.queries = []

    def retrieve(self, query, k=None, where=None, expand=True):
        self.queries.append((query, where))
        return [COVER_HIT, OTHER_HIT]


def test_run_retrieves_per_check_and_batches(monkeypatch):
    calls = []

    def fake_chat_json(model, system, user, **kw):
        calls.append(user)
        ids = [line.split("id=")[1].split(" ")[0] for line in user.splitlines() if line.startswith("### Check")]
        first_sid = user.split("[S")[1].split("]")[0]
        return {"results": [{"id": i, "status": "Compliant", "clause": "26.4.2.2", "sources": [f"S{first_sid}"]} for i in ids]}

    monkeypatch.setattr(compliance.llm, "chat_json", fake_chat_json)
    ex = make_extraction(DrawingType.FOUNDATION, cover_footing="50 mm", concrete_grade="M25")
    stub = StubRetriever()
    results = compliance.run(ex, {"fck": 25}, stub, k=2, batch_size=5)

    n = len(checks_for(DrawingType.FOUNDATION))
    assert len(results) == n and len(stub.queries) == n
    assert len(calls) == -(-n // 5)
    assert {"source": "IS456"} in [w for _, w in stub.queries]
    # first check in each batch cites its own passage -> grounded; others cite a passage of another check -> withheld
    assert results[0].status == "Compliant"
    assert results[1].status == "Insufficient Data"


def test_report_markdown():
    ex = make_extraction(DrawingType.FOUNDATION, cover_footing="40 mm")
    val = validator.rule_checks(ex)
    res = [compliance.CheckResult("cover_footing", "Nominal cover", "Non-Compliant", "40 mm", ">= 50 mm", "26.4.2.2",
                                  citations=[{"ref": "IS456, Cl. 26.4.2.2, p. 47"}], recommendation="Increase to 50 mm").to_dict()]
    md = build_markdown(ex, val.to_dict(), res)
    assert "Overall verdict:** NOT COMPLIANT" in md
    assert "26.4.2.2 (IS456, Cl. 26.4.2.2, p. 47)" in md
    assert "## Missing or Wrong Information" in md
