"""Shared building blocks for the per-drawing-type extraction schemas."""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class DrawingType(str, Enum):
    FOUNDATION = "foundation"
    COLUMN = "column"
    SLAB = "slab"
    BEAM = "beam"
    UNKNOWN = "unknown"


class ParamStatus(str, Enum):
    FOUND = "found"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class ParamSpec:
    """Definition of one structural parameter the Specialist must extract."""

    key: str
    label: str
    hint: str            # what to look for on the drawing
    unit: str = ""       # expected unit, "" when unitless / text
    required: bool = True


class ExtractedParam(BaseModel):
    key: str
    label: str = ""
    value: Optional[str] = None
    unit: Optional[str] = None
    source_location: Optional[str] = Field(None, description="Where on the drawing the value was read")
    status: ParamStatus = ParamStatus.MISSING
    note: Optional[str] = None
    clarification: Optional[str] = Field(None, description="Question for the engineer when missing/ambiguous")
    edited: bool = False  # set by the UI when the engineer changes the value


class Extraction(BaseModel):
    drawing_type: DrawingType
    drawing_title: Optional[str] = None
    params: List[ExtractedParam]

    def as_dict(self) -> Dict[str, ExtractedParam]:
        return {p.key: p for p in self.params}

    def value(self, key: str) -> Optional[str]:
        p = self.as_dict().get(key)
        return p.value if p and p.status != ParamStatus.MISSING else None


# Parameters that every drawing type carries (general notes / title block).
COMMON_PARAMS: List[ParamSpec] = [
    ParamSpec("site_location", "Site location", "Project site city/state from the title block. NOT the consultant/architect address."),
    ParamSpec("exposure_condition", "Exposure condition", "Environmental exposure (mild/moderate/severe/very severe/extreme) if stated."),
    ParamSpec("concrete_grade", "Grade of concrete", "Concrete grade, e.g. M20, M25. Note per-member grades if they differ.", "N/mm2"),
    ParamSpec("steel_grade", "Grade of steel", "Reinforcement type and grade, e.g. Fe 500 TMT / HYSD, IS 1786.", "N/mm2"),
    ParamSpec("lap_length", "Lap length", "Lap splice length, e.g. 50d or a value in mm."),
    ParamSpec("development_length", "Development length (Ld)", "Anchorage / development length, e.g. 47d or a value in mm."),
    ParamSpec("seismic_zone", "Seismic zone", "Seismic zone (II-V) per IS 1893 if stated."),
]
