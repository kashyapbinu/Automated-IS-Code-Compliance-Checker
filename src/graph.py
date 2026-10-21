"""LangGraph orchestration of the agents.

    orchestrator ─┬─ human mode ────────► confirm_type ─► specialist ─► human_review ◄───────────┐
                  ├─ auto, known type ──────────────────► specialist      │ edited / first pass │
                  └─ auto, unknown type ─► END                            ▼                     │
                                                                       validator ─ human mode ──┘
                  human_review ─ "run" ─► compliance ─► report ─► END      └─ auto ─► compliance

Human mode (UI) pauses twice with `interrupt()`:
  confirm_type  payload {"classification"}           resume with the drawing type value ("beam", ...)
  human_review  payload {"extraction", "validation"} resume with {"extraction": Extraction} to (re)validate
                                                     edited values, or {"run": True, "notes": "..."} to run
                                                     the compliance check on the current values.
Auto mode (CLI / tests) runs straight through. The retriever is passed in
config["configurable"]["retriever"] so it is never checkpointed.
"""
from typing import List, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src import pipeline
from src.agents.orchestrator import Classification
from src.agents.validator import ValidationResult
from src.schemas import DrawingType, Extraction


class CheckState(TypedDict, total=False):
    urls: List[str]
    human: bool                     # pause for the engineer (UI) or run straight through (CLI)
    use_llm_validator: bool
    source_name: str
    classification: Classification
    drawing_type: DrawingType       # type actually used (engineer override or classification)
    extraction: Extraction
    validation: Optional[ValidationResult]
    run_compliance: bool            # engineer released the verified values for the compliance check
    notes: str
    results: list
    report_markdown: str
    error: str


# --------------------------------------------------------------------------- nodes

def orchestrator_node(state: CheckState) -> dict:
    if state.get("classification"):  # re-run after an engineer type change: keep the original verdict
        return {}
    return {"classification": pipeline.classify(state["urls"])}


def confirm_type_node(state: CheckState) -> dict:
    if state.get("drawing_type"):  # chosen up front (CLI --type or a UI restart with an override)
        return {}
    chosen = interrupt({"classification": state["classification"]})
    return {"drawing_type": DrawingType(chosen)}


def specialist_node(state: CheckState) -> dict:
    if state.get("extraction"):  # restarted with engineer-verified values: don't re-extract
        return {}
    dtype = state.get("drawing_type") or state["classification"].drawing_type
    return {"drawing_type": dtype, "extraction": pipeline.extract(state["urls"], dtype), "validation": None}


def human_review_node(state: CheckState) -> dict:
    if not state.get("human"):
        return {}
    answer = interrupt({"extraction": state["extraction"], "validation": state.get("validation")})
    if answer.get("run"):
        return {"run_compliance": True, "notes": answer.get("notes", "")}
    return {"extraction": answer["extraction"], "run_compliance": False}


def validator_node(state: CheckState) -> dict:
    return {"validation": pipeline.validate(state["extraction"], use_llm=state.get("use_llm_validator", True))}


def compliance_node(state: CheckState, config) -> dict:
    retriever = config.get("configurable", {}).get("retriever")
    validation = state.get("validation") or pipeline.validate(state["extraction"], use_llm=False)
    return {"validation": validation,
            "results": pipeline.comply(state["extraction"], validation, retriever, user_notes=state.get("notes", ""))}


def report_node(state: CheckState) -> dict:
    cls = state["classification"]
    md = pipeline.build_report(state["extraction"], state["validation"], state["results"], cls,
                               overridden=state["drawing_type"] != cls.drawing_type,
                               source_name=state.get("source_name", ""))
    return {"report_markdown": md}


# --------------------------------------------------------------------------- routing

def after_orchestrator(state: CheckState) -> str:
    if state.get("human"):
        return "confirm_type"
    dtype = state.get("drawing_type") or state["classification"].drawing_type
    return "specialist" if dtype != DrawingType.UNKNOWN else "unsupported"


def unsupported_node(state: CheckState) -> dict:
    return {"error": "Unsupported drawing. Only foundation, column, slab and beam drawings can be checked."}


def after_human_review(state: CheckState) -> str:
    return "compliance" if state.get("run_compliance") else "validator"


def after_validator(state: CheckState) -> str:
    return "human_review" if state.get("human") else "compliance"


def build_graph(checkpointer=None):
    g = StateGraph(CheckState)
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("confirm_type", confirm_type_node)
    g.add_node("unsupported", unsupported_node)
    g.add_node("specialist", specialist_node)
    g.add_node("human_review", human_review_node)
    g.add_node("validator", validator_node)
    g.add_node("compliance", compliance_node)
    g.add_node("report", report_node)

    g.add_edge(START, "orchestrator")
    g.add_conditional_edges("orchestrator", after_orchestrator, ["confirm_type", "specialist", "unsupported"])
    g.add_edge("confirm_type", "specialist")
    g.add_edge("unsupported", END)
    g.add_edge("specialist", "human_review")
    g.add_conditional_edges("human_review", after_human_review, ["validator", "compliance"])
    g.add_conditional_edges("validator", after_validator, ["human_review", "compliance"])
    g.add_edge("compliance", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


__all__ = ["CheckState", "build_graph", "Command"]
