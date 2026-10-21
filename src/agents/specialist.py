"""Specialist agent: vision extraction of the type-specific parameter schema."""
import json
from typing import List

from src import llm
from src.schemas import DrawingType, Extraction, ExtractedParam, ParamSpec, ParamStatus, get_schema

SYSTEM = """You are a senior Indian structural engineer reading an RCC {dtype} drawing.
Extract ONLY what is written or drawn. Rules:
1. Never invent, assume or compute a value. If it is not on the drawing, status = "missing", value = null.
2. If text is unreadable, contradictory or could mean two things, status = "ambiguous", give your best reading in value and explain in note.
3. For every missing or ambiguous parameter write a short, specific "clarification" question for the engineer.
4. "source_location" = where you read it (e.g. "NOTES item 4", "Footing schedule row F2", "Section A-A").
5. Keep values as written (e.g. "T12@150 c/c", "50d", "M25"); put the unit in "unit" when there is one.
6. Do not confuse the consultant's/architect's address with the site location.
Reply with JSON only."""

USER = """Drawing type: {dtype}
Extract these parameters (key: label - what to look for [expected unit]):
{param_lines}

Return:
{{
  "drawing_title": "<title block text or null>",
  "params": [
    {{"key": "<key>", "value": "<string or null>", "unit": "<string or null>",
      "source_location": "<string or null>", "status": "found|missing|ambiguous",
      "note": "<string or null>", "clarification": "<question or null>"}}
  ]
}}
Include every key listed above exactly once, in the same order."""


def _param_lines(schema: List[ParamSpec]) -> str:
    return "\n".join(
        f"- {p.key}: {p.label} - {p.hint}" + (f" [{p.unit}]" if p.unit else "") for p in schema
    )


def extract(image_urls: List[str], drawing_type: DrawingType) -> Extraction:
    schema = get_schema(drawing_type)
    data = llm.chat_json(
        "specialist",
        SYSTEM.format(dtype=drawing_type.value),
        USER.format(dtype=drawing_type.value, param_lines=_param_lines(schema)),
        image_urls=image_urls,
        temperature=0,
        max_tokens=8000,
    )
    return to_extraction(data, drawing_type)


def to_extraction(data: dict, drawing_type: DrawingType) -> Extraction:
    """Coerce model output onto the schema: unknown keys dropped, absent keys marked missing."""
    schema = get_schema(drawing_type)
    returned = {}
    for item in data.get("params", []) or []:
        if isinstance(item, dict) and item.get("key"):
            returned[item["key"]] = item

    params = []
    for spec in schema:
        item = returned.get(spec.key, {})
        value = item.get("value")
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        value = None if value in (None, "", "null", "N/A", "n/a") else str(value).strip()

        try:
            status = ParamStatus(str(item.get("status", "")).lower())
        except ValueError:
            status = ParamStatus.FOUND if value else ParamStatus.MISSING
        if value is None and status == ParamStatus.FOUND:
            status = ParamStatus.MISSING

        clarification = item.get("clarification")
        if status != ParamStatus.FOUND and not clarification:
            clarification = f"Please provide: {spec.label}" + (f" ({spec.unit})" if spec.unit else "")

        params.append(
            ExtractedParam(
                key=spec.key,
                label=spec.label,
                value=value,
                unit=item.get("unit") or (spec.unit or None),
                source_location=item.get("source_location"),
                status=status,
                note=item.get("note"),
                clarification=clarification if status != ParamStatus.FOUND else None,
            )
        )
    return Extraction(drawing_type=drawing_type, drawing_title=data.get("drawing_title"), params=params)
