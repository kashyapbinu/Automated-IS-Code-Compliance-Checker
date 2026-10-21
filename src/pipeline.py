"""classify -> extract -> (human verify) -> validate -> retrieve + comply -> report.

Each stage is a separate function so the UI can pause between them for the engineer.
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
    """Non-interactive run (CLI / tests): no human verification step."""
    urls = image_urls(images)
    classification = classify(urls)
    dtype = drawing_type or classification.drawing_type
    extraction = extract(urls, dtype)
    validation = validate(extraction, use_llm=use_llm_validator)
    results = comply(extraction, validation)
    md = build_report(extraction, validation, results, classification, overridden=drawing_type is not None and drawing_type != classification.drawing_type, source_name=source_name)
    return {
        "classification": classification,
        "extraction": extraction,
        "validation": validation,
        "results": results,
        "report_markdown": md,
    }
