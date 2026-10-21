"""classify -> extract -> (human verify) -> validate -> retrieve + comply -> report.

Stage functions used as the nodes of the LangGraph workflow in src/graph.py.
"""
from dataclasses import asdict
from typing import List, Optional

from PIL import Image

from src import preprocess, report
from src.agents import compliance, orchestrator, specialist, validator
from src.agents.orchestrator import Classification
from src.schemas import DrawingType, Extraction


def image_urls(images: List[Image.Image]) -> List[str]:
    return [preprocess.to_data_url(img) for img in preprocess.prepare_images(images)]


def classify(urls: List[str]) -> Classification:
    return orchestrator.classify(urls)


def extract(urls: List[str], drawing_type: DrawingType) -> Extraction:
    if drawing_type == DrawingType.UNKNOWN:
        raise ValueError("Unsupported drawing. Only foundation, column, slab and beam drawings can be checked.")
    return specialist.extract(urls, drawing_type)


def validate(extraction: Extraction, use_llm: bool = True) -> validator.ValidationResult:
    return validator.validate(extraction, use_llm=use_llm)


def comply(extraction: Extraction, validation: validator.ValidationResult, retriever=None, user_notes: str = ""):
    if retriever is None:
        from src.rag.retriever import Retriever

        retriever = Retriever()
    return compliance.run(extraction, validation.derived, retriever, user_notes=user_notes)


def build_report(extraction: Extraction, validation: Optional[validator.ValidationResult], results,
                 classification: Optional[Classification] = None, overridden: bool = False, source_name: str = "") -> str:
    cls = None
    if classification:
        cls = {**asdict(classification), "drawing_type": classification.drawing_type.value, "overridden": overridden}
    return report.build_markdown(
        extraction,
        validation.to_dict() if validation else None,
        [r.to_dict() for r in results],
        cls,
        source_name,
    )


def run_all(images: List[Image.Image], drawing_type: Optional[DrawingType] = None, use_llm_validator: bool = True,
            source_name: str = "") -> dict:
    """Non-interactive run (CLI / tests): the LangGraph workflow in auto mode, no human verification step."""
    import uuid

    from src.graph import build_graph

    state = {"urls": image_urls(images), "human": False, "use_llm_validator": use_llm_validator,
             "source_name": source_name}
    if drawing_type:
        state["drawing_type"] = drawing_type
    out = build_graph().invoke(state, {"configurable": {"thread_id": uuid.uuid4().hex}})
    if out.get("error"):
        raise ValueError(out["error"])
    return {key: out[key] for key in ("classification", "extraction", "validation", "results", "report_markdown")}
