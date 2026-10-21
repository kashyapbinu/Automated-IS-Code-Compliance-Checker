import uuid

import pytest

from src import pipeline
from src.agents.orchestrator import Classification
from src.agents.validator import Issue, ValidationResult
from src.graph import Command, build_graph
from src.schemas import DrawingType
from tests.conftest import make_extraction


@pytest.fixture
def stub_agents(monkeypatch):
    calls = {"classify": 0, "extract": [], "validate": 0, "comply": []}

    def classify(urls):
        calls["classify"] += 1
        return Classification(DrawingType.SLAB, 0.62, "slab plan")

    def extract(urls, dtype):
        calls["extract"].append(dtype)
        return make_extraction(dtype)

    def validate(ex, use_llm=True):
        calls["validate"] += 1
        # first validation finds an error, re-validation after the engineer's edit is clean
        issues = [Issue("error", ["slab_thickness"], "thickness missing")] if calls["validate"] == 1 else []
        return ValidationResult(issues=issues)

    def comply(ex, validation, retriever=None, user_notes=""):
        calls["comply"].append(user_notes)
        return []

    for name, fn in [("classify", classify), ("extract", extract), ("validate", validate), ("comply", comply)]:
        monkeypatch.setattr(pipeline, name, fn)
    return calls


def cfg():
    return {"configurable": {"thread_id": uuid.uuid4().hex}}


def test_auto_mode_runs_straight_through(stub_agents):
    out = build_graph().invoke({"urls": ["u"], "human": False}, cfg())
    assert out["drawing_type"] == DrawingType.SLAB
    assert stub_agents["validate"] == 1 and stub_agents["comply"] == [""]
    assert out["report_markdown"]


def test_auto_mode_honours_type_override(stub_agents):
    out = build_graph().invoke({"urls": ["u"], "human": False, "drawing_type": DrawingType.BEAM}, cfg())
    assert stub_agents["extract"] == [DrawingType.BEAM]
    assert out["drawing_type"] == DrawingType.BEAM


def test_auto_mode_stops_on_unknown_type(stub_agents, monkeypatch):
    monkeypatch.setattr(pipeline, "classify", lambda urls: Classification(DrawingType.UNKNOWN, 0.9, "site plan"))
    out = build_graph().invoke({"urls": ["u"], "human": False}, cfg())
    assert "Unsupported" in out["error"] and not stub_agents["extract"]


def test_human_mode_pauses_and_loops_until_released(stub_agents):
    graph, config = build_graph(), cfg()

    graph.invoke({"urls": ["u"], "human": True}, config)
    snap = graph.get_state(config)
    assert snap.next == ("confirm_type",)
    assert snap.tasks[0].interrupts[0].value["classification"].drawing_type == DrawingType.SLAB

    graph.invoke(Command(resume="beam"), config)  # engineer overrides the type
    snap = graph.get_state(config)
    assert snap.next == ("human_review",) and stub_agents["extract"] == [DrawingType.BEAM]
    assert snap.values["validation"] is None

    ex = snap.values["extraction"]
    graph.invoke(Command(resume={"extraction": ex}), config)  # confirm values -> validator -> back for review
    snap = graph.get_state(config)
    assert snap.next == ("human_review",) and snap.values["validation"].has_errors

    edited = ex.model_copy(update={"params": [p.model_copy(update={"edited": True}) for p in ex.params]})
    graph.invoke(Command(resume={"extraction": edited}), config)  # fix and re-validate
    snap = graph.get_state(config)
    assert snap.next == ("human_review",) and not snap.values["validation"].has_errors
    assert all(p.edited for p in snap.values["extraction"].params)
    assert stub_agents["comply"] == []  # nothing runs until the engineer releases the values

    out = graph.invoke(Command(resume={"run": True, "notes": "coastal site"}), config)
    assert stub_agents["comply"] == ["coastal site"]
    assert graph.get_state(config).next == ()
    assert "beam" in out["report_markdown"].lower()
