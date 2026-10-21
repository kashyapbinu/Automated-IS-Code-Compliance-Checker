"""Orchestrator agent: classifies the drawing so the right Specialist schema is used."""
from dataclasses import dataclass
from typing import List

from src import llm
from src.schemas import DrawingType

SYSTEM = """You classify RCC structural drawings. Reply with JSON only:
{"type": "foundation" | "column" | "slab" | "beam" | "unknown", "confidence": 0.0-1.0, "reason": "<= 15 words"}
- foundation: footing / raft / pile cap layouts, schedule of footings.
- column: column layout or column schedule / column sections.
- slab: slab reinforcement plans / slab panels.
- beam: beam layouts, beam schedules, beam elevations/sections.
- unknown: architectural drawings, staircases, anything else, or not a structural drawing.
If several member types appear, pick the one the drawing is primarily about (title block / main content)."""


@dataclass
class Classification:
    drawing_type: DrawingType
    confidence: float
    reason: str = ""


def classify(image_urls: List[str]) -> Classification:
    # Deterministic, short output: temperature 0, no reasoning, small token budget.
    data = llm.chat_json(
        "orchestrator",
        SYSTEM,
        "Classify this drawing.",
        image_urls=image_urls,
        temperature=0,
        max_tokens=150,
        reasoning=False,
    )
    return parse_classification(data)


def parse_classification(data: dict) -> Classification:
    raw = str(data.get("type", "unknown")).strip().lower()
    try:
        drawing_type = DrawingType(raw)
    except ValueError:
        drawing_type = DrawingType.UNKNOWN
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return Classification(drawing_type, confidence, str(data.get("reason", "")))
