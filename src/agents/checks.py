"""Compliance check registry: which parameters each check uses and how to query the codebooks for it.

Each check gets its own retrieval query (instead of one query for the whole report), so the
Compliance agent sees the clauses that actually govern that parameter.
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple

from src.schemas import DrawingType


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    params: Tuple[str, ...]
    query: str
    sources: Tuple[str, ...] = ("IS456", "SP34")


COMMON_CHECKS = [
    Check("concrete_grade", "Minimum concrete grade for exposure", ("concrete_grade", "exposure_condition", "site_location"),
          "minimum grade of reinforced concrete for environmental exposure condition durability"),
    Check("steel_grade", "Reinforcement type and grade", ("steel_grade",),
          "types of reinforcement high strength deformed steel bars grade Fe 415 Fe 500"),
    Check("lap_length", "Lap splice length", ("lap_length", "steel_grade", "concrete_grade"),
          "lap splices length flexural tension direct tension compression lap length not less than"),
    Check("development_length", "Development length", ("development_length", "steel_grade", "concrete_grade"),
          "development length of bars Ld design bond stress deformed bars"),
]

TYPE_CHECKS: Dict[DrawingType, List[Check]] = {
    DrawingType.FOUNDATION: [
        Check("cover_footing", "Nominal cover to footing reinforcement", ("cover_footing", "exposure_condition", "pcc_below_footing"),
              "nominal cover footings minimum cover 50 mm", ("IS456",)),
        Check("cover_column", "Nominal cover to column/pedestal bars", ("cover_column",),
              "nominal cover longitudinal reinforcing bar in a column not less than 40 mm"),
        Check("footing_depth", "Minimum footing depth at edge", ("footing_depth", "footing_type"),
              "thickness at the edge of footing reinforced concrete footings not less than 150 mm", ("IS456",)),
        Check("footing_reinforcement", "Footing reinforcement and spacing", ("footing_bottom_bars", "footing_top_bars", "footing_size", "footing_type"),
              "footing tensile reinforcement distribution across width minimum reinforcement spacing of bars"),
        Check("dowels", "Load transfer at column base / starter bars", ("column_long_bars", "ties_continuous", "column_ties"),
              "transfer of load at the base of column dowels starter bars extend into footing"),
        Check("column_ties", "Column ties in pedestal", ("column_ties", "column_long_bars", "column_size"),
              "transverse reinforcement column lateral ties pitch diameter not less than one fourth"),
        Check("column_steel", "Column starter steel percentage", ("column_long_bars", "column_size"),
              "longitudinal reinforcement in column not less than 0.8 percent not more than 6 percent gross cross sectional area"),
        Check("raft_reinforcement", "Raft top and bottom reinforcement", ("footing_type", "footing_top_bars", "footing_bottom_bars"),
              "raft foundation detailing top and bottom reinforcement mat", ("SP34",)),
        Check("foundation_detailing", "Footing detailing practice (SP 34)", ("footing_type", "footing_schedule", "pcc_below_footing", "founding_depth"),
              "detailing of isolated footings sloped footing schedule foundations", ("SP34",)),
    ],
    DrawingType.COLUMN: [
        Check("column_steel", "Longitudinal steel percentage", ("long_bar_count", "long_bar_dia", "column_size", "steel_percentage"),
              "longitudinal reinforcement in column not less than 0.8 percent not more than 6 percent gross cross sectional area"),
        Check("min_bars", "Minimum number and diameter of bars", ("long_bar_count", "long_bar_dia"),
              "minimum number of longitudinal bars rectangular column four circular six bars not less than 12 mm diameter"),
        Check("tie_dia", "Lateral tie diameter", ("tie_dia", "long_bar_dia"),
              "diameter of polygonal links or lateral ties not less than one fourth diameter of largest longitudinal bar 6 mm"),
        Check("tie_pitch", "Lateral tie pitch", ("tie_spacing", "column_size", "long_bar_dia"),
              "pitch of transverse reinforcement least lateral dimension 16 times smallest diameter 300 mm"),
        Check("tie_arrangement", "Tie arrangement / cross ties", ("tie_configuration", "tie_hook", "long_bar_count"),
              "arrangement of transverse reinforcement corner and alternate bars lateral support 75 mm"),
        Check("cover_column", "Nominal cover to column bars", ("cover_column", "exposure_condition"),
              "nominal cover longitudinal reinforcing bar in a column not less than 40 mm"),
        Check("slenderness", "Short / slender column", ("column_size", "unsupported_length"),
              "short and slender compression members effective length ratio less than 12"),
        Check("lap_location", "Lap location in columns", ("lap_location", "lap_length"),
              "laps in columns staggered splices location detailing", ("SP34",)),
        Check("section_change", "Bar cranking at change of section", ("section_change", "starter_bars"),
              "offset bars cranked column change in cross section detailing", ("SP34",)),
    ],
    DrawingType.SLAB: [
        Check("slab_thickness", "Span/depth ratio (deflection)", ("slab_thickness", "short_span", "support_condition"),
              "control of deflection basic values span to effective depth ratio simply supported continuous cantilever", ("IS456",)),
        Check("min_steel", "Minimum reinforcement in slab", ("main_bar_dia", "main_bar_spacing", "dist_bar_dia", "dist_bar_spacing", "slab_thickness"),
              "minimum reinforcement in slabs 0.15 percent mild steel 0.12 percent high strength deformed bars", ("IS456",)),
        Check("main_spacing", "Maximum spacing of main bars", ("main_bar_spacing", "slab_thickness"),
              "maximum distance between bars slabs main reinforcement three times effective depth or 300 mm", ("IS456",)),
        Check("dist_spacing", "Maximum spacing of distribution bars", ("dist_bar_spacing", "slab_thickness"),
              "spacing of distribution bars five times effective depth or 450 mm", ("IS456",)),
        Check("max_dia", "Maximum bar diameter in slab", ("main_bar_dia", "dist_bar_dia", "slab_thickness"),
              "maximum diameter of bars in slabs not exceed one eighth of total thickness", ("IS456",)),
        Check("cover_slab", "Nominal cover to slab bars", ("cover_slab", "exposure_condition"),
              "nominal cover to meet durability requirements exposure mild moderate severe", ("IS456",)),
        Check("two_way", "Two-way slab action and corner reinforcement", ("slab_type", "short_span", "long_span", "torsion_reinforcement"),
              "two way slabs restrained corners torsion reinforcement ly/lx ratio"),
        Check("top_bars", "Top bars over supports / curtailment", ("top_bars_support", "curtailment", "support_condition"),
              "slab detailing top bars over support extend 0.3 span curtailment of bars", ("SP34",)),
        Check("cantilever", "Cantilever slab detailing", ("cantilever_details",),
              "cantilever slab reinforcement anchorage into back span detailing", ("SP34",)),
    ],
    DrawingType.BEAM: [
        Check("min_tension", "Minimum tension reinforcement", ("bottom_bars", "beam_width", "beam_depth", "steel_grade"),
              "minimum reinforcement in beams As/bd = 0.85/fy tension reinforcement", ("IS456",)),
        Check("max_steel", "Maximum tension / compression steel", ("bottom_bars", "top_bars", "extra_top_bars", "beam_width", "beam_depth"),
              "maximum tension reinforcement maximum compression reinforcement beam not exceed 0.04 bD", ("IS456",)),
        Check("side_face", "Side face reinforcement", ("side_face_bars", "beam_depth", "beam_width"),
              "side face reinforcement depth of web exceeds 750 mm 0.1 percent of web area", ("IS456",)),
        Check("stirrup_spacing", "Maximum stirrup spacing", ("stirrup_spacing_support", "stirrup_spacing_mid", "beam_depth"),
              "maximum spacing of shear reinforcement 0.75 d vertical stirrups not exceed 300 mm", ("IS456",)),
        Check("min_shear", "Minimum shear reinforcement", ("stirrup_dia", "stirrup_legs", "stirrup_spacing_mid", "beam_width", "steel_grade"),
              "minimum shear reinforcement Asv/(b sv) 0.4/0.87fy", ("IS456",)),
        Check("bar_spacing", "Clear distance between bars", ("bar_clear_spacing", "bottom_bars", "beam_width", "cover_beam", "stirrup_dia"),
              "minimum distance between individual bars horizontal distance not less than diameter of bar aggregate size 5 mm", ("IS456",)),
        Check("cover_beam", "Nominal cover to beam bars", ("cover_beam", "exposure_condition"),
              "nominal cover to meet durability requirements exposure mild moderate severe", ("IS456",)),
        Check("anchorage", "Anchorage at supports / curtailment", ("end_anchorage", "extra_top_bars", "support_condition"),
              "positive moment reinforcement at simple supports anchorage curtailment of tension reinforcement"),
        Check("span_depth", "Span/depth ratio (deflection)", ("clear_span", "beam_depth", "support_condition"),
              "control of deflection basic values span to effective depth ratio beams", ("IS456",)),
        Check("lap_location", "Lap location in beams", ("lap_location", "lap_length"),
              "splices in beams location away from maximum stress staggered laps", ("SP34",)),
    ],
}


def checks_for(drawing_type: DrawingType) -> List[Check]:
    return COMMON_CHECKS + TYPE_CHECKS.get(drawing_type, [])
