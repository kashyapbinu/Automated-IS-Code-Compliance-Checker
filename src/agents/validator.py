"""Validator agent: internal-consistency and sanity checks on the (engineer-verified) extraction.

This is not the code-compliance check. It answers "do these values make sense together?"
and derives quantities (steel %, ly/lx, ...) that the Compliance agent then checks against the code.
"""
import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from src import llm, units
from src.schemas import DrawingType, Extraction, ParamStatus, get_schema


@dataclass
class Issue:
    severity: str          # "error" | "warning" | "info"
    params: List[str]
    message: str
    source: str = "rules"  # "rules" | "llm"


@dataclass
class ValidationResult:
    issues: List[Issue] = field(default_factory=list)
    derived: Dict[str, object] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def to_dict(self) -> dict:
        return {"issues": [asdict(i) for i in self.issues], "derived": self.derived}


COVER_KEYS = ("cover_footing", "cover_column", "cover_slab", "cover_beam")
SPACING_KEYS = ("tie_spacing", "confining_tie_spacing", "main_bar_spacing", "dist_bar_spacing",
                "stirrup_spacing_support", "stirrup_spacing_mid")
DIA_KEYS = ("long_bar_dia", "tie_dia", "main_bar_dia", "dist_bar_dia", "stirrup_dia")


def _range(result, key, value, lo, hi, what):
    if value is not None and not lo <= value <= hi:
        result.issues.append(Issue("error", [key], f"{what} = {value:g} looks wrong (expected {lo:g}-{hi:g}). Check units / reading."))


def rule_checks(ex: Extraction) -> ValidationResult:
    r = ValidationResult()
    v = ex.value

    # Required parameters still missing after human review.
    params = ex.as_dict()
    for spec in get_schema(ex.drawing_type):
        p = params.get(spec.key)
        if spec.required and (p is None or p.status == ParamStatus.MISSING):
            r.issues.append(Issue("warning", [spec.key], f"{spec.label} is still missing."))
        elif p is not None and p.status == ParamStatus.AMBIGUOUS and not p.edited:
            r.issues.append(Issue("warning", [spec.key], f"{spec.label} is marked ambiguous and was not confirmed."))

    # Material grades.
    fck = units.concrete_grade(v("concrete_grade"))
    if v("concrete_grade") and fck is None:
        r.issues.append(Issue("error", ["concrete_grade"], f"Cannot read a concrete grade from '{v('concrete_grade')}'."))
    _range(r, "concrete_grade", fck, 10, 80, "fck")
    fy = units.steel_grade(v("steel_grade"))
    if v("steel_grade") and fy is None:
        r.issues.append(Issue("error", ["steel_grade"], f"Cannot read a steel grade from '{v('steel_grade')}'."))
    elif fy is not None and fy not in (250, 415, 500, 550, 600):
        r.issues.append(Issue("error", ["steel_grade"], f"Fe {fy} is not a standard IS 1786 / IS 432 grade."))
    if fck:
        r.derived["fck"] = fck
    if fy:
        r.derived["fy"] = fy

    # Covers, spacings, diameters: unit sanity.
    for key in COVER_KEYS:
        _range(r, key, units.length_mm(v(key)), 10, 100, "Cover (mm)")
    for key in SPACING_KEYS:
        sp = units.bar_spacing(v(key))
        spacing = sp[1] if sp else units.length_mm(v(key))
        _range(r, key, spacing, 40, 450, "Spacing (mm)")
    for key in DIA_KEYS:
        dia = units.first_number(v(key))
        if dia is not None and int(dia) not in units.STANDARD_BAR_DIAS:
            r.issues.append(Issue("warning", [key], f"{dia:g} mm is not a standard bar diameter."))
    for key in ("lap_length", "development_length"):
        mult = units.multiple_of_d(v(key))
        _range(r, key, mult, 20, 80, "Multiple of bar diameter")
        if mult is not None:
            r.derived[f"{key}_xd"] = mult

    {
        DrawingType.COLUMN: _column,
        DrawingType.SLAB: _slab,
        DrawingType.BEAM: _beam,
        DrawingType.FOUNDATION: _foundation,
    }.get(ex.drawing_type, lambda *_: None)(ex, r)
    return r


def _column(ex: Extraction, r: ValidationResult):
    v = ex.value
    size = units.section_mm(v("column_size"))
    count = units.first_number(v("long_bar_count"))
    dia = units.first_number(v("long_bar_dia"))
    if size:
        b, d = sorted(size)
        r.derived["column_b_mm"], r.derived["column_D_mm"] = b, d
        _range(r, "column_size", b, 150, 2000, "Column least dimension (mm)")
    if size and count and dia:
        ast = count * units.bar_area(dia)
        pct = round(100 * ast / (size[0] * size[1]), 2)
        r.derived["steel_percentage_computed"] = pct
        stated = units.first_number(v("steel_percentage"))
        if stated and abs(stated - pct) > 0.1 * pct:
            r.issues.append(Issue("error", ["steel_percentage", "long_bar_count", "long_bar_dia", "column_size"],
                                  f"Stated steel {stated:g}% does not match {count:g}-{dia:g} dia in {size[0]:g}x{size[1]:g} = {pct}%."))
    if count is not None and count < 4:
        r.issues.append(Issue("error", ["long_bar_count"], f"{count:g} longitudinal bars is not a valid rectangular column."))
    tie = units.first_number(v("tie_dia"))
    if tie and dia and tie > dia:
        r.issues.append(Issue("warning", ["tie_dia", "long_bar_dia"], "Tie diameter is larger than the main bar diameter - likely swapped."))


