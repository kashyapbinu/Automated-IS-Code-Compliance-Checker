from typing import Dict, List

from src.schemas.base import (
    DrawingType,
    Extraction,
    ExtractedParam,
    ParamSpec,
    ParamStatus,
)
from src.schemas.beam import BEAM_PARAMS
from src.schemas.column import COLUMN_PARAMS
from src.schemas.foundation import FOUNDATION_PARAMS
from src.schemas.slab import SLAB_PARAMS

SCHEMAS: Dict[DrawingType, List[ParamSpec]] = {
    DrawingType.FOUNDATION: FOUNDATION_PARAMS,
    DrawingType.COLUMN: COLUMN_PARAMS,
    DrawingType.SLAB: SLAB_PARAMS,
    DrawingType.BEAM: BEAM_PARAMS,
}


def get_schema(drawing_type: DrawingType) -> List[ParamSpec]:
    if drawing_type not in SCHEMAS:
        raise ValueError(f"No schema for drawing type '{drawing_type}'.")
    return SCHEMAS[drawing_type]


__all__ = [
    "DrawingType",
    "Extraction",
    "ExtractedParam",
    "ParamSpec",
    "ParamStatus",
    "SCHEMAS",
    "get_schema",
]