def _slab(ex: Extraction, r: ValidationResult):
    v = ex.value
    lx, ly = units.length_mm(v("short_span")), units.length_mm(v("long_span"))
    t = units.length_mm(v("slab_thickness"))
    _range(r, "slab_thickness", t, 75, 500, "Slab thickness (mm)")
    if lx and ly:
        if lx > ly:
            lx, ly = ly, lx
            r.issues.append(Issue("info", ["short_span", "long_span"], "Short and long span were swapped."))
        ratio = round(ly / lx, 2)
        r.derived["ly_lx"] = ratio
        computed = "one-way" if ratio > 2 else "two-way"
        r.derived["slab_type_computed"] = computed
        stated = (v("slab_type") or "").lower()
        if stated and ("one" in stated) != (computed == "one-way"):
            r.issues.append(Issue("error", ["slab_type", "short_span", "long_span"],
                                  f"Slab stated as '{v('slab_type')}' but ly/lx = {ratio} implies {computed}."))
    if lx and t:
        r.derived["span_to_thickness"] = round(lx / t, 1)
        if lx / t > 45:
            r.issues.append(Issue("warning", ["slab_thickness", "short_span"], f"Span/thickness = {lx / t:.0f} is unusually high - check thickness/span reading."))
    main = units.first_number(v("main_bar_dia"))
    dist = units.first_number(v("dist_bar_dia"))
    if main and dist and dist > main:
        r.issues.append(Issue("warning", ["main_bar_dia", "dist_bar_dia"], "Distribution bars larger than main bars - main/distribution may be swapped."))


def _beam(ex: Extraction, r: ValidationResult):
    v = ex.value
    b, d = units.length_mm(v("beam_width")), units.length_mm(v("beam_depth"))
    _range(r, "beam_width", b, 100, 1500, "Beam width (mm)")
    _range(r, "beam_depth", d, 150, 2500, "Beam depth (mm)")
    if b and d:
        if b > d:
            r.issues.append(Issue("warning", ["beam_width", "beam_depth"], "Beam width > depth - check if b and D are swapped."))
        r.derived["side_face_required"] = d > 750
    span = units.length_mm(v("clear_span"))
    if span and d:
        r.derived["span_to_depth"] = round(span / d, 1)
    bottom = units.bar_set(v("bottom_bars"))
    if bottom and b and d:
        cover = units.length_mm(v("cover_beam")) or 25
        eff_d = d - cover - bottom[1] / 2
        pt = round(100 * bottom[0] * units.bar_area(bottom[1]) / (b * eff_d), 2)
        r.derived["tension_steel_percentage"] = pt
        r.derived["effective_depth_mm"] = round(eff_d)
    stirrup = units.first_number(v("stirrup_dia"))
    if stirrup and bottom and stirrup > bottom[1]:
        r.issues.append(Issue("warning", ["stirrup_dia", "bottom_bars"], "Stirrup diameter larger than main bars - likely swapped."))


def _foundation(ex: Extraction, r: ValidationResult):
    v = ex.value
    _range(r, "footing_depth", units.length_mm(v("footing_depth")), 150, 3000, "Footing depth (mm)")
    size = units.section_mm(v("footing_size"))
    col = units.section_mm(v("column_size"))
    if size and col and (min(size) <= min(col) or max(size) <= max(col)):
        r.issues.append(Issue("error", ["footing_size", "column_size"], "Footing is not larger than the column it supports."))
    ftype = (v("footing_type") or "").lower()
    if "raft" in ftype and not v("footing_top_bars"):
        r.issues.append(Issue("warning", ["footing_top_bars"], "Raft foundation without top reinforcement recorded."))
    sbc = units.first_number(v("sbc"))
    if sbc is not None:
        unit_text = (v("sbc") or "").lower()
        kn = sbc * 10 if "t/m" in unit_text else sbc
        r.derived["sbc_kN_m2"] = kn
        _range(r, "sbc", kn, 50, 1000, "SBC (kN/m2)")


LLM_SYSTEM = """You review extracted RCC drawing data for INTERNAL CONSISTENCY only (not code compliance).
Look for: values that contradict each other, schedule entries that disagree with notes, mixed or implausible units,
members referenced but not defined, parameters that look swapped. Ignore anything a deterministic check already flagged.
Reply JSON: {"issues": [{"severity": "error|warning|info", "params": ["<key>", ...], "message": "<one sentence>"}]}.
Return {"issues": []} when nothing is inconsistent."""


def llm_checks(ex: Extraction, known: List[Issue]) -> List[Issue]:
    payload = {
        "drawing_type": ex.drawing_type.value,
        "params": [p.model_dump(include={"key", "label", "value", "unit", "status", "source_location", "note"}) for p in ex.params],
        "already_flagged": [i.message for i in known],
    }
    data = llm.chat_json("validator", LLM_SYSTEM, json.dumps(payload, indent=1), temperature=0, max_tokens=1500)
    keys = {p.key for p in ex.params}
    issues = []
    for item in data.get("issues", []) or []:
        if not isinstance(item, dict) or not item.get("message"):
            continue
        severity = item.get("severity") if item.get("severity") in ("error", "warning", "info") else "warning"
        issues.append(Issue(severity, [k for k in item.get("params", []) if k in keys], item["message"], source="llm"))
    return issues


def validate(ex: Extraction, use_llm: bool = True) -> ValidationResult:
    result = rule_checks(ex)
    if use_llm:
        try:
            result.issues.extend(llm_checks(ex, result.issues))
        except Exception as e:  # LLM pass is advisory; never block on it
            result.issues.append(Issue("info", [], f"LLM consistency pass skipped: {e}", source="llm"))
    return result
